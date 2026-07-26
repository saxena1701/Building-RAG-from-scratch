from __future__ import annotations

from typing import Callable

from sentence_transformers import CrossEncoder

# Cross-encoder reranker. Ships with sentence-transformers (already a dependency), so no new
# package or API key is needed. Scores each (query, chunk_text) pair jointly, which is more
# accurate than the bi-encoder / BM25 / RRF signals the base retrievers rank on.
_RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(_RERANK_MODEL_NAME)
    return _model


def rerank_retrieve(
    query: str,
    db_url: str,
    base_retriever: Callable[..., dict],
    top_k: int = 5,
    candidate_k: int = 20,
) -> dict:
    """Retrieve a wide candidate_k pool from base_retriever, rerank with a cross-encoder, return top_k.

    Implements the retrieve-then-rerank flow: pull candidate_k (default 20) results from any base
    retriever, score every (query, chunk_text) pair jointly with a cross-encoder, and return the
    best top_k (default 5). Returns the standard shape
    {"results": [{chunk_id, source, text, score, base_rank}, ...]} ordered by rerank score
    (list order == rank).

    The added "score" is the cross-encoder relevance score and REPLACES any base score. These are
    raw logits (can be negative) and are not comparable to BM25 or RRF scores. "base_rank" is the
    chunk's 1-indexed position in the base pool, kept for debugging how far the reranker moved it.

    If the base retriever returns nothing (e.g. a lexical query with no term overlap), this returns
    {"results": []} without invoking the model.
    """
    candidates = base_retriever(query, db_url=db_url, top_k=candidate_k)["results"]
    if not candidates:
        return {"results": []}

    model = _get_reranker()
    scores = model.predict([(query, c["text"]) for c in candidates])

    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)[:top_k]
    return {
        "results": [
            {
                "chunk_id": candidates[i]["chunk_id"],
                "source": candidates[i]["source"],
                "text": candidates[i]["text"],
                "score": float(scores[i]),
                "base_rank": i + 1,
            }
            for i in order
        ]
    }


def make_reranking_retriever(
    base_retriever: Callable[..., dict],
    candidate_k: int = 20,
) -> Callable[..., dict]:
    """Bind a base retriever + candidate_k into a standard (query, db_url, top_k) callable.

    This makes reranked variants a drop-in for the RETRIEVERS dicts in the entry-point scripts and
    for run_eval, which all call retrievers as retriever(query, db_url=..., top_k=...). The base
    retriever is chosen at registration time (there is intentionally no default).
    """

    def _retriever(query: str, db_url: str, top_k: int = 5) -> dict:
        return rerank_retrieve(
            query, db_url, base_retriever=base_retriever, top_k=top_k, candidate_k=candidate_k
        )

    _retriever.__name__ = f"rerank_{getattr(base_retriever, '__name__', 'base')}"
    return _retriever
