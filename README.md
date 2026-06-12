# Building RAG from Scratch

A production-ready Retrieval-Augmented Generation (RAG) system built from first principles. This project demonstrates how to build a complete RAG pipeline: from document parsing through semantic search and retrieval.

## Overview

RAG enhances language models by retrieving relevant information from a knowledge base before generating responses. This system implements a typical RAG pipeline:

```
Documents → Parser → Chunker → Embedder → Vector DB → Retrieval
```

## Architecture

### Phase 1: Mock Documents

The knowledge base resides in `data/knowledge_base/` and contains both markdown and PDF documents:

```
data/knowledge_base/
├── marketsphere_kb_meta/
│   └── manifest.jsonl          # Index of all documents
└── marketsphere_kb/
    ├── markdown/               # .md files
    └── pdf/                    # .pdf files
```

**Manifest Format** (`manifest.jsonl`):
Each line is a JSON object describing one document:
```json
{
  "document_id": "doc_001",
  "path": "marketsphere_kb/markdown/guide.md",
  "format": "markdown",
  "title": "User Guide",
  "source": "internal"
}
```

**Why This Design:**
- Manifest decouples document metadata from file system structure
- Supports multiple formats (markdown, PDF) with extensible parser
- Metadata enables filtering and ranking at retrieval time

---

### Phase 2: Parser

**File:** `rag_core/parser.py`

The parser extracts text and metadata from documents. It handles multiple formats and normalizes them into a standard `Document` format.

#### Document Format

```python
@dataclass
class Document:
    source_id: str                    # Unique identifier (e.g., "doc_001")
    text: str                         # Full document text
    metadata: dict[str, Any]          # Manifest fields + extracted headings
```

#### Parsing Strategies

**Markdown Parsing:**
- Reads file as UTF-8 text
- Extracts ATX headings (`#`, `##`, `###`, etc.) as structural metadata
- Preserves full text for later chunking

**PDF Parsing:**
- Uses `unstructured` library with "fast" strategy
- Extracts:
  - **Titles** → section headings
  - **NarrativeText** → body paragraphs
  - **ListItems** → bullets and numbered lists
- Strips non-content elements (e.g., footers, page numbers)

#### Example Usage

```python
from rag_core.parser import parse_knowledge_base, save_documents

# Parse all documents from manifest
documents = parse_knowledge_base("data/knowledge_base")

# Save to JSONL for later processing
save_documents(documents, "data/parsed/documents.jsonl")
```

**Output:** JSONL file with one document per line
```json
{"source_id": "doc_001", "text": "...", "metadata": {...}}
```

---

### Phase 3: Setting Up pgvector Database

PostgreSQL with the `pgvector` extension provides vector similarity search. This enables semantic retrieval based on meaning, not keywords.

#### Database Setup

```bash
# Create database
createdb rag_db

# Enable pgvector extension
psql -d rag_db -c "CREATE EXTENSION IF NOT EXISTS vector"

# Create chunks table with vector column
psql -d rag_db -f - << 'EOF'
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata JSONB NOT NULL,
    embedding vector(384),                    -- 384-dim embedding vector for all-MiniLM-L6-v2
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast vector similarity search
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);

-- GIN index for efficient metadata filtering
CREATE INDEX ON chunks USING gin (metadata);

-- Full-text search index for BM25 hybrid retrieval
CREATE INDEX ON chunks USING gin (to_tsvector('english', text));
EOF
```

#### Connection Configuration

Store database URL in `.env`:
```
DATABASE_URL=postgresql://user:password@localhost:5432/rag_db
```

**Why pgvector?**
- Native PostgreSQL integration (no separate vector DB)
- HNSW indexing provides fast approximate nearest neighbor search (~O(log N))
- JSONB metadata with GIN indexing enables efficient filtering on document attributes
- Full-text search (tsvector) can be combined with semantic search for hybrid retrieval

**Index Breakdown:**
- **HNSW (vector_cosine_ops):** Hierarchical Navigable Small World algorithm for vector similarity—faster and more flexible than IVFFLAT
- **GIN (metadata):** Enables efficient filtering queries like `WHERE metadata->>'source' = 'doc_001'`
- **GIN (tsvector):** Enables full-text search for BM25-style keyword matching as fallback

---

### Phase 4: Chunker

**File:** `rag_core/chunker.py`

Documents are too large for embedding (APIs have token limits). Chunking splits documents into manageable pieces while preserving context through overlapping windows.

#### Chunk Format

```python
@dataclass
class Chunk:
    chunk_id: str                     # e.g., "doc_001_c0"
    source_document_id: str           # Reference to source document
    text: str                         # Chunk text
    metadata: dict[str, Any]          # Document metadata + chunk stats
```

#### Chunking Algorithm

The chunker uses **token-aware chunking** to respect API limits:

1. **Calibration**: Count tokens in full document to estimate `chars_per_token` ratio
2. **Windowing**: Create fixed-size windows based on estimated character count
3. **Verification**: Count actual tokens; trim if over budget
4. **Overlap**: Retain `overlap` tokens from previous chunk to preserve context

**Why Token-Aware?**
- Character count alone is unreliable (varies by language, punctuation)
- Ensures chunks fit within embedding API token limits (~512 tokens for typical models)
- Overlap prevents losing context at chunk boundaries

#### Configuration

```python
chunk_all(
    documents,
    max_tokens=500,    # Target chunk size
    overlap=50,        # Context from previous chunk
)
```

**Example Output:**
```json
{
  "chunk_id": "doc_001_c0",
  "source_document_id": "doc_001",
  "text": "Chapter 1: Introduction...",
  "metadata": {
    "chunk_index": 0,
    "chunk_total": 5,
    "chunk_tokens": 498,
    "headings": ["Introduction", "Overview"],
    ...
  }
}
```

---

### Phase 5: Embedder

**File:** `rag_core/embedder_retriever.py`

Embeddings convert text to dense vectors in a high-dimensional space. Semantically similar texts have vectors close together, enabling similarity-based retrieval.

#### Model: all-MiniLM-L6-v2

- **Type:** Sentence-Transformers (fine-tuned BERT)
- **Dimensions:** 384 (compact yet effective)
- **Performance:** ~40x faster than base BERT, minimal accuracy loss
- **Training:** Optimized for semantic similarity via contrastive learning

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode(texts)  # Returns (batch_size, 384)
```

#### Indexing Workflow

```python
from rag_core import embed_and_index

chunks = load_chunks("data/chunks/chunks_v1.jsonl")

# Encode in batches and insert into database
embed_and_index(
    chunks,
    db_url="postgresql://...",
    batch_size=100,
)
```

**Process:**
1. Load chunks from JSONL
2. Encode text in batches (100 chunks at a time)
3. Insert embeddings into PostgreSQL with upsert logic
4. pgvector HNSW index automatically indexes new vectors

**Example Vector:**
```python
# Text: "Machine learning is a subset of AI"
# Embedding: [-0.034, 0.127, 0.089, ..., 0.045]  # 384 dimensions
```

---

### Phase 6: Retrieval

**File:** `rag_core/embedder_retriever.py` (retrieve function)

Retrieval finds the most relevant chunks to answer a user query using vector similarity.

#### Retrieval Process

1. **Encode Query:** Convert user query to embedding using same model
2. **Similarity Search:** Find chunks with nearest vectors (cosine distance)
3. **Return Top-K:** Return `top_k` most similar chunks with metadata

```python
from rag_core import retrieve

results = retrieve(
    query="How does the system handle errors?",
    db_url="postgresql://...",
    top_k=5,
)
```

**SQL Query:**
```sql
SELECT chunk_id, source_document_id, text
FROM chunks
ORDER BY embedding <=> %s::vector
LIMIT 5
```

The `<=>` operator computes cosine distance (PostgreSQL pgvector operator).

#### Output Format

```python
{
  "results": [
    {
      "chunk_id": "doc_001_c2",
      "source": "doc_001",
      "text": "Error handling involves try-catch blocks..."
    },
    ...
  ]
}
```

**Why This Works:**
- Query and chunks use the same embedding space
- Cosine distance naturally captures semantic similarity
- HNSW index ensures fast approximate nearest neighbor search (~O(log N))
- Top-K result set is small and can be post-processed for ranking/filtering

---

## Usage

### 1. Parse Documents

```bash
python -m rag_core.parser data/knowledge_base data/parsed/documents.jsonl
```

### 2. Chunk Documents

```bash
python -m rag_core.chunker data/parsed/documents.jsonl data/chunks/chunks_v1.jsonl
```

### 3. Embed and Index

```bash
python -m rag_core.embedder_retriever data/chunks/chunks_v1.jsonl
```

### 4. Query the System

```bash
python rag_retrieval.py
# Enter your query: What is machine learning?
# Returns top 5 most relevant chunks
```

---

## Configuration

### Environment Variables (`.env`)

```
ANTHROPIC_API_KEY=...          # For token counting during chunking
DATABASE_URL=...     # PostgreSQL + pgvector connection
```

## Dependencies

- **anthropic**: Token counting for accurate chunk sizing
- **pypdf**: PDF text extraction
- **unstructured[pdf]**: Advanced PDF parsing (layouts, tables, etc.)
- **sentence-transformers**: Embedding model
- **psycopg2-binary**: PostgreSQL driver
- **python-dotenv**: Environment variable management

---

## Architecture Decisions

| Decision | Trade-off | Rationale |
|----------|-----------|-----------|
| Token-aware chunking | Slower but accurate chunk sizes | APIs have token limits; prevents expensive failures |
| HNSW indexing | Approximate search (1-2% loss) vs. exact | Fast nearest neighbor search; 100x faster for 1M+ vectors; accuracy loss negligible |
| Sentence-Transformers | 384-dim vs. GPT-3 embeddings (1536-dim) | Sufficient for semantic search; 4x smaller, faster, self-hosted |
| PostgreSQL + pgvector | No specialized vector DB | Simpler ops; pgvector HNSW competitive with specialized DBs |
| Batch embedding | Higher latency per batch | 10-50x faster than single encoding; amortizes model load time |

---

## Next Steps

- **Reranking:** Use cross-encoders to rerank top-K results before LLM
- **Hybrid Search:** Combine vector search with BM25 full-text search
- **Metadata Filtering:** Pre-filter chunks by document type or date before similarity search
- **Query Expansion:** Expand queries with synonyms or reformulations for better coverage

---

## License

MIT
