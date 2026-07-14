from __future__ import annotations

from collections import defaultdict

from .embedder_retriever import retrieve
from .lexical_retriever import lexical_retrieve


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    rrf_k: int = 60,
    weights: list[float] | None = None,
) -> dict[str, float]:
    """Combine several ranked lists of chunk_ids into fused RRF scores.

    RRF is purely rank-based: a chunk at rank r (1-indexed) in a list contributes
    weight / (rrf_k + r). Scores from every list are summed, so a chunk surfaced by both
    retrievers is boosted. rrf_k dampens the influence of top ranks (standard default 60).

    weights (one per list, default all 1.0) let a stronger retriever count more. On a
    corpus where dense retrieval already dominates, up-weighting dense avoids the weaker
    lexical list diluting an otherwise-good dense ranking.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    scores: dict[str, float] = defaultdict(float)
    for ranked, weight in zip(ranked_lists, weights):
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += weight / (rrf_k + rank)
    return scores


def hybrid_retrieve(
    query: str,
    db_url: str,
    top_k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> dict:
    """Hybrid retrieval: fuse dense (pgvector) and lexical (BM25) results via RRF.

    Each branch is queried for a wider candidate_k pool, fused by chunk_id with
    reciprocal_rank_fusion, then truncated to top_k. Returns the standard shape
    {"results": [{chunk_id, source, text, score, retrievers}, ...]} ordered by fused
    score (list order == rank). source/text are pulled from whichever branch surfaced
    the chunk, so no extra DB round-trip is needed.

    dense_weight / lexical_weight tune the fusion balance. On this corpus dense retrieval
    is markedly stronger than BM25, so equal weights let lexical dilute a good dense
    ranking; up-weighting dense (and/or lowering candidate_k) narrows the gap. Defaults
    are 1.0/1.0 (plain RRF) so behavior is unchanged unless tuned.
    """
    dense = retrieve(query, db_url=db_url, top_k=candidate_k)["results"]
    lexical = lexical_retrieve(query, db_url=db_url, top_k=candidate_k)["results"]

    # Map chunk_id -> {source, text} and track which branches surfaced each chunk.
    info: dict[str, dict] = {}
    provenance: dict[str, list[str]] = defaultdict(list)
    for name, results in (("dense", dense), ("lexical", lexical)):
        for r in results:
            info.setdefault(
                r["chunk_id"], {"source": r["source"], "text": r["text"]}
            )
            provenance[r["chunk_id"]].append(name)

    dense_ids = [r["chunk_id"] for r in dense]
    lexical_ids = [r["chunk_id"] for r in lexical]
    fused = reciprocal_rank_fusion(
        [dense_ids, lexical_ids], rrf_k=rrf_k, weights=[dense_weight, lexical_weight]
    )

    ranked_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:top_k]

    return {
        "results": [
            {
                "chunk_id": cid,
                "source": info[cid]["source"],
                "text": info[cid]["text"],
                "score": fused[cid],
                "retrievers": provenance[cid],
            }
            for cid in ranked_ids
        ]
    }
