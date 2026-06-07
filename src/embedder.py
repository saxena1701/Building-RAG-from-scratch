from __future__ import annotations

import os
import json
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from chunker import Chunk

load_dotenv()

_MODEL_NAME = "all-MiniLM-L6-v2"
_BATCH_SIZE = 100

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _get_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def embed_and_index(chunks: list[Chunk], batch_size: int = _BATCH_SIZE) -> None:
    model = _get_model()
    conn = _get_conn()

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


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from chunker import load_chunks

    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/chunks/chunks_v1.jsonl")
    chunks = load_chunks(in_path)
    embed_and_index(chunks)
    print(f"\nDone. Indexed {len(chunks)} chunks.")
