# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch RAG pipeline over a synthetic e-commerce support knowledge base (`data/knowledge_base/marketsphere_kb/`). The pipeline stages are: parse → chunk → embed+index → retrieve (dense / lexical / hybrid) → optional cross-encoder rerank → evaluate. The corpus contains *deliberately* planted flaws (contradictions, stale archives, near-duplicates) documented in `data/knowledge_base/marketsphere_kb_meta/FLAWS.md` — retrieval quality is measured against these, so don't "fix" the corpus.

## Environment & setup

- Virtualenv lives in `ragEnv/` (Python 3.13). Activate with `source ragEnv/bin/activate` before running anything.
- Secrets in `.env` (loaded via `python-dotenv`): `DATABASE_URL` (Postgres + pgvector) and `ANTHROPIC_API_KEY` (used only for token counting during chunking).
- Package is installed editable as `rag-core`; import from the `rag_core` package.

## Database

Retrieval requires a running local Postgres with two extensions:
- **pgvector** — dense `vector(384)` similarity via HNSW (`embedding <=> query`).
- **pg_search (ParadeDB)** — BM25 lexical search. Bootstrap the BM25 index once after indexing: `python -m rag_core.lexical_retriever` (runs `ensure_bm25_index`).

The single `chunks` table (schema in README "Phase 3") holds `chunk_id`, `source_document_id`, `text`, `metadata` (JSONB), and `embedding`. Full DDL is in the README, not in a migration file.

## Common commands

Run the pipeline in order (each stage reads the previous stage's JSONL output under `data/`):

```bash
python -m rag_core.parser data/knowledge_base data/parsed/documents.jsonl
python -m rag_core.chunker data/parsed/documents.jsonl data/chunks/chunks_v1.jsonl
python -m rag_core.embedder_retriever data/chunks/chunks_v1.jsonl   # embeds + upserts into pgvector
python -m rag_core.lexical_retriever                               # one-time: build BM25 index
```

Query interactively / evaluate:

```bash
python rag_retrieval.py --retriever hybrid          # dense | lexical | hybrid | rerank-dense | rerank-hybrid
python eval_retrieval.py --retriever rerank-hybrid  # writes timestamped JSON to data/eval/results/
```

There is no test suite, linter, or build step configured — the eval harness (`eval_retrieval.py`, recall@k / MRR@k against `data/eval/retrieval_eval_v1.jsonl`) is the de facto correctness check when changing retrieval.

## Architecture notes

- **Retriever contract.** Every retriever is a callable `(query, db_url, top_k=5) -> {"results": [{chunk_id, source, text, score?, ...}]}`, list order == rank. This uniform shape is what makes retrievers swappable in the `RETRIEVERS` dicts in `rag_retrieval.py` / `eval_retrieval.py` and in `run_eval`. Preserve it when adding a retriever.
- **Composition over inheritance.** `hybrid_retrieve` calls `retrieve` (dense) + `lexical_retrieve` and fuses by Reciprocal Rank Fusion (rank-based, so it sidesteps reconciling cosine-distance vs. BM25 score scales). `make_reranking_retriever(base)` wraps *any* base retriever into the standard signature, pulling `candidate_k=20` then cross-encoding down to `top_k`. Reranked variants are registered by composing these — e.g. `make_reranking_retriever(hybrid_retrieve)`.
- **Public API** is re-exported from `rag_core/__init__.py`; entry-point scripts import from `rag_core`, not submodules.
- **Models are module-level singletons** loaded lazily (`_get_model` in `embedder_retriever.py`, `_get_reranker` in `reranker_retriever.py`). Embedding model is `all-MiniLM-L6-v2` (384-dim, must match the DB column); reranker is `cross-encoder/ms-marco-MiniLM-L-6-v2`. Both are self-hosted via `sentence-transformers` — no API calls at retrieval time.
- **Chunking is token-aware** (`chunker.py`): it calibrates chars-per-token from a live `anthropic` token count of the whole doc, then windows words to stay under `max_tokens=500` with `overlap=50`. This is the only place the Anthropic API is used; the model id is `claude-haiku-4-5-20251001`.

## Scoring / score semantics (easy to get wrong)

`score` in results is **not comparable across retrievers**: dense has no score, lexical returns BM25 relevance, hybrid returns fused RRF scores, and rerank returns raw cross-encoder logits (can be negative) that *replace* the base score. Don't threshold or compare scores across retriever types.

Eval excludes `no_answer` queries from recall/MRR (logged for manual review only), and reports metrics broken down by query `category` (`single_chunk`, `multi_chunk_synthesis`, `vocab_mismatch`).
