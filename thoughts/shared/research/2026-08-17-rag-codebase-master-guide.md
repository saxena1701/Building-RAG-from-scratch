---
date: 2026-08-17T19:58:47-04:00
researcher: Claude
git_commit: 233abf68920e5c114426a81faaf090e2ae35ec76
branch: main
repository: Building-RAG-from-scratch
topic: "Master guide: architecture, data flow, and current state of the RAG pipeline"
tags: [research, codebase, rag, retrieval, chunker, embedder, hybrid, reranker, multi-query, eval, master-guide]
status: complete
last_updated: 2026-08-17
last_updated_by: Claude
---

# Research: Master Guide to Building-RAG-from-scratch

## Research Question
Research the codebase and develop an understanding document that can serve as a master guide for this project.

## Summary
This is a solo/research-stage, from-scratch RAG **retrieval** pipeline (no answer-generation/LLM-completion step yet) built as ~1,100 lines across 9 modules in `rag_core/`, driven by two CLI entry points (`rag_retrieval.py`, `eval_retrieval.py`). Documents flow through 10 phases: parse → chunk (token-aware, Anthropic tokenizer-calibrated) → embed (MiniLM, 384-dim) → index (Postgres + pgvector, HNSW) → retrieve (dense / BM25-lexical via ParadeDB / RRF-hybrid) → rerank (cross-encoder, optional second stage) → multi-query fan-out (optional third stage, currently fixture-driven, not live-LLM) → evaluate (recall@k / MRR@k harness, category-broken-out, against a hand-labeled eval set with an intentionally flawed knowledge base). All five (soon six) retriever variants share one `(query, db_url, top_k) -> {"results": [...]}` interface, which is what lets the same `RETRIEVERS` dict be reused verbatim between the interactive CLI and the eval harness with zero drift.

The README (`README.md`) is itself already a comprehensive phase-by-phase architecture doc with code examples and a decisions table — treat it as the primary reference; this document adds the connective tissue (data flow, contracts, current uncommitted state, known issues) that ties the phases together and orients a new contributor or agent quickly. Two audit reports already exist at `audits/bugs.md` and `audits/production-readiness.md` (generated 2026-08-17 against this same commit) — this guide summarizes and cross-references them rather than re-deriving their findings.

**Notable current-state facts:**
- Working tree has uncommitted changes not yet reflected in the last commit (`233abf6`, "added query rewriter RAG phase"): a debug `print(q)` added to `multi_query_retriever.py`, the deletion of `tests/test_multi_query_retriever.py` (the only test file in the repo), and edits to `CLAUDE.md`/`.codex/*`/`AGENTS.md`.
- `thoughts/shared/{handoffs,plans,research,tickets}` exist but are empty (`.gitkeep` only) — no prior research/planning history to draw on.
- The README's "Phase 11" (query rewriting / multi-query) described in commit `233abf6` is implemented but not yet documented in `README.md` itself — `rag_core/multi_query_retriever.py` is real, wired into both CLIs as `"multiquery"`, but the README stops at Phase 10 (Evaluation).

## Detailed Findings

### Pipeline data flow (end to end)

```
data/knowledge_base/{marketsphere_kb_meta/manifest.jsonl, marketsphere_kb/{markdown,pdf}/*}
  → rag_core/parser.py :: parse_knowledge_base() → Document(source_id, text, metadata)
  → data/parsed/documents.jsonl (save_documents / load_documents)
  → rag_core/chunker.py :: chunk_all() → Chunk(chunk_id, source_document_id, text, metadata)
  → data/chunks/chunks_v1.jsonl (save_chunks / load_chunks)
  → rag_core/embedder_retriever.py :: embed_and_index() → Postgres `chunks` table (pgvector)
  → rag_core/lexical_retriever.py :: ensure_bm25_index() → ParadeDB BM25 index on same table (one-time bootstrap)
  → query time: retrieve() | lexical_retrieve() | hybrid_retrieve() | rerank_retrieve() | multi_query_retrieve()
  → rag_core/eval.py :: run_eval() against data/eval/retrieval_eval_v1.jsonl → data/eval/results/eval_<ts>.json
```

Each stage persists its output to JSONL before the next stage runs (`data/parsed/`, `data/chunks/`), so re-running downstream stages never re-does upstream work — a deliberate design choice (README "Architecture Decisions" table).

### Module-by-module reference

**`rag_core/parser.py`** (147 lines)
- `Document` dataclass: `source_id`, `text`, `metadata`.
- `load_manifest()` reads `marketsphere_kb_meta/manifest.jsonl` keyed by `document_id`.
- `parse_markdown()` — reads UTF-8, extracts ATX headings via regex (`rag_core/parser.py:38-43`) into `metadata["headings"]`.
- `parse_pdf()` — uses `unstructured.partition.pdf(strategy="fast")`, keeps `Title`/`NarrativeText`/`ListItem` elements, drops the rest (footers/page numbers).
- `parse_knowledge_base()` iterates the manifest, dispatches by `format` field, skips missing files silently (`rag_core/parser.py:101-102`).
- CLI: `python -m rag_core.parser [kb_dir] [out_path]`.

**`rag_core/chunker.py`** (170 lines)
- `Chunk` dataclass: `chunk_id` (`"{source_id}_c{idx}"`), `source_document_id`, `text`, `metadata`.
- Token-aware windowing: calibrates `chars_per_token` from one whole-document `anthropic.Anthropic().messages.count_tokens()` call (model `claude-haiku-4-5-20251001`, `rag_core/chunker.py:17,32-37`), then estimates/trims each window by character budget, with a real per-chunk word-level overlap carried forward.
- Requires `ANTHROPIC_API_KEY` — every chunking run makes one live API call per document purely for token counting (flagged in `audits/production-readiness.md` as untracked cost).
- Known latent edge case (see Known Issues below): overlap close to/exceeding `max_tokens` can degenerate the advance step to ~1 word/chunk (`rag_core/chunker.py:89-98`); not hit by current default `overlap=50`/`max_tokens=500`.
- CLI: `python -m rag_core.chunker [in_path] [out_path]`.

**`rag_core/embedder_retriever.py`** (117 lines)
- Model: `all-MiniLM-L6-v2` (`sentence-transformers`, 384-dim), lazily loaded singleton (`_get_model`).
- `embed_and_index()` batches (default 100), `INSERT ... ON CONFLICT (chunk_id) DO UPDATE` (idempotent upsert) into Postgres `chunks` table.
- **The whole batch loop runs inside one `with conn:` transaction** (`rag_core/embedder_retriever.py:39-71`) — a late-batch failure rolls back everything, including already-succeeded batches (`audits/bugs.md` HIGH #1).
- `retrieve()` — plain dense kNN: `ORDER BY embedding <=> %s::vector LIMIT top_k`. Returns `{"results": [{chunk_id, source, text}]}` — **no `score` key**, unlike every other retriever variant (`audits/bugs.md` MEDIUM/latent finding, relevant if `retrieve` is ever passed as a `base_retriever` to `multi_query_retrieve`).
- `_get_conn()` opens a fresh `psycopg2` connection per call — no pooling anywhere in the codebase.
- CLI: `python -m rag_core.embedder_retriever [chunks_path]` (reads `DATABASE_URL` from `.env`).

**`rag_core/lexical_retriever.py`** (81 lines)
- BM25 via ParadeDB's `pg_search` extension (Tantivy-backed), on the *same* `chunks` table as pgvector — one Postgres instance, two index types.
- `ensure_bm25_index()` — idempotent `CREATE EXTENSION IF NOT EXISTS pg_search` + `CREATE INDEX IF NOT EXISTS chunks_bm25_idx ... USING bm25 (chunk_id, text)`. Must be run once after `embed_and_index` (`python -m rag_core.lexical_retriever`) before `lexical`/`hybrid`/reranked-hybrid retrievers will work.
- `lexical_retrieve()` uses the `paradedb.match()` query builder (not raw `@@@` string interpolation) specifically so arbitrary NL queries (punctuation, boolean words) can't break Tantivy parsing; no-overlap queries return `{"results": []}` cleanly.
- Result shape matches dense: `{chunk_id, source, text, score}` — this *does* include `score`.

**`rag_core/hybrid_retriever.py`** (87 lines)
- `reciprocal_rank_fusion()` — pure rank-based RRF: `score += weight / (rrf_k + rank)`, default `rrf_k=60`, default weights `1.0/1.0`.
- `hybrid_retrieve()` — pulls `candidate_k=20` from both `retrieve()` and `lexical_retrieve()`, fuses by `chunk_id`, truncates to `top_k`. Adds `retrievers: ["dense"|"lexical", ...]` provenance field. `source`/`text` reused from whichever branch found the chunk first — no extra DB round-trip.
- Tuning note in both README and code: dense is markedly stronger on this corpus at equal weights, so lexical can dilute a good dense ranking; up-weight dense or lower `candidate_k` to compensate (not done by default).

**`rag_core/reranker_retriever.py`** (83 lines)
- Cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2` (also from `sentence-transformers` — no new dependency), lazy singleton.
- `rerank_retrieve()` implements retrieve-then-rerank: pull `candidate_k=20` from any `base_retriever`, score every `(query, chunk_text)` pair jointly, return top `top_k=5`. Replaces `score` with the cross-encoder logit (can be negative, only meaningful within-query) and adds `base_rank` (pre-rerank position).
- `make_reranking_retriever(base_retriever, candidate_k=20)` binds a base retriever into the standard `(query, db_url, top_k)` contract — this factory pattern (bind extra config at wiring time, expose the plain 3-arg call signature) is reused identically in `multi_query_retriever.py`.
- No try/except around `model.predict()` — a reranker crash loses all base results rather than degrading gracefully (`audits/production-readiness.md` MEDIUM).
- Two pre-wired variants in both CLIs: `rerank-dense`, `rerank-hybrid`.

**`rag_core/multi_query_retriever.py`** (147 lines) — newest phase, added in the most recent commit (`233abf6`), and the file with uncommitted changes
- `_min_max_normalize()` — scales a per-query score list to `[0,1]`; degenerate (len==1 or all-equal) lists map to `1.0` (needed because cross-encoder logits can be negative, so raw scores can't be compared/merged directly across differently-worded queries).
- `multi_query_retrieve(queries, db_url, base_retriever, top_k, final_k)` — takes an **already-assembled** list of queries (original + rewrites; no LLM call happens inside this function), dedups (order-preserving), fans each out to `base_retriever(q, db_url=db_url, top_k=top_k)`, normalizes each query's score list independently, unions by `chunk_id` keeping the **max** normalized score across queries, and records which `queries` surfaced each chunk. Sorted desc, truncated to `final_k`.
  - **Uncommitted bug**: line 51 (`rag_core/multi_query_retriever.py:51`) has a stray `print(q)` inside the dedup loop — prints every deduped query to stdout on every call. Landed in the same uncommitted diff that deletes `tests/test_multi_query_retriever.py` (`audits/bugs.md` HIGH #2). This looks like in-progress debugging, not finished work — worth cleaning up before committing.
- `make_multi_query_retriever(rewriter, base_retriever=None, per_query_k=5, include_original=True)` — wraps a `rewriter: Callable[[str], list[str]]` (rewrites only, not the original — "include original" policy lives centrally here) into the standard 3-arg retriever contract. Default `base_retriever` is `make_reranking_retriever(hybrid_retrieve)`, i.e. rerank-hybrid per sub-query.
- `passthrough_rewriter()` — trivial no-op rewriter (returns `[]`); with `include_original=True` this collapses multi-query back to plain rerank-hybrid.
- `fixture_rewriter(path)` — the **only rewriter actually wired into either CLI today**. Loads a precomputed `{query, rewrites}` JSONL (`data/eval/rewrites_v1.jsonl`) into a dict, returns `[]` for unseen queries. This keeps eval deterministic and avoids a live LLM/API-key dependency for now — but also means there is no live query-rewriting yet, despite the commit message ("added query rewriter RAG phase"). A live LLM-backed rewriter is implied as the next step by both the commit history and the production-readiness audit's note that this is the one place a rewriter API failure would currently crash the whole multi-query path (no try/except around `rewriter(query)`).

**`rag_core/eval.py`** (149 lines)
- `recall_at_k()` — `|expected ∩ retrieved| / |expected|`.
- `reciprocal_rank()` — `1/rank` of first hit in `relevant`, else `0.0`.
- `run_eval(eval_path, db_url, k, retriever)` — loads the eval JSONL, calls `retriever(query, db_url=db_url, top_k=k)` per row, scores rows with non-empty `expected_chunk_ids`; rows with `expected_chunk_ids == []` (category `no_answer`) are logged but excluded from aggregate metrics (no scoring threshold defined for them).
- Aggregates: overall `recall_at_k`/`mrr_at_k`, plus per-category breakdown across `_SCORED_CATEGORIES = ["single_chunk", "multi_chunk_synthesis", "vocab_mismatch"]`.
- `print_summary()` / `save_report()` — the one genuinely structured piece of observability in the whole codebase (per the production-readiness audit); everything else is bare `print()`.

**Entry points**
- `rag_retrieval.py` (48 lines) and `eval_retrieval.py` (54 lines) build an **identical** `RETRIEVERS` dict: `dense`, `lexical`, `hybrid`, `rerank-dense`, `rerank-hybrid`, `multiquery` (`make_multi_query_retriever(fixture_rewriter("data/eval/rewrites_v1.jsonl"))`). This is deliberately kept in lockstep so the CLI and the eval harness never diverge on what "hybrid" etc. means — flagged as a Positive in `audits/production-readiness.md`.
- **Eager import-time fixture load**: `RETRIEVERS` (and thus `fixture_rewriter(...)`, which opens and reads the JSONL immediately) is built at module import, before `argparse` runs — so `python rag_retrieval.py --retriever dense` still fails with `FileNotFoundError` if `data/eval/rewrites_v1.jsonl` is missing, even though that retriever choice never touches it (`audits/bugs.md` MEDIUM #3).
- `rag_retrieval.py` is a one-shot interactive script (`input()` prompt, prints top-5 with scores/provenance). `eval_retrieval.py` takes positional `eval_path`/`k` plus `--retriever`, prints the summary, and saves a timestamped JSON report.

**`rag_core/__init__.py`** — the public surface (`__all__`): `embed_and_index`, `retrieve`, `lexical_retrieve`, `ensure_bm25_index`, `hybrid_retrieve`, `rerank_retrieve`, `make_reranking_retriever`, `multi_query_retrieve`, `make_multi_query_retriever`, `fixture_rewriter`, `run_eval`, `save_report`, `print_summary`. Everything the two CLIs import comes from here.

### Data & fixtures

- `data/knowledge_base/` — a fictional "MarketSphere" e-commerce KB (`marketsphere_kb_meta/manifest.jsonl` + `marketsphere_kb/{markdown,pdf}/`). Contains `marketsphere_kb_meta/FLAWS.md` — an **intentionally flawed** fixture (contradiction, staleness, near-duplicate docs) purpose-built to stress-test retrieval quality (e.g. `data/eval/retrieval_eval_v1.jsonl` q02's trap: `shipping_policy_archive_2023_c0` states a stale `$35` threshold vs. the correct `$50`). This is a deliberate eval-quality design choice, not accidental data hygiene debt.
- `data/eval/retrieval_eval_v1.jsonl` — hand-labeled eval set: `query_id`, `category` (`single_chunk` | `multi_chunk_synthesis` | `vocab_mismatch` | presumably `no_answer`), `query`, `expected_chunk_ids`, `also_relevant_chunk_ids`, `notes`.
- `data/eval/rewrites_v1.jsonl` — precomputed `{query_id, query, rewrites: [3 paraphrases]}` per eval query; backs `fixture_rewriter` so `multiquery` eval runs are deterministic without a live LLM call.
- `data/eval/results/` — timestamped JSON reports from `save_report()` (gitignored-style working output, currently untracked in git status).
- `rag_db.session.sql` — a scratch/history file of ad-hoc SQL run against the DB (e.g. sample `paradedb.match()` queries) — not a schema file; the actual schema DDL lives in the README (Phase 3).

### Known issues (already audited — see `audits/bugs.md` and `audits/production-readiness.md`)

Both files were generated by a prior audit run against this exact commit + working tree and remain accurate as of this research. Highlights, not a re-derivation:

1. **HIGH** — `embed_and_index`'s single all-batch transaction discards already-succeeded batches on a late failure (`rag_core/embedder_retriever.py:39-71`).
2. **HIGH** — uncommitted `print(q)` debug line + concurrently-deleted `tests/test_multi_query_retriever.py` (`rag_core/multi_query_retriever.py:51`) — the only test file in the repo is currently gone from the working tree.
3. **MEDIUM** — eager fixture load at CLI import time regardless of chosen `--retriever` (`eval_retrieval.py:25`, `rag_retrieval.py:21`).
4. **MEDIUM, latent** — `retrieve()` omits `score`, which `multi_query_retrieve` requires from any `base_retriever` — currently unreached because the only wired multiquery variant uses reranked-hybrid as its base.
5. **MEDIUM, latent** — chunker's advance-step can degenerate near 1-word steps if `overlap` approaches `max_tokens`; not triggered by current defaults.
6. **MEDIUM, latent** — chunk token estimate is calibrated once per document and never re-verified per chunk against the real tokenizer.
7. **Systemic (production-readiness.md)** — zero `logging`, zero `except` blocks, zero timeouts anywhere in the codebase (grep-confirmed); no DB connection pooling; no retry/backoff; unpinned dependencies; two unused deps (`pgvector`, `pypdf`); no CI.

None of these are "broken right now" — they're prototype-stage gaps consistent with a project whose README already accurately frames it as "built from first principles" for learning/demonstration, plus one genuine in-flight regression (the print/deleted-test pair) that looks like uncommitted mid-debugging work.

## Code References
- `rag_core/parser.py:12-15` — `Document` dataclass
- `rag_core/parser.py:84-110` — `parse_knowledge_base()` orchestration
- `rag_core/chunker.py:21-25` — `Chunk` dataclass
- `rag_core/chunker.py:44-118` — `chunk_document()` token-aware windowing
- `rag_core/chunker.py:89-98` — degenerate-overlap edge case
- `rag_core/embedder_retriever.py:31-71` — `embed_and_index()`, all-or-nothing transaction
- `rag_core/embedder_retriever.py:74-103` — `retrieve()`, missing `score` key
- `rag_core/lexical_retriever.py:35-74` — `lexical_retrieve()` via `paradedb.match()`
- `rag_core/hybrid_retriever.py:9-30` — `reciprocal_rank_fusion()`
- `rag_core/hybrid_retriever.py:33-87` — `hybrid_retrieve()`
- `rag_core/reranker_retriever.py:22-63` — `rerank_retrieve()`
- `rag_core/reranker_retriever.py:66-83` — `make_reranking_retriever()` factory pattern
- `rag_core/multi_query_retriever.py:23-81` — `multi_query_retrieve()`
- `rag_core/multi_query_retriever.py:51` — uncommitted stray `print(q)`
- `rag_core/multi_query_retriever.py:84-116` — `make_multi_query_retriever()`
- `rag_core/multi_query_retriever.py:126-147` — `fixture_rewriter()`
- `rag_core/eval.py:39-109` — `run_eval()`
- `rag_core/__init__.py:1-26` — public API surface
- `rag_retrieval.py:15-22` — `RETRIEVERS` dict (interactive CLI)
- `eval_retrieval.py:19-26` — `RETRIEVERS` dict (eval harness), duplicated verbatim
- `data/eval/retrieval_eval_v1.jsonl` — labeled eval set
- `data/eval/rewrites_v1.jsonl` — fixture rewrites for `multiquery`

## Architecture Insights

- **Uniform retriever contract as the load-bearing convention**: every retriever variant — dense, lexical, hybrid, reranked, multi-query — is a `(query: str, db_url: str, top_k: int) -> {"results": [...]}` callable. This is what allows `make_reranking_retriever` and `make_multi_query_retriever` to be simple factories that *wrap* any earlier-stage retriever into the same shape, and what keeps `rag_retrieval.py`/`eval_retrieval.py`/`rag_core/eval.py::run_eval` from ever diverging on what a given retriever name means. The one crack in this contract (`retrieve()` lacking `score`) is exactly where a factory (`multi_query_retrieve`) that assumes the full shape would break.
- **Persist-then-advance pipeline**: each phase writes JSONL before the next reads it (parse→documents.jsonl, chunk→chunks.jsonl), so expensive upstream work (PDF parsing, Anthropic token-counting calls) is never silently redone.
- **Two-stage retrieval as a composable pattern, not a special case**: reranking and multi-query are both implemented as *wrappers around* a base retriever rather than as new standalone retrieval logic — `rerank_retrieve(base_retriever=...)` and `multi_query_retrieve(base_retriever=...)` both take "what to call for each query" as a parameter. This is why 5-6 retriever variants exist from combining only 3 real ideas (dense/lexical/hybrid × optional rerank × optional multi-query).
- **RRF over score fusion**: hybrid retrieval deliberately avoids reconciling dense cosine-distance and BM25 score scales by fusing on rank alone (RRF) — same reasoning is echoed in multi-query's choice to min-max normalize per-query score lists before merging (raw cross-encoder logits aren't comparable across differently-phrased queries either).
- **Eval-driven, not eyeballed**: `eval_retrieval.py` exercises the *actual* production retriever code (no mocking), against a corpus deliberately salted with traps (stale docs, near-duplicates) — this is a stronger-than-typical eval setup for a project this size.
- **Deliberate LLM-optionality in chunking vs. rewriting**: chunking makes a live Anthropic call (token counting) unconditionally; query rewriting deliberately does *not* yet (fixture-only) — the commit history and audits suggest live LLM rewriting is the next planned increment, not yet built.

## Historical Context (from thoughts/)
`thoughts/shared/{handoffs,plans,research,tickets}` all exist but contain only `.gitkeep` placeholders — no prior research, plans, or tickets are recorded there yet. This document is the first entry in `thoughts/shared/research/`.

## Related Research
None yet — no other documents exist under `thoughts/shared/research/`. `audits/bugs.md` and `audits/production-readiness.md` (repo root, not under `thoughts/`) are the closest prior analysis and are referenced throughout this document rather than duplicated.

## Open Questions
- Is a live LLM-backed query rewriter planned to replace/augment `fixture_rewriter` (implied by the "query rewriter RAG phase" commit message and the production-readiness audit's forward-looking note)? If so, `multi_query_retrieve`'s lack of error handling around `rewriter(query)` becomes a live risk rather than a latent one.
- Is an answer-generation ("G" of RAG) step planned? Currently this repo implements retrieval only — the README's own "Next Steps" section lists "Generation: Feed retrieved chunks to an LLM" as unbuilt.
- Should the uncommitted `print(q)` removal + test-file restoration (or rewrite) happen before any further work lands on top, given both audits flag it as the most actionable, lowest-risk fix available right now?
- The README documents Phases 1-10 in depth but stops before the multi-query phase (`rag_core/multi_query_retriever.py`) that's already implemented and wired into both CLIs — worth a README update once the fixture-vs-live-rewriter question above is resolved, so the doc doesn't describe stale scope.
