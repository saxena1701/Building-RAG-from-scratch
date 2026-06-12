from __future__ import annotations

import json

import psycopg2
from sentence_transformers import SentenceTransformer

from .chunker import Chunk

_MODEL_NAME = "all-MiniLM-L6-v2"
_BATCH_SIZE = 100

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _get_conn(db_url: str) -> psycopg2.extensions.connection:
    return psycopg2.connect(db_url)


def embed_and_index(
    chunks: list[Chunk],
    db_url: str,
    batch_size: int = _BATCH_SIZE,
) -> None:
    model = _get_model()
    conn = _get_conn(db_url)

    try:
        with conn:
            with conn.cursor() as cur:
                for i in range(0, len(chunks), batch_size):
                    batch = chunks[i : i + batch_size]
                    texts = [c.text for c in batch]

                    embeddings = model.encode(texts, show_progress_bar=True)

                    cur.executemany(
                        """
                        INSERT INTO chunks (chunk_id, source_document_id, text, metadata, embedding)
                        VALUES (%s, %s, %s, %s::jsonb, %s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE
                            SET text = EXCLUDED.text,
                                metadata = EXCLUDED.metadata,
                                embedding = EXCLUDED.embedding
                        """,
                        [
                            (
                                c.chunk_id,
                                c.source_document_id,
                                c.text,
                                json.dumps(c.metadata),
                                embedding.tolist(),
                            )
                            for c, embedding in zip(batch, embeddings)
                        ],
                    )

                    print(f"Indexed batch {i // batch_size + 1} ({len(batch)} chunks)")
    finally:
        conn.close()


def retrieve(query: str, db_url: str, top_k: int = 5) -> dict:
    model = _get_model()
    query_embedding = model.encode(query).tolist()

    conn = _get_conn(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, source_document_id, text
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, top_k),
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
            }
            for row in rows
        ]
    }
