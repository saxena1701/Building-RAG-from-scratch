# Codebase Audit: Building-RAG-from-scratch — Production Readiness Assessment

## Scope

Reviewed against `references/rag-production-checklist.md` (error handling & resilience, security & secrets, configuration, observability, testing, scalability & performance, dependency management, RAG-pipeline-specific risks). Same file set as the companion bug report: all of `rag_core/`, both entry-point scripts, `pyproject.toml`, `requirements.txt`, `.gitignore`, and a shape-only pass over `data/` (not read line-by-line — checked for checked-in secrets and confirmed the intentional-flaws fixture at `data/knowledge_base/marketsphere_kb_meta/FLAWS.md`). Excluded `ragEnv/`, `.git/`, `.beads/`, `.claude/skills/`, `data/eval/results/`.

`HEAD` is `233abf6`; the working tree has uncommitted changes (see `bugs.md` Scope section for the full list) — most relevant here is that `tests/test_multi_query_retriever.py` is currently deleted, so "no tests exist" below reflects the working tree, not the last commit.

## Executive Summary

This is a solo/research-stage RAG pipeline — no web layer, no authentication, no deployed service, CLI scripts driven by `input()` — and the code quality within that scope is reasonable: chunking is persisted rather than recomputed, embeddings are upserted idempotently, and the eval harness genuinely exercises the real retriever code paths rather than a mocked stand-in. But the gap between that and "production-ready" (the term the README uses) is large and systemic: there is **zero use of the `logging` module, zero `except` blocks, and zero timeouts anywhere in the codebase** (all three confirmed by exhaustive grep across `rag_core/` and the entry scripts) — every diagnostic is a bare `print()`, every external call (Postgres, Anthropic, the embedding/reranking models) is unbounded and un-retried, and a single failure anywhere in the chain currently takes down the whole request with no fallback. None of this is on fire today because nothing here is exposed to real traffic yet, but every item below is a prerequisite, not a nice-to-have, before this pipeline sits behind anything a user or a scheduled job depends on.

## Production Readiness Assessment

### Error handling & resilience
**[HIGH] No exception handling anywhere in the pipeline.** Grepping `rag_core/*.py` and both entry scripts for `except` returns zero matches. A Postgres connection drop, a reranker model failing to load, or an Anthropic API error propagates straight up and kills whatever was running, with no fallback to degraded behavior. Zero results *are* handled gracefully by `hybrid_retrieve`/`rerank_retrieve`/`multi_query_retrieve` (each returns `{"results": []}` rather than crashing) — that part is done right — but an actual exception is not. See `bugs.md` #1 (all-or-nothing indexing transaction) and #2/#4 for concrete instances.

**[HIGH] No timeouts on any external call.** `psycopg2.connect()` (`rag_core/embedder_retriever.py:28`), the Anthropic `count_tokens` call (`rag_core/chunker.py:32-37`), `SentenceTransformer.encode`, and `CrossEncoder.predict` are all synchronous with no timeout configured anywhere (grep for `timeout` across the codebase returns nothing). A hung DB connection or a slow API response blocks indefinitely.

**[MEDIUM] No retry/backoff logic.** No `tenacity`/`backoff` dependency and no manual retry loop anywhere — a single transient failure (rate limit, network blip) is fatal rather than retried.

### Security & secrets management
**[LOW] Secrets handling is actually fine.** `ANTHROPIC_API_KEY` and `DATABASE_URL` are loaded via `python-dotenv` from `.env`, which exists locally but is correctly listed in `.gitignore` and is not tracked by git (confirmed via `git status`). No hardcoded credentials found anywhere in source.

**[LOW] No web/API layer exists yet**, so rate-limiting and cost-based-DoS exposure (an unauthenticated endpoint triggering LLM calls) are not live risks today — flagged here only as a hard requirement the moment any of this is wrapped in a service.

**[LOW, forward-looking] No LLM answer-generation step exists in this repo at all** — only retrieval, plus one Anthropic call used purely for token counting during chunking. Indirect prompt injection via retrieved chunk text (the RAG-specific risk the checklist calls out) is therefore not reachable yet. Worth designing for now rather than retrofitting: whenever a "generate an answer from retrieved chunks" step is added, retrieved text should be a clearly separated channel from system instructions, not concatenated into one undifferentiated prompt string.

**[MEDIUM] Dependencies are unpinned** — see Dependency Management below; also a security-process gap (no way to know if an installed version has a known CVE).

### Configuration management
**[MEDIUM] Config is scattered as per-module constants, not centralized.** Model names (`_MODEL` in `chunker.py`, `_MODEL_NAME` in `embedder_retriever.py`, `_RERANK_MODEL_NAME` in `reranker_retriever.py`) and tuning knobs (`top_k`, `candidate_k`, `batch_size`, `rrf_k`, fusion weights) are each defined locally as function defaults. Fine at 8 modules; will get harder to reason about (e.g. "what candidate_k is actually used end-to-end for multiquery?") as more retriever variants are added.

**[MEDIUM] Fixture path is hardcoded and loaded eagerly regardless of which retriever is selected** — see `bugs.md` #3 (`eval_retrieval.py:25`, `rag_retrieval.py:21`). Also means both scripts implicitly assume they're run from the repo root; no path resolution relative to the script location.

### Observability
**[HIGH] No logging infrastructure at all.** Grepping for `import logging` / `logging\.` across the entire codebase returns zero results. Every piece of runtime information — chunk counts, indexing batch progress, eval results — is a bare `print()` (14+ call sites across `chunker.py`, `embedder_retriever.py`, `eval.py`, `lexical_retriever.py`, `multi_query_retriever.py`, `parser.py`). No log levels, nothing structured, nothing that could be filtered, redirected, or shipped to an aggregator without a rewrite.

**[HIGH] No visibility into the RAG-specific failure modes the checklist calls out.** Empty/low-relevance retrieval results aren't logged when they happen (they just flow through as an empty list). Reranker score distributions, query-rewrite output, and embedding-call latency aren't tracked anywhere outside the stray debug `print(q)` noted in `bugs.md` #2.

**[MEDIUM] No cost/token-usage tracking.** `chunk_all` makes one live Anthropic API call per document purely to count tokens, with no running total logged — invisible cost until the bill arrives, exactly the scenario the checklist warns about.

**[Positive]** `rag_core/eval.py`'s `print_summary`/`save_report` are a genuine, structured exception to the above — per-category recall@k/MRR@k with timestamped JSON reports persisted to `data/eval/results/`. Worth keeping as the pattern to extend, not replace.

### Testing coverage
**[HIGH] Zero automated test coverage right now.** The `tests/` directory does not currently exist — its only file, `tests/test_multi_query_retriever.py`, is deleted in the uncommitted working tree (see `bugs.md` #2). No CI configuration was found anywhere in the repo (no `.github/workflows`, no other CI config), so nothing would have caught either the coverage loss or the debug print even if the test still existed.

**[Positive]** `eval_retrieval.py` / `rag_core/eval.py` is a real, working eval harness — recall@k and MRR@k, broken out by query category (`single_chunk`, `multi_chunk_synthesis`, `vocab_mismatch`, plus a separate `no_answer` bucket), and it calls the actual retriever functions end-to-end rather than mocking them. It measures retrieval *quality*, not code correctness, though — it won't catch an unhandled exception or a shape mismatch like `bugs.md` #4, only silently-wrong rankings.

### Scalability & performance
**[MEDIUM] No DB connection pooling — a fresh `psycopg2` connection is opened and closed per call.** `retrieve()` and `lexical_retrieve()` each call `_get_conn` independently; `hybrid_retrieve` opens two connections per query; `multi_query_retrieve` fans this out again per rewritten query, entirely sequentially — no `asyncio`/threading/`concurrent.futures` anywhere in the codebase. For N rewritten queries that's up to 2N sequential DB round-trips plus N reranker passes, none overlapped.

**[MEDIUM] No caching of repeated identical queries** anywhere in the retrieval path.

**[LOW] No evidence of an ANN index (HNSW/IVFFlat) on the pgvector column** — the dense query orders by raw `<=>` distance over the full table. Immaterial at the current knowledge-base size, will not scale past a few thousand chunks.

**[Positive]** Chunking happens once at ingest and is persisted to `data/chunks/chunks_v1.jsonl` rather than recomputed per query — done right. Embeddings are upserted (`ON CONFLICT ... DO UPDATE`), so re-running after a successful prior run is safe and idempotent (though see `bugs.md` #1 for what happens when a run itself fails partway).

### Dependency management
**[MEDIUM] Zero version pins anywhere.** Both `requirements.txt` and `pyproject.toml` list dependencies with no `==` or even `>=` bounds. No lockfile. A clean install today and one six months from now can silently resolve to different versions with no way to reproduce the difference.

**[MEDIUM] Two dependencies are unused.** `pgvector` (in `requirements.txt` only) and `pypdf` (in both manifests) are never imported anywhere in the source (grep-confirmed) — PDF parsing actually goes through `unstructured.partition.pdf`, and the `::vector` cast is done via raw SQL string formatting, not the `pgvector` Python adapter. Dead weight in the install, and the fact that `pgvector` is only in one of the two manifests shows the two files have already drifted from each other.

**[LOW] Python floor is declared (`>=3.10` in `pyproject.toml`) but no upper bound and no `.python-version` file.**

### RAG pipeline-specific risks
**[HIGH] Retriever contract inconsistency** — full write-up in `bugs.md` #4 (dense `retrieve()` is missing the `score` key every other retriever variant provides). Flagged here as the representative instance of a broader gap: five retriever variants exist, nothing (no shared type, no test) enforces that they agree on result shape.

**[MEDIUM] No fallback on reranker failure.** `rerank_retrieve` (`rag_core/reranker_retriever.py`) has no try/except around `model.predict(...)` — a reranker crash (OOM loading the cross-encoder, unexpected input) loses the base retriever's results entirely instead of degrading to the unranked base ordering.

**[MEDIUM] No fallback on query-rewriter failure.** The only rewriter actually wired into either entry-point script is `fixture_rewriter` — a static JSONL lookup that can't fail at request time. But `make_multi_query_retriever`/`multi_query_retrieve` are public, documented to accept *any* `rewriter: Callable[[str], list[str]]`, and there's no try/except around the `rewriter(query)` call. The commit history ("added query rewriter RAG phase") and README's phased structure suggest a live LLM-backed rewriter is a planned next step — the moment that lands, a single rewriter API failure will crash the entire multi-query retrieval with no fallback to the original query.

**[Positive] No eval/production drift.** `eval_retrieval.py` and `rag_retrieval.py` build an identical `RETRIEVERS` dict and call every retriever through the same `(query, db_url, top_k)` interface that `rag_core.eval.run_eval` uses — this is exactly the kind of divergence the checklist warns about, and this repo does not have it.

**[Positive/contextual] The knowledge-base corpus intentionally contains contradiction, staleness, and near-duplicate documents** (`data/knowledge_base/marketsphere_kb_meta/FLAWS.md`) as a deliberate eval fixture for exercising retrieval quality — this is good practice, not a production content problem, and worth noting so it isn't mistaken for accidental data hygiene issues.

Chunking edge cases (degenerate overlap, unverified token estimates) are covered in `bugs.md` #5/#6 rather than duplicated here.

## Prioritized Action List

1. **[P0]** Remove the stray `print(q)` debug statement and restore/rewrite the deleted test file before committing — `rag_core/multi_query_retriever.py:51`, `tests/test_multi_query_retriever.py` (currently an in-flight regression, not yet committed).
2. **[P1]** Commit per batch instead of wrapping the whole indexing run in one transaction, so a late failure doesn't discard already-embedded batches — `rag_core/embedder_retriever.py:39-71`.
3. **[P1]** Add try/except with fallback-to-base-results around the reranker call and the rewriter call, so one component failing degrades gracefully instead of killing the whole request — `rag_core/reranker_retriever.py`, `rag_core/multi_query_retriever.py`.
4. **[P1]** Give dense `retrieve()` a `score` key so all retriever variants share one result contract, and add a test asserting the shared shape — `rag_core/embedder_retriever.py:94-103`.
5. **[P1]** Add real logging (the `logging` module) in place of bare `print()`, at minimum for retrieval-empty, reranker-score, and query-rewrite events — currently zero structured observability anywhere in the repo.
6. **[P1]** Add timeouts to every external call — `psycopg2.connect`, the Anthropic `count_tokens` call, model loads — none exist anywhere today.
7. **[P2]** Make the `"multiquery"` entry in `RETRIEVERS` lazy instead of eagerly reading its fixture file at import time regardless of the chosen retriever — `eval_retrieval.py:25`, `rag_retrieval.py:21`.
8. **[P2]** Pin dependency versions and drop the unused `pgvector`/`pypdf` entries from `requirements.txt`/`pyproject.toml`.
9. **[P2]** Clamp/assert `overlap < max_tokens` in `chunk_document` to prevent the degenerate near-duplicate-chunk case — `rag_core/chunker.py:89-98`.
10. **[P2]** Re-verify chunk token estimates against the real tokenizer at least once per chunk rather than trusting a document-wide char-per-token ratio — `rag_core/chunker.py:32-83`.
11. **[P2]** Reuse/pool DB connections instead of opening a fresh one per `retrieve()`/`lexical_retrieve()` call, and consider parallelizing the dense/lexical branches and the multi-query fan-out.
12. **[P2]** Either back the README's "production-ready" claim with the work above, or soften the framing to match the project's current research/prototype stage.
