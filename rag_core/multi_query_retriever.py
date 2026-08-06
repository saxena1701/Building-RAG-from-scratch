from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .hybrid_retriever import hybrid_retrieve
from .reranker_retriever import make_reranking_retriever


def _min_max_normalize(scores: list[float]) -> list[float]:
    """Scale scores to [0, 1]. Degenerate lists (len==1 or all-equal) map to 1.0 to avoid
    divide-by-zero; cross-encoder logits can be negative so min-max (not raw) is required.
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def multi_query_retrieve(
    queries: list[str],
    db_url: str,
    base_retriever: Callable[..., dict],
    top_k: int = 5,
    final_k: int | None = None,
) -> dict:
    """Fan a pre-computed list of queries out to base_retriever, normalize each per-query
    rerank-score list, then union/dedup by chunk_id keeping the max normalized score.

    queries is the full fan-out set (original + rewrites), already assembled by the caller
    (the agent-side rewriter, or an adapter like make_multi_query_retriever). No LLM call
    happens here. Empty/whitespace-only queries are dropped and duplicates removed
    (order preserved) before fan-out.

    For each qi, base_retriever(qi, db_url=db_url, top_k=top_k)["results"] is expected to
    already be reranked (e.g. make_reranking_retriever(hybrid_retrieve)) so its "score" is a
    per-query relevance score, not directly comparable across queries. Min-max normalizing
    each qi's score list independently puts them on the same [0, 1] scale before merging.

    Returns {"results": [{chunk_id, source, text, score, queries}, ...]} sorted by merged
    normalized score desc, truncated to final_k (None = return all).
    """
    seen_queries: set[str] = set()
    deduped_queries: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen_queries:
            seen_queries.add(q)
            deduped_queries.append(q)

    merged: dict[str, dict] = {}
    for q in deduped_queries:
        results = base_retriever(q, db_url=db_url, top_k=top_k)["results"]
        if not results:
            continue
        normalized = _min_max_normalize([r["score"] for r in results])
        for r, norm_score in zip(results, normalized):
            chunk_id = r["chunk_id"]
            entry = merged.get(chunk_id)
            if entry is None:
                merged[chunk_id] = {
                    "chunk_id": chunk_id,
                    "source": r["source"],
                    "text": r["text"],
                    "score": norm_score,
                    "queries": [q],
                }
            else:
                entry["queries"].append(q)
                if norm_score > entry["score"]:
                    entry["score"] = norm_score

    ranked = sorted(merged.values(), key=lambda e: e["score"], reverse=True)
    if final_k is not None:
        ranked = ranked[:final_k]

    return {"results": ranked}


def make_multi_query_retriever(
    rewriter: Callable[[str], list[str]],
    base_retriever: Callable[..., dict] | None = None,
    per_query_k: int = 5,
    include_original: bool = True,
) -> Callable[..., dict]:
    """Wrap a rewriter into the standard (query, db_url, top_k) retriever interface.

    rewriter takes the original query and returns only the rewrites (not the original) so the
    "include original" policy lives in one place, here. base_retriever is the per-query
    retrieve->rerank pipeline (default rerank-hybrid, i.e. make_reranking_retriever(hybrid_retrieve));
    it's a parameter so rerank-dense or others can be A/B'd.

    The standard top_k (what the CLI/eval pass) maps to final_k (size of the merged set);
    per_query_k is the per-query k_i passed to multi_query_retrieve's top_k.
    """
    if base_retriever is None:
        base_retriever = make_reranking_retriever(hybrid_retrieve)

    def _retriever(query: str, db_url: str, top_k: int = 5) -> dict:
        queries = list(rewriter(query))
        if include_original:
            queries = [query] + queries
        return multi_query_retrieve(
            queries,
            db_url,
            base_retriever=base_retriever,
            top_k=per_query_k,
            final_k=top_k,
        )

    _retriever.__name__ = f"multiquery_{getattr(base_retriever, '__name__', 'base')}"
    return _retriever


def passthrough_rewriter(query: str) -> list[str]:
    """Trivial rewriter that produces no rewrites. With include_original=True, this collapses
    make_multi_query_retriever to plain rerank-hybrid over just the original query.
    """
    return []


def fixture_rewriter(path: str | Path) -> Callable[[str], list[str]]:
    """Build a rewrite(query) -> list[str] callable from a precomputed rewrites JSONL fixture.

    Each line is a JSON object with at least "query" and "rewrites" fields (query_id is also
    expected in the file for traceability but isn't needed for lookup). Lets the CLI/eval run
    the full fan-out without a live agent or API key, and keeps eval deterministic. Queries not
    present in the fixture return [] (no rewrites, falls back to just the original).
    """
    rewrites_by_query: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rewrites_by_query[row["query"]] = row["rewrites"]

    def rewrite(query: str) -> list[str]:
        rewrites= rewrites_by_query.get(query, [])
        return rewrites;

    return rewrite
