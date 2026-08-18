# Production-Hardening Checklist for RAG Systems

Work through each section against the actual repo. Every item is a question to answer by reading code/config, not a box to tick blindly — note what's present, what's missing, and whether it matters given the project's real usage (a personal research tool has a different bar than something serving external traffic).

## 1. Error handling & resilience

- Do calls to external services (LLM APIs, embedding APIs, vector DB, any HTTP call) have timeouts? An unbounded call can hang a request indefinitely.
- Is there retry logic (with backoff) for transient failures, or does one flaky API call kill the whole pipeline?
- What happens when the retriever returns zero results? Does downstream code assume at least one result exists (`results[0]`, `results[:k]` assumed non-empty)?
- What happens when the LLM call fails or returns malformed output (e.g. the model doesn't return valid JSON when JSON was expected)?
- Are exceptions caught at the right layer, or is there a blanket `except Exception: pass` somewhere hiding real failures?
- Is there a circuit breaker or fallback behavior for a downstream service being down, or does every request just fail?

## 2. Security & secrets management

- Are API keys (OpenAI, Anthropic, Cohere, vector DB, etc.) loaded from environment variables / a secrets manager, or hardcoded/committed anywhere?
- Is there a `.env` file in the repo? Is it in `.gitignore`? Check `git log` isn't needed — just check current tracked files and `.gitignore` contents.
- If there's any API/web layer, is user input passed into prompts without sanitization? Prompt injection via user query text is the LLM-era equivalent of SQL injection — a malicious query could try to override system instructions.
- **Indirect prompt injection**: this is a RAG-specific risk most generic security reviews miss. If retrieved document chunks are inserted into the prompt, and those documents come from an untrusted or semi-trusted corpus (scraped web content, user uploads), instructions embedded in the retrieved text could hijack the LLM's behavior. Is there any isolation between "system instructions," "retrieved context," and "user query" in the prompt template, or is it all one undifferentiated string?
- If there's a query endpoint, is it rate-limited? An unauthenticated endpoint that triggers LLM/embedding API calls is a direct path to a large API bill (cost-based DoS), not just a traditional DoS concern.
- Are dependencies pinned to specific versions (not just `>=`), and is there any process for checking for known vulnerabilities (e.g. `pip-audit`)?

## 3. Configuration management

- Is configuration (model names, chunk sizes, top-k, API endpoints, DB paths) centralized, or scattered as magic numbers/strings across files?
- Is there a clear separation between dev/local config and anything resembling a prod config (even if this project doesn't have formal environments yet)?
- Are file paths hardcoded (absolute paths, paths assuming a specific working directory) in a way that would break if run from a different machine or directory?

## 4. Observability

- Is there any logging at all? If something fails at 2am, is there enough information in logs to diagnose it without reproducing locally?
- Are there logs/metrics around the RAG-specific failure modes: retrieval returning empty/low-relevance results, reranker scores, query rewrite output, chunk counts, embedding API latency?
- Is there any tracking of LLM/embedding API cost and token usage, or is that invisible until the bill arrives?
- If logs exist, do they ever log full prompts/documents that might contain sensitive user data, in a way that could be a privacy issue?

## 5. Testing coverage

- Is there a test suite at all, and does it cover the core retrieval/ranking logic, not just trivial cases?
- Are there tests for edge cases specific to this domain: empty corpus, empty query, query with no relevant matches, very long documents that need chunking, duplicate/near-duplicate documents?
- Is there an eval harness (this repo has `eval_retrieval.py` / `rag_core/eval.py`-style scripts) and is it actually exercised, or is it a one-off script that's gone stale?
- Do tests actually run against real logic, or do they mock so much that a real regression wouldn't be caught? (Check whether recently-deleted or recently-modified test files suggest test coverage is being lost over time — that's a signal worth surfacing, not something to silently note.)

## 6. Scalability & performance

- What's the retrieval strategy at scale — does it load the entire corpus/index into memory? Does that work at 10x or 100x the current data size?
- Are embeddings computed once and cached/persisted, or recomputed on every run/query? Recomputing embeddings for the same documents repeatedly is a common hidden cost.
- For hybrid/multi-query/reranking retrievers: do they make requests sequentially where they could be parallelized (e.g. multiple query variants, multiple reranker calls)?
- Is there any caching for repeated identical queries?
- Does chunking happen once at ingest time and get persisted, or does it happen on the fly per-query (wasteful and can produce inconsistent chunk boundaries across runs)?

## 7. Dependency management

- Is there a lockfile or pinned versions (`requirements.txt` with exact versions, or a lockfile from a modern tool), or loose version ranges that could silently break on reinstall?
- Are there unused dependencies bloating the install, or used dependencies missing from the manifest (works locally because of a stray global install, breaks in a clean environment)?
- Is the Python version pinned/declared anywhere (`pyproject.toml`, `.python-version`), or left implicit?

## 8. RAG pipeline-specific correctness risks

These are failure modes generic "is this production ready" checklists don't know to look for — pay special attention here since this is the part of the review that's actually differentiated for a RAG system:

- **Chunking edge cases**: what happens to documents shorter than the chunk size? Documents with unusual structure (tables, code blocks, non-UTF8 content)? Off-by-one errors in chunk overlap logic?
- **Embedding/index consistency**: if documents are re-ingested or updated, does the index get updated consistently, or can it drift out of sync with the source documents (stale embeddings pointing at content that's changed or been deleted)?
- **Retriever contract consistency**: if there are multiple retriever implementations (lexical, hybrid, multi-query, reranker-based), do they all return results in a consistent format/type? A bug where one retriever variant returns a different shape than another is a classic source of downstream breakage when they're swapped or composed.
- **Query rewriting failure modes**: if a query rewriter/multi-query step calls an LLM to expand or rewrite the query, what happens if that call fails or returns something unusable (empty string, malformed list)? Does it fall back to the original query, or does the whole pipeline break?
- **Reranker failure modes**: same question for reranking — does a reranker failure lose the original (unreranked) results, or does it propagate the failure?
- **Evaluation/production drift**: does the eval script test the same code path that production/real usage actually exercises, or has the eval harness diverged from the real pipeline over time (e.g. eval calls retriever functions directly while the "real" path goes through an extra wrapper the eval never touches)?
