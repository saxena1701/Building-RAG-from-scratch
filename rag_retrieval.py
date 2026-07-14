import argparse
import os

from dotenv import load_dotenv

from rag_core import hybrid_retrieve, lexical_retrieve, retrieve

RETRIEVERS = {
    "dense": retrieve,
    "lexical": lexical_retrieve,
    "hybrid": hybrid_retrieve,
}

load_dotenv()

parser = argparse.ArgumentParser(description="Interactively query the RAG index.")
parser.add_argument(
    "--retriever",
    choices=list(RETRIEVERS),
    default="dense",
    help="Which retriever to use (default: dense).",
)
args = parser.parse_args()

db_url = os.getenv("DATABASE_URL")
retriever = RETRIEVERS[args.retriever]

query = input("Enter your query: ")
results = retriever(query, db_url=db_url, top_k=5)

for i, r in enumerate(results["results"], 1):
    score = r.get("score")
    score_str = f" | score: {score:.4f}" if isinstance(score, (int, float)) else ""
    print(f"[{i}] chunk_id: {r['chunk_id']} | source: {r['source']}{score_str}")
    print(r["text"])
    if args.retriever == "hybrid" and "retrievers" in r:
        print(f"retrievers: {r['retrievers']}")
    print()
