# Codebase Audit: Building-RAG-from-scratch — Bugs & Correctness Issues

## Scope

Reviewed: all Python source under `rag_core/` (`__init__.py`, `chunker.py`, `embedder_retriever.py`, `eval.py`, `hybrid_retriever.py`, `lexical_retriever.py`, `multi_query_retriever.py`, `parser.py`, `reranker_retriever.py`) plus the two entry-point scripts `eval_retrieval.py` and `rag_retrieval.py`, `pyproject.toml`, `requirements.txt`, `.gitignore`, and the knowledge-base fixtures under `data/` (skimmed for shape/secrets, not read line-by-line). Excluded: `ragEnv/` (venv), `.git/`, `.beads/`, `.claude/skills/` (the skill under test itself), and `data/eval/results/` (generated eval output).

This is a full read of every source file, not a spot-check — the repo is 13 Python files, well under the threshold for parallelizing.

**Working-tree state matters here.** `HEAD` is `233abf6` ("added query rewriter RAG phase"), but the working tree has uncommitted changes: `rag_core/multi_query_retriever.py` has a one-line diff (an added `print(q)`), `tests/test_multi_query_retriever.py` has been deleted, and `CLAUDE.md`/`.codex/*`/`AGENTS.md` were also touched/deleted. This audit reflects the working tree as it stands, not just `HEAD` — see Bug #2 below, which only exists because of this uncommitted diff.

## Executive Summary

The retrieval logic itself (RRF fusion, min-max normalization, reranking, chunk persistence) is generally sound and the eval harness is real, not decorative — no manufactured bugs were needed to fill this report. The two most important findings are process-level, not algorithmic: an all-or-nothing DB transaction that can silently waste an entire indexing run's compute on any transient failure, and an in-flight uncommitted change that deletes the one existing test file in the same diff that adds a debug `print()` to the code that test covered. The remaining bugs are latent — correct today only because of how the code happens to be called — but sit close enough to the public API surface (`multi_query_retrieve`, `chunk_document`) that a small, reasonable change elsewhere would trigger them. Nothing found here is a "the pipeline is broken right now" bug; this reads as an early-stage but carefully-built prototype, not a system stress-tested against unhappy paths.

## Bugs & Correctness Issues

### [HIGH] All-or-nothing indexing transaction discards completed batches on failure — `rag_core/embedder_retriever.py:39-71`
**Issue:** `embed_and_index` wraps its entire batch loop in a single `with conn:` block opened *before* the loop, so nothing commits until every batch has succeeded.
**Failure scenario:** Indexing 500 chunks in batches of 100. Batch 4 of 5 raises (DB blip, OOM during `model.encode`, a malformed embedding) → the whole transaction rolls back, discarding batches 1-3 that had already succeeded — and the (expensive) embedding compute already spent on them. Re-running re-embeds everything from scratch instead of resuming.
**Fix:** Commit after each batch (`conn.commit()` inside the loop, or move `with conn:` inside it) so a late failure only loses the in-flight batch. This is also the representative instance of the "no retry/resilience around external calls" gap — see production-readiness.md's Error Handling section.

### [HIGH] Leftover debug print landed in the same uncommitted diff that deletes the file's only test — `rag_core/multi_query_retriever.py:51`
**Issue:** The working tree adds `print(q)` inside the query-dedup loop in `multi_query_retrieve`, and in the same uncommitted diff, `tests/test_multi_query_retriever.py` — which specifically covered dedup, score-merging, and truncation in this function — was deleted (confirmed via `git diff` / `git show HEAD:tests/test_multi_query_retriever.py`).
**Failure scenario:** As-is, this doesn't crash anything, but every call to `multi_query_retrieve` now writes each deduplicated query string to stdout (called once per fanned-out query per user request), and the test suite that would have caught a real regression here no longer exists. Read together, this is exactly what mid-debugging, about-to-be-committed work looks like — not a finished change.
**Fix:** Remove the `print(q)` before committing; restore the deleted test file (or replace it with an equivalent) rather than letting coverage silently regress to zero.

### [MEDIUM] Eager fixture load at import time blocks every invocation regardless of chosen retriever — `eval_retrieval.py:25`, `rag_retrieval.py:21`
**Issue:** `RETRIEVERS = {..., "multiquery": make_multi_query_retriever(fixture_rewriter("data/eval/rewrites_v1.jsonl"))}` is built at module import time, before `argparse` even runs. `fixture_rewriter` opens and fully reads that file immediately.
**Failure scenario:** Run `python rag_retrieval.py --retriever dense` (nothing to do with multiquery) from a fresh clone before `data/eval/rewrites_v1.jsonl` exists, or from a different working directory — the script fails with an unrelated `FileNotFoundError` before the user's actual retriever choice is ever consulted.
**Fix:** Build `RETRIEVERS["multiquery"]` lazily (e.g. a factory called only when `--retriever multiquery` is selected) instead of eagerly at import time.

### [MEDIUM, latent] Retriever result contract is inconsistent — dense `retrieve()` omits the `score` key that `multi_query_retrieve` requires — `rag_core/embedder_retriever.py:94-103`, `rag_core/multi_query_retriever.py:60`
**Issue:** `lexical_retrieve`, `hybrid_retrieve`, and `rerank_retrieve` all return `{"results": [{chunk_id, source, text, score, ...}]}`, but plain dense `retrieve()` returns `{"results": [{chunk_id, source, text}]}` — no `score`. `multi_query_retrieve` unconditionally does `[r["score"] for r in results]` (line 60) and its own docstring documents the (unenforced) expectation that `base_retriever` returns per-query relevance scores.
**Failure scenario:** This is currently unreached — the only registered `"multiquery"` retriever uses `make_reranking_retriever(hybrid_retrieve)` as its base, which does include `score`. But `multi_query_retrieve`/`make_multi_query_retriever` are public exports (`rag_core.__all__`) that accept any `base_retriever`. Passing plain `retrieve` (unreranked dense) as `base_retriever` — a completely reasonable "multiquery-dense" variant — raises `KeyError: 'score'` on the first call. Labeled latent/currently-unreached per the failure mode being real but not exercised by any current call site.
**Fix:** Add a `score` field to `retrieve()`'s output (e.g. `1 - cosine_distance`, or `None` with a `multi_query_retrieve`-side default), and add a test asserting all five retriever variants share one result shape.

### [MEDIUM, latent] Chunk-advance step can degenerate to ~1-word steps when overlap is close to the chunk size — `rag_core/chunker.py:89-98`
**Issue:** The advance-window loop breaks as soon as `advance_chars >= (accumulated - overlap_chars)`. When `overlap_chars` is close to (or exceeds) `accumulated`, that threshold is ≤0, so the loop breaks after a single word and `start_word` advances by `max(1, advance_words)` — as little as one word per chunk.
**Failure scenario:** Calling `chunk_document(doc, client, max_tokens=500, overlap=490)` — a config the function accepts with no validation — on a long document produces an enormous number of near-duplicate, one-word-shifted chunks. Not hit today because both call sites use the safe default (`overlap=50` vs. `max_tokens=500`), so this is latent, not live.
**Fix:** Assert/clamp `overlap < max_tokens` (or clamp to some fraction of it) at the top of `chunk_document`.

### [MEDIUM, latent] Token-count estimate is calibrated once and never re-verified against the real tokenizer — `rag_core/chunker.py:32-83`
**Issue:** `chars_per_token` is computed once from a single whole-document `count_tokens` API call, then every candidate chunk's token count is estimated purely via `len(candidate) / chars_per_token` — the real Anthropic tokenizer is never called again to confirm a trimmed chunk actually fits `max_tokens`.
**Failure scenario:** A document mixing dense prose with a table or code block (very different chars-per-token density than the document average) can produce chunks that silently exceed `max_tokens` by a meaningful margin, which then get embedded/consumed downstream against a budget that's wrong. The current markdown/PDF knowledge base is fairly uniform prose, so this hasn't manifested yet — latent for the present corpus, live risk for less uniform future documents.
**Fix:** Re-verify the final trimmed candidate with one real `count_tokens` call per chunk (or explicitly document the estimate-only tradeoff and clamp `max_tokens` with headroom).

## Notes

Findings that are fundamentally about systemic patterns rather than a single file:line — no error-handling fallback around reranker/rewriter failures, zero timeouts on any external call, no connection pooling — are covered in `production-readiness.md` rather than duplicated here in full; each has a one-line cross-reference above where it overlaps with a specific bug.
