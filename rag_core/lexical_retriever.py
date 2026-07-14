from __future__ import annotations

import os

from dotenv import load_dotenv

from .embedder_retriever import _get_conn

_BM25_INDEX = "chunks_bm25_idx"


def ensure_bm25_index(db_url: str) -> None:
    """Idempotently install ParadeDB's pg_search and build the BM25 index on chunks.

    Safe to run repeatedly; a fresh clone can call this once (after embed_and_index)
    to bootstrap lexical retrieval. Requires the pg_search extension to be available
    on the Postgres server.
    """
    conn = _get_conn(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {_BM25_INDEX}
                    ON chunks USING bm25 (chunk_id, text)
                    WITH (key_field = 'chunk_id')
                    """
                )
    finally:
        conn.close()


def lexical_retrieve(query: str, db_url: str, top_k: int = 5) -> dict:
    """BM25 lexical retrieval via ParadeDB (pg_search).

    Returns the same shape as embedder_retriever.retrieve so it is a drop-in for the
    eval harness and interactive script: {"results": [{chunk_id, source, text, score}, ...]}
    ordered by BM25 relevance (list order == rank).

    Uses the paradedb.match() query builder rather than the raw `text @@@ %s` string form
    so arbitrary natural-language queries (punctuation, quotes, boolean words) are treated
    as plain OR'd terms and cannot break Tantivy query parsing. A query with no indexed
    term overlap simply returns {"results": []}, letting RRF degrade to dense-only.
    """
    conn = _get_conn(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, source_document_id, text, paradedb.score(chunk_id) AS score
                FROM chunks
                WHERE chunk_id @@@ paradedb.match('text', %s)
                ORDER BY paradedb.score(chunk_id) DESC
                LIMIT %s
                """,
                (query, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return {
        "results": [
            {
                "chunk_id": row[0],
                "source": row[1],
                "text": row[2],
                "score": float(row[3]),
            }
            for row in rows
        ]
    }


if __name__ == "__main__":
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    ensure_bm25_index(db_url)
    print(f"Ensured pg_search extension and {_BM25_INDEX} index.")
