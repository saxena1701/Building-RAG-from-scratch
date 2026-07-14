from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .embedder_retriever import retrieve

_SCORED_CATEGORIES = ["single_chunk", "multi_chunk_synthesis", "vocab_mismatch"]


def load_eval_set(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def recall_at_k(expected: list[str], retrieved: list[str]) -> float:
    hits = len(set(expected) & set(retrieved))
    return hits / len(expected)


def reciprocal_rank(relevant: set[str], retrieved: list[str]) -> float:
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_eval(
    eval_path: str | Path,
    db_url: str,
    k: int = 5,
    retriever: Callable[..., dict] = retrieve,
) -> dict[str, Any]:
    rows = load_eval_set(eval_path)

    per_query: list[dict[str, Any]] = []
    for row in rows:
        retrieved = [
            r["chunk_id"] for r in retriever(row["query"], db_url=db_url, top_k=k)["results"]
        ]
        expected = row["expected_chunk_ids"]
        also_relevant = row["also_relevant_chunk_ids"]

        if expected:
            recall = recall_at_k(expected, retrieved)
            rr = reciprocal_rank(set(expected), retrieved)
        else:
            recall = None
            rr = None

        per_query.append(
            {
                "query_id": row["query_id"],
                "category": row["category"],
                "query": row["query"],
                "expected_chunk_ids": expected,
                "also_relevant_chunk_ids": also_relevant,
                "retrieved_chunk_ids": retrieved,
                "recall": recall,
                "reciprocal_rank": rr,
            }
        )

    scored = [q for q in per_query if q["recall"] is not None]
    unscored = [q for q in per_query if q["recall"] is None]

    by_category: dict[str, Any] = {}
    for category in _SCORED_CATEGORIES:
        category_rows = [q for q in scored if q["category"] == category]
        by_category[category] = {
            "count": len(category_rows),
            "recall_at_k": _mean([q["recall"] for q in category_rows]),
            "mrr_at_k": _mean([q["reciprocal_rank"] for q in category_rows]),
        }

    aggregate = {
        "k": k,
        "recall_at_k": _mean([q["recall"] for q in scored]),
        "mrr_at_k": _mean([q["reciprocal_rank"] for q in scored]),
        "scored_count": len(scored),
        "by_category": by_category,
        "no_answer": {
            "count": len(unscored),
            "note": "excluded from recall@k/MRR@k (no score/threshold available); retrieved_chunk_ids logged for manual review",
            "rows": [
                {"query_id": q["query_id"], "retrieved_chunk_ids": q["retrieved_chunk_ids"]}
                for q in unscored
            ],
        },
    }

    return {
        "k": k,
        "retriever": getattr(retriever, "__name__", str(retriever)),
        "eval_path": str(eval_path),
        "results": per_query,
        "aggregate": aggregate,
    }


def print_summary(report: dict[str, Any]) -> None:
    k = report["k"]
    for q in report["results"]:
        if q["recall"] is None:
            print(f"[{q['query_id']}] {q['category']:<20} (unscored)")
        else:
            print(
                f"[{q['query_id']}] {q['category']:<20} "
                f"recall@{k}={q['recall']:.2f}  MRR@{k}={q['reciprocal_rank']:.2f}"
            )
        print(f"    expected={q['expected_chunk_ids']}")
        print(f"    also_relevant={q['also_relevant_chunk_ids']}")
        print(f"    retrieved={q['retrieved_chunk_ids']}")

    agg = report["aggregate"]
    print()
    print(f"retriever: {report.get('retriever', 'retrieve')}")
    print(f"{'category':<22} {'n':>3}  {'recall@' + str(k):>10}  {'MRR@' + str(k):>8}")
    for category, stats in agg["by_category"].items():
        print(
            f"{category:<22} {stats['count']:>3}  "
            f"{stats['recall_at_k']:>10.2f}  {stats['mrr_at_k']:>8.2f}"
        )
    print(
        f"{'OVERALL':<22} {agg['scored_count']:>3}  "
        f"{agg['recall_at_k']:>10.2f}  {agg['mrr_at_k']:>8.2f}"
    )
    print(f"{'no_answer (unscored)':<22} {agg['no_answer']['count']:>3}")


def save_report(report: dict[str, Any], out_dir: str | Path = "data/eval/results") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return out_path
