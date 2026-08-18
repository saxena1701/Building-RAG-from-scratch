---
name: codebase-audit
description: Search the codebase for bugs, correctness errors, and defects, and separately produce a production-readiness / production-hardening review with prioritized recommendations covering error handling, security, secrets management, observability, testing, scalability, dependency management, and RAG-pipeline-specific risks (retrievers, rerankers, chunkers, query rewriting, embeddings, vector store). Writes two standalone markdown files — one bug report, one production-readiness report. Use this skill whenever the user asks to find bugs, audit the codebase, review the whole project, do a production hardening pass, ask "is this ready to ship / deploy / go to prod", request a security or reliability review, or want a punch list before a release — even if they don't say "audit" or "production ready" explicitly.
---

# Codebase Audit

This skill produces two standalone markdown files: a **bug report** (concrete correctness defects, cited by file and line) and a **production-readiness report** (systemic gaps between "it works on my machine" and "it survives real traffic, real users, and real failure modes"). They're separate deliverables with separate audiences in mind — someone triaging "what's broken right now" doesn't want to wade through hardening philosophy, and someone planning a hardening roadmap doesn't want it interleaved with line-level bug triage. Do both passes, write both files, every time this skill runs — they're cheap to produce together and expensive to reconcile later if only one exists.

**Default output locations** (create the directory if it doesn't exist):
- `audits/bugs.md`
- `audits/production-readiness.md`

If the user specifies a different location or filename, use that instead. Each run overwrites the previous report for that scope — these are meant to reflect current state, not accumulate history. If the user wants a dated snapshot instead (e.g. to track progress over time), use `audits/bugs-<YYYY-MM-DD>.md` / `audits/production-readiness-<YYYY-MM-DD>.md`.

## Why this is two passes, not one

Bugs and hardening gaps are found differently. Bugs come from close reading: tracing a function's logic, checking what happens on the exception path, noticing an off-by-one or a mismatched type. Hardening gaps come from zooming out: does this project have *any* logging? What happens if the OpenAI/Anthropic API call times out — does anything catch it? Is there a `.env` file that might be accidentally committable? Trying to do both while reading the same line of code splits your attention and you'll do a mediocre job of each. Read the code once for bugs, then step back and read the project's shape for hardening gaps.

## Step 1: Scope the audit

Ask yourself (don't necessarily ask the user, unless the repo is large and it's genuinely ambiguous) what's in scope:

- **Whole repo** (default when the user says "audit the codebase" / "is this production ready") — everything except generated artifacts, virtual envs, `node_modules`, and data directories.
- **A subset** if the user names a module, directory, or recent change ("review my retriever code", "audit what I just built").

For a small-to-medium repo (roughly under ~30 source files), read it directly with Read/Grep — no need to parallelize. For a larger repo, split by top-level module/package and spawn a few `Explore` or general-purpose subagents in parallel, each covering one slice, then merge their findings before writing the report yourself. Don't spawn a subagent per file — that's wasteful and loses cross-file context (e.g. a bug in how module A calls module B is invisible if each is read in isolation).

Always exclude: `.git/`, virtual environments (`venv`, `.venv`, `env`, `ragEnv`, etc.), `node_modules`, build artifacts, and large data/results directories — skim their existence (are secrets or raw data checked in?) but don't read their contents line by line.

Run `git status` early and treat uncommitted changes as in-scope, not noise. A repo mid-edit tells you things a clean checkout doesn't — a deleted test file sitting next to a debug `print()` added in the same diff is a real finding (it reads as abandoned work about to be committed), and you'd miss it entirely by only looking at HEAD. If there are uncommitted changes, note in the Scope section that the audit reflects the working tree, not just the last commit, and record which commit HEAD was at — findings are cited by file:line, and lines drift as the code changes, so a reader needs to know what state was actually audited.

## Step 2: Bug hunt

Read the actual source, not just filenames. For each file in scope, look for:

- **Logic errors**: off-by-one, inverted conditionals, wrong variable used, incorrect boundary handling
- **Exception paths**: what happens when a call fails? Silent `except: pass`, swallowed errors, or exceptions that propagate somewhere unhelpful
- **Type/contract mismatches**: a function assumes a list is never empty, a dict key always exists, an API response always has a given field
- **Resource handling**: unclosed files/connections, missing timeouts on network calls, unbounded loops or recursion
- **State and mutation bugs**: shared mutable default arguments, global state that isn't reset between calls, race conditions if anything is concurrent
- **Dead or unreachable code**: a strong signal something was half-refactored and never finished
- **Copy-paste drift**: near-duplicate functions/classes where one was fixed and the other wasn't (common across retriever variants, for example)

For every bug, capture: file path, line number, a one-sentence description of the defect, and — critically — the concrete failure scenario (what input or sequence of events triggers it, and what actually goes wrong). "This could be cleaner" is not a bug; "if the retriever returns zero results, `results[0]` on line 42 raises an IndexError and the whole query fails" is a bug.

Don't manufacture bugs to have something to report. If a file is clean, say so briefly and move on — padding the report with nitpicks dilutes the findings that actually matter.

Some real bugs are **latent**: correct code today only because of how it happens to be wired up elsewhere, but one call-site change away from breaking (e.g. a function that assumes a dict key exists, which happens to always be true given the current callers). These are genuinely worth reporting — they're exactly the kind of thing that survives code review and then breaks in production after a seemingly-unrelated change — but don't let them masquerade as active failures. Label them explicitly as latent/currently-unreached in the failure scenario, and keep the severity a notch below what you'd give the same bug if it were live.

## Step 3: Production-hardening review

Step back from individual lines and assess the project as a system. Read `references/rag-production-checklist.md` for the full checklist — it's organized by category (error handling & resilience, security & secrets, configuration, observability, testing, scalability & performance, dependency management, and RAG-pipeline-specific risks like retrieval failure modes, prompt injection via retrieved content, and embedding/index drift). Work through each category and note what's present, what's missing, and how much it matters for *this* project's actual risk profile — a solo research prototype and a system serving external users need different bars, so calibrate severity accordingly rather than flagging every missing enterprise pattern as critical.

Ground findings in what you actually observe in the repo (config files, `requirements.txt`/`pyproject.toml`, presence or absence of a test directory, CI config, logging calls, `.env` handling) — don't assume industry-standard tooling is present or absent without checking.

## Step 4: Write the two reports

Each file is self-contained — someone should be able to open just one and get everything they need, without cross-referencing the other. Keep both scannable: engineers reading these want to know what to fix first, not to read prose.

### `audits/bugs.md`

```markdown
# Bug Report: <repo/module name>

_Audited at commit <short-sha> (or "uncommitted changes on top of <short-sha>" if the working tree isn't clean) on <date>._

## Scope
What was reviewed (paths), what was excluded, and roughly how deep the read was (full read vs. spot-check for very large areas).

## Summary
2-4 sentences: how many bugs, how many are severe, and the single most important one to fix first. Be honest and direct — a report that soft-pedals a real defect is worse than useless.

## Findings
For each bug, in descending severity:

### [SEVERITY] Short title — `path/to/file.py:line`
**Issue:** one-sentence description.
**Failure scenario:** concrete input/condition → concrete wrong behavior. If latent (see below), say so explicitly here.
**Fix:** one or two sentences on the fix direction (not a full patch unless asked).

## Prioritized Fix List
Flat, ordered punch list, ranked by (impact × likelihood):

1. **[P0]** ... — one line, with the file reference
2. **[P1]** ...
3. **[P2]** ...
```

### `audits/production-readiness.md`

```markdown
# Production Readiness Report: <repo/module name>

_Audited at commit <short-sha> (or "uncommitted changes on top of <short-sha>" if the working tree isn't clean) on <date>._

## Scope
Same as the bug report — what was reviewed, what was excluded, how deep the read was.

## Verdict
3-6 sentences: overall health, the single biggest systemic risk, and whether this is "close to production-ready" or "early-stage prototype." Name the project's actual risk profile you're calibrating against (solo prototype vs. serving real users) so the reader knows the bar being applied.

## Assessment by Category
One subsection per checklist category that has findings (skip categories with nothing to report, or note "no issues found" briefly). Within each category, order findings by descending severity. For each finding:

**[SEVERITY] Title** — what's missing/wrong, why it matters for this project specifically, and what to do about it.

If a finding is really a specific bug (concrete file:line, concrete failure scenario) rather than a systemic gap, it belongs in `bugs.md` instead — reference it here in one line rather than writing it up twice (e.g. "See `bugs.md`: retriever score-contract gap — also an instance of missing input-contract validation across the retriever interface.").

Categories to consider (see `references/rag-production-checklist.md` for detail):
- Error handling & resilience
- Security & secrets management
- Configuration management
- Observability (logging, metrics, tracing)
- Testing coverage
- Scalability & performance
- Dependency management
- RAG pipeline-specific risks (retrieval failure modes, chunking edge cases, embedding/index consistency, reranker/query-rewriter failure handling, prompt injection via retrieved documents, cost/rate-limit exposure on LLM and embedding API calls)

## Prioritized Hardening Roadmap
Flat, ordered punch list, ranked by (impact × likelihood):

1. **[P0]** ... — one line
2. **[P1]** ...
3. **[P2]** ...
```

Both prioritized lists use P0 (breaks correctness or is a real security hole / actively unsafe), P1 (will bite in production but isn't on fire), P2 (worth doing, not urgent). Don't inflate everything to P0 — a list where everything is critical helps no one prioritize. Severity labels used inline (`[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]`) should map onto P0-P2 consistently: CRITICAL/HIGH → P0/P1, MEDIUM → P1/P2, LOW → P2.

**Each file gets its own list — don't merge them.** `bugs.md`'s Prioritized Fix List ranks only the findings in that file's own Findings section; `production-readiness.md`'s Prioritized Hardening Roadmap ranks only that file's own Assessment findings. It's tempting to build one combined ranked list across both bugs and hardening gaps and drop it in whichever file feels like the "main" one — resist that. The whole point of splitting into two files was so each stands alone; a reader who opens only `bugs.md` still needs to know which of *its* bugs to fix first, and a combined list living in the other file defeats that. If a specific bug is important enough to also drive the hardening roadmap, it can appear in both lists (bugs.md's list ranks it as a bug fix; production-readiness.md's list ranks it as an instance of a systemic gap) — that's a deliberate, limited exception to the "don't duplicate write-ups" rule above, not a contradiction of it, since here it's just a one-line list entry in each place, not a full write-up.

Use the section headers shown in the templates above verbatim (`## Summary`, `## Verdict`, `## Prioritized Fix List`, `## Prioritized Hardening Roadmap`, etc.) rather than substituting your own phrasing (e.g. don't write "Executive Summary" in `bugs.md` when the template says `Summary`) — consistent headers are what make these reports easy to diff against a future run.

## Tone

Be direct and specific, not diplomatic-to-the-point-of-vague. "Consider possibly adding some error handling in some places" is useless. "The three retriever classes each make an unguarded API call with no timeout and no retry — a slow embedding API will hang the whole request" is useful. The point of this skill is to give the user criticism they can act on, not reassurance.

Aim for each report to be readable in under 10 minutes — for most small-to-medium repos that lands around 60-100 lines per file. If you're well past that, you're probably over-explaining individual findings rather than trusting the reader; tighten prose before cutting real findings.

After writing both files, tell the user where they landed (both paths) and give a one-line summary of what each contains — don't just say "done," since the value here is two artifacts they can open, share, or diff against a future run.
