# MarketSphere Knowledge Base Corpus

This is the document corpus for Compass Phase 3 (RAG). It contains 152 documents across four source types, in two formats, with deliberate flaws baked in.

## Structure

```
marketsphere_kb/
  policies/        30 markdown files — terms of service, returns, shipping, warranty, etc.
  faqs/            45 markdown files — short Q&A entries
  runbooks/        26 markdown files — internal support procedures
  manuals/         51 PDFs           — product manuals across 6 product categories

marketsphere_kb_meta/
  manifest.jsonl   one JSON record per document (id, path, type, dates, format, notes)
  FLAWS.md         documents the four deliberate flaws — DO NOT READ until after retrieval eval
```

## Source types in detail

**Policies** are formal company-published documents. Markdown, multi-section, written in formal tone. These are the canonical source for questions like "what's the return window," "how does shipping work."

**FAQs** are short customer-facing question/answer pairs. Markdown, simple structure (Question section + Answer section). Two FAQs intentionally near-duplicate each other.

**Runbooks** are internal support procedures, not customer-facing. Markdown, with audience and resolution-tree structure. One legacy runbook deliberately contradicts the current policy — your retrieval needs to handle this.

**Manuals** are product PDFs. 51 products across 6 categories (headphones, kitchen appliances, fitness, smart home, outdoor, apparel care). Each PDF has 8-9 sections including box contents, setup, troubleshooting, warranty, and specifications. PDFs vary in document date (random spread across the past 2 years) to give you metadata to play with.

## What this corpus is designed to teach

This corpus is *intentionally not clean*. Specifically:

1. **Three formats** force you to write real parsers. PDFs in particular have quirks you'll only see by parsing them — broken paragraph boundaries, lost table structure, unexpected whitespace.

2. **Four deliberate flaws** mirror the kinds of problems present in every real enterprise KB:
   - Contradictions between current policy and outdated runbooks
   - Stale archived documents still present in the corpus
   - Near-duplicate entries from multiple authors writing about the same thing
   See `marketsphere_kb_meta/FLAWS.md` for details — but resist reading it until after your first retrieval evaluation pass. The whole point is to discover these issues through your retrieval metrics, not to know about them in advance.

3. **Mixed date ranges** give you metadata for freshness-aware retrieval experiments. Most documents are from 2024; some are from 2023 and earlier.

4. **Realistic content** means the documents reference each other, share vocabulary, and cover overlapping topics. This is what makes retrieval hard — not the volume, but the topical overlap.

## How to use

For Phase 3 Step 1, you have the corpus done. Move directly to Step 2 (parsing). The parsers you write will need to handle:
- `.md` files in `policies/`, `faqs/`, `runbooks/`
- `.pdf` files in `manuals/`

Both ultimately produce `Document` objects with normalized text and the metadata from `manifest.jsonl`.

For Phase 3 Step 6 (retrieval eval), you'll hand-write query/expected-chunk pairs against this corpus. A good starting set covers:
- Direct policy lookups ("what's the return window for electronics?")
- Multi-document synthesis ("can I return open headphones I bought on sale?")
- Vocabulary mismatches (ask about "refund" when the policy says "reimbursement")
- The flaw cases (which version of the policy does retrieval prefer?)
- Cross-format queries (product manual question + policy question in one)

For Phase 3 Step 11 (final integration), this corpus becomes Compass's `search_knowledge_base` source. When Compass is asked about return policy, shipping, product setup, or troubleshooting, it queries this KB.

## Regeneration

The generator script is `generate_corpus.py`. It uses `random.seed(42)` so output is reproducible. You can modify the script to:
- Add more documents in any category
- Add more deliberate flaws
- Change product categories
- Adjust dates for freshness experiments

The script depends on `reportlab` for PDF generation: `pip install reportlab`.
