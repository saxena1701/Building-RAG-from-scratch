from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

from .parser import Document, load_documents

_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class Chunk:
    chunk_id: str
    source_document_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def count_tokens(text: str, client: anthropic.Anthropic) -> int:
    resp = client.messages.count_tokens(
        model=_MODEL,
        messages=[{"role": "user", "content": text}],
    )
    return resp.input_tokens


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_document(
    doc: Document,
    client: anthropic.Anthropic,
    max_tokens: int = 500,
    overlap: int = 50,
) -> list[Chunk]:
    words = doc.text.split()
    if not words:
        return []

    # Calibrate chars-per-token from the full document.
    full_tokens = count_tokens(doc.text, client)
    if full_tokens == 0:
        return []

    chars_per_token = len(doc.text) / full_tokens
    target_chars = max_tokens * chars_per_token
    overlap_chars = overlap * chars_per_token

    chunks: list[Chunk] = []
    start_word = 0

    while start_word < len(words):
        # Estimate ending word index from char budget.
        accumulated = 0
        end_word = start_word
        while end_word < len(words) and accumulated < target_chars:
            accumulated += len(words[end_word]) + 1
            end_word += 1

        # Verify and trim/grow to fit within max_tokens.
        candidate = " ".join(words[start_word:end_word])
        actual_tokens = int(len(candidate) / chars_per_token)

        # Trim if over budget.
        while actual_tokens > max_tokens and end_word > start_word + 1:
            end_word -= 1
            candidate = " ".join(words[start_word:end_word])
            actual_tokens = int(len(candidate) / chars_per_token)

        chunks.append((start_word, end_word, candidate, actual_tokens))

        if end_word >= len(words):
            break

        # Advance start, leaving overlap_chars worth of words behind.
        advance_chars = 0
        advance_words = 0
        for w in words[start_word:end_word]:
            advance_chars += len(w) + 1
            advance_words += 1
            if advance_chars >= (accumulated - overlap_chars):
                break

        start_word = start_word + max(1, advance_words)

    # Patch in chunk_total now that we know it, then build Chunk objects.
    total = len(chunks)
    result: list[Chunk] = []
    for idx, (_, _, text, tokens) in enumerate(chunks):
        metadata = {
            **doc.metadata,
            "chunk_index": idx,
            "chunk_total": total,
            "chunk_tokens": tokens,
        }
        result.append(
            Chunk(
                chunk_id=f"{doc.source_id}_c{idx}",
                source_document_id=doc.source_id,
                text=text,
                metadata=metadata,
            )
        )
    return result


def chunk_all(
    documents: list[Document],
    max_tokens: int = 500,
    overlap: int = 50,
) -> list[Chunk]:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    all_chunks: list[Chunk] = []
    for i, doc in enumerate(documents, 1):
        doc_chunks = chunk_document(doc, client, max_tokens, overlap)
        all_chunks.extend(doc_chunks)
        print(f"[{i}/{len(documents)}] {doc.source_id} → {len(doc_chunks)} chunk(s)")
    return all_chunks


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_chunks(chunks: list[Chunk], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(dataclasses.asdict(chunk), ensure_ascii=False) + "\n")


def load_chunks(input_path: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk(**json.loads(line)))
    return chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/parsed/documents.jsonl")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/chunks/chunks_v1.jsonl")

    docs = load_documents(in_path)
    chunks = chunk_all(docs)
    save_chunks(chunks, out_path)
    print(f"\nSaved {len(chunks)} chunks to {out_path}")
