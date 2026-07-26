#!/usr/bin/env bash
# Stop hook: keep CLAUDE.md in sync with implementation changes.
#
# Fires once at the end of each turn. If Python source changed vs the last
# commit, it spawns a headless `claude -p` pass that reviews the working-tree
# diff and makes minimal edits to CLAUDE.md so its documented architecture /
# commands / structure stay accurate.
set -euo pipefail

# --- Re-entry guard -----------------------------------------------------------
# The `claude -p` we spawn below loads this same Stop hook. Bail out inside that
# nested invocation, otherwise every sync would spawn another sync forever.
[ -n "${CLAUDE_MD_SYNC:-}" ] && exit 0

# Need the CLI and a git repo to do anything useful.
command -v claude >/dev/null 2>&1 || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# --- Detect implementation changes -------------------------------------------
# Tracked changes vs HEAD + untracked files, limited to Python source, with
# CLAUDE.md itself excluded (editing it must not re-arm the trigger).
changed=$(
  { git diff HEAD --name-only 2>/dev/null
    git ls-files --others --exclude-standard 2>/dev/null; } \
  | grep -E '\.py$' \
  | grep -v -E '(^|/)CLAUDE\.md$' \
  || true
)
[ -z "$changed" ] && exit 0

# --- Sync CLAUDE.md in the background -----------------------------------------
CLAUDE_MD_SYNC=1 claude -p "An implementation change was just made in this repository. Review the working-tree changes with \`git diff HEAD\` and update CLAUDE.md so its documented architecture, module/component descriptions, commands, and project structure stay accurate. Make minimal, surgical edits — change ONLY what is now out of date. Do not document trivial, cosmetic, or clearly in-progress changes. If CLAUDE.md is already accurate, make no edits at all." \
  --permission-mode acceptEdits \
  --allowedTools "Read" "Edit(CLAUDE.md)" "Bash(git diff:*)" "Bash(git status:*)" \
  >/dev/null 2>&1 || true

exit 0
