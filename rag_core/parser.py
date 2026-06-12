from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any



@dataclass
class Document:
    source_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> dict[str, dict]:
    """Return a dict keyed by document_id from the JSONL manifest."""
    entries: dict[str, dict] = {}
    with open(manifest_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                entries[entry["document_id"]] = entry
    return entries


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def _extract_md_headings(text: str) -> list[str]:
    """Return all ATX headings (# / ## / ###) found in the markdown text."""
    return [
        m.group(2).strip()
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
    ]


def parse_markdown(file_path: Path, manifest_entry: dict) -> list[Document]:
    """
    Parse a single markdown file into one Document.

    Metadata contains all manifest fields plus:
      - headings: ordered list of section headings found in the file
    """
    text = file_path.read_text(encoding="utf-8")
    headings = _extract_md_headings(text)

    metadata = {**manifest_entry, "headings": headings}

    return [Document(source_id=manifest_entry["document_id"], text=text.strip(), metadata=metadata)]


# ---------------------------------------------------------------------------
# PDF parser
# ---------------------------------------------------------------------------

def parse_pdf(file_path: Path, manifest_entry: dict) -> list[Document]:
    from unstructured.partition.pdf import partition_pdf
    from unstructured.documents.elements import NarrativeText, Title, ListItem

    elements = partition_pdf(filename=str(file_path), strategy="fast")

    headings = [e.text for e in elements if isinstance(e, Title)]
    body_elements = [e for e in elements if isinstance(e, (NarrativeText, Title, ListItem))]
    text = "\n\n".join(e.text for e in body_elements if e.text.strip())

    metadata = {**manifest_entry, "headings": headings}

    return [Document(source_id=manifest_entry["document_id"], text=text, metadata=metadata)]


# ---------------------------------------------------------------------------
# Knowledge-base loader
# ---------------------------------------------------------------------------

def parse_knowledge_base(kb_dir: str | Path) -> list[Document]:
    """
    Parse all documents in the knowledge base directory.

    Expects:
      <kb_dir>/marketsphere_kb_meta/manifest.jsonl
      <kb_dir>/marketsphere_kb/<source_type>/<file>

    Returns a flat list of Document objects for all files listed in the manifest.
    """
    kb_dir = Path(kb_dir)
    manifest_path = kb_dir / "marketsphere_kb_meta" / "manifest.jsonl"
    manifest = load_manifest(manifest_path)

    documents: list[Document] = []
    for entry in manifest.values():
        file_path = kb_dir / entry["path"]
        if not file_path.exists():
            continue

        fmt = entry.get("format", "")
        if fmt == "markdown":
            documents.extend(parse_markdown(file_path, entry))
        elif fmt == "pdf":
            documents.extend(parse_pdf(file_path, entry))

    return documents


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_documents(documents: list[Document], output_path: str | Path) -> None:
    """Serialize documents to a JSONL file, one Document per line."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for doc in documents:
            record = {"source_id": doc.source_id, "text": doc.text, "metadata": doc.metadata}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_documents(input_path: str | Path) -> list[Document]:
    """Deserialize documents from a JSONL file produced by save_documents."""
    documents: list[Document] = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                documents.append(Document(**record))
    return documents


if __name__ == "__main__":
    import sys

    kb_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/knowledge_base")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/parsed/documents.jsonl")

    docs = parse_knowledge_base(kb_dir)
    save_documents(docs, out_path)
    print(f"Saved {len(docs)} documents to {out_path}")
