import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from rag_core import (
    hybrid_retrieve,
    lexical_retrieve,
    print_summary,
    retrieve,
    run_eval,
    save_report,
)

RETRIEVERS = {
    "dense": retrieve,
    "lexical": lexical_retrieve,
    "hybrid": hybrid_retrieve,
}

load_dotenv()

parser = argparse.ArgumentParser(description="Evaluate a retriever on the eval set.")
parser.add_argument(
    "eval_path",
    nargs="?",
    default="data/eval/retrieval_eval_v1.jsonl",
    help="Path to the eval JSONL file.",
)
parser.add_argument("k", nargs="?", type=int, default=5, help="top_k / cutoff for recall@k and MRR@k.")
parser.add_argument(
    "--retriever",
    choices=list(RETRIEVERS),
    default="dense",
    help="Which retriever to evaluate (default: dense).",
)
args = parser.parse_args()

db_url = os.getenv("DATABASE_URL")

report = run_eval(
    Path(args.eval_path), db_url=db_url, k=args.k, retriever=RETRIEVERS[args.retriever]
)
print_summary(report)

out_path = save_report(report)
print(f"\nSaved report to {out_path}")
