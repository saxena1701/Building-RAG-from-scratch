# Deliberate Flaws in the MarketSphere Knowledge Base

This document records the intentional flaws baked into the corpus. **Do not read this before completing your retrieval evaluation in Phase 3.** Read it afterward to verify your retrieval system handles each flaw appropriately.

These flaws mirror the kinds of problems present in real enterprise knowledge bases.

---

## Flaw 1: Contradiction

**Documents involved**: return_policy, electronics_return_addendum, runbook_electronics_returns_legacy

**Description**: Return policy and electronics addendum say 30-day window with 15% restocking fee for opened electronics. Legacy runbook says 14 days with 20% fee. The runbook is outdated (2023) but still in the corpus, as often happens in real companies.

**Expected good-RAG behavior**: Good RAG with metadata filtering or freshness signals should prefer the newer policy. Bare RAG will surface both and the LLM may give conflicting answers depending on which is retrieved.

---

## Flaw 2: Staleness

**Documents involved**: shipping_policy, shipping_policy_archive_2023

**Description**: An archived 2023 shipping policy still in the corpus shows $35 free shipping threshold and lower prices. Current policy says $50. The archive header says it's historical, but a naive retriever doesn't read headers.

**Expected good-RAG behavior**: Naive retrieval will sometimes surface the archived version for queries like 'what's free shipping threshold'. Better retrieval uses date metadata to prefer recent docs.

---

## Flaw 3: Near Duplicate

**Documents involved**: faq_track_order, faq_track_order_alt

**Description**: Two FAQ entries that essentially answer the same 'how do I track' question with different wording. Common in real KBs where multiple authors create overlapping content.

**Expected good-RAG behavior**: Naive retrieval may return both, wasting the top-k budget. Deduplication or reranking should reduce this.

---

## Flaw 4: Near Duplicate

**Documents involved**: faq_free_shipping, faq_free_shipping_amount

**Description**: Two FAQ entries about the free shipping threshold with slightly different framing.

**Expected good-RAG behavior**: Same as above - good retrieval should consolidate.

---

