#!/usr/bin/env python3
"""
SkillGod SessionEnd hook.

Fires when Claude Code closes a session. Summarizes what was worked on during
the session — referencing the decision/pattern memory rows that hooks/post_tool.py
already captured while the session was live — and commits that summary to SQLite,
keyed to the correct project AND git branch/commit.

Two writes, both best-effort and both idempotent-safe:
  1. The `sessions` table row is finalized (ended_at + summary) via end_session().
     start_session() is called first (INSERT OR IGNORE) so a session whose id the
     start hook never persisted still gets a real, closed row instead of a silent
     no-op UPDATE against a missing id.
  2. A branch-tagged `context` memory row is saved via save_with_git() — the SAME
     git-tagging path post_tool.py uses — so the summary is recallable in future
     sessions through get_recent()/sg timeline and is genuinely keyed to the git
     branch (the sessions table itself has no branch column).

Project identity is resolved the SAME way every other hook and the MCP server
resolve it: derive_project_id() (git remote / abspath hash), never the bare
folder name, so this summary lands under the same key the rest of the session's
memory did.

Follows the established hook conventions: reads its input from stdin as JSON,
writes through the shared memory layer, and FAILS SAFELY BUT VISIBLY — any error
is surfaced on stderr rather than swallowed, and never crashes session teardown.

Wire in ~/.claude/settings.json (done automatically by `sg init`):
  "hooks": {
    "SessionEnd": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\path\\to\\hooks\\session_end.py"}]
    }]
  }

Input  (stdin): JSON with optional keys { "session_id": "...", "project": "..." }
Output (stdout): none required — this is a teardown hook, not an injection hook.
"""

import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

# Windows: hook stdout/stderr are pipes (legacy cp1252 default) — emit UTF-8
# so summary text containing non-ANSI characters can't crash session teardown.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")


def _derive_project_id() -> str:
    """Collision-resistant project id (BUG-016), matching every other hook.
    Falls back to the folder name only if the memory helper can't be imported."""
    try:
        from memory import derive_project_id
        return derive_project_id()
    except Exception:
        return Path.cwd().name


def _build_summary(mems: list) -> str:
    """Compose a one-line session summary from the memory rows post_tool.py
    captured during the session. No LLM call — cheap and deterministic, matching
    the decision-heuristic philosophy of the rest of the memory layer."""
    if not mems:
        return "Session summary — no decisions or patterns captured this session"
    by_kind: dict[str, int] = {}
    for m in mems:
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    counts = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
    head = "; ".join(m["summary"][:70].strip() for m in mems[:3])
    return f"Session summary ({counts}) — {head}"


def main() -> None:
    # Read optional hook input (same tolerant pattern as session_start.py).
    try:
        raw = sys.stdin.read(4096)
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        sys.stderr.write(f"[skillgod/session_end] warning: unparseable input ({e})\n")
        data = {}

    project = (
        data.get("project")
        or os.environ.get("SKILLGOD_PROJECT")
        or _derive_project_id()
    )
    session_id = data.get("session_id", "")

    try:
        from memory import (get_recent, start_session, end_session,
                            save_with_git, get_git_context)

        # 1. Summarize from what post_tool.py captured — but ONLY real
        #    decision/pattern/error rows, NEVER prior 'context' rows. This matters
        #    for two edge cases found in a fresh-eyes audit:
        #      • An empty/pure-Q&A session (no decisions captured) must not write a
        #        noise "nothing happened" row that later sessions then re-summarize
        #        (self-referential accumulation). Filtering out 'context' means an
        #        empty session yields mems == [] and we skip the memory write below.
        #      • Session-summary 'context' rows from earlier sessions must not be
        #        mistaken for THIS session's work.
        #    (limit is raised to 12 pre-filter so we still surface up to a few real
        #    rows even when context rows are interleaved.)
        SUMMARY_KINDS = ("decision", "pattern", "error")
        # Scope to THIS session's rows when we have a session_id (post_tool now
        # stamps session_id on captured rows). Without the scope, an empty
        # session in a project with history re-summarized OLD decisions into a
        # fresh noise row on every IDE close. No session_id → fall back to
        # project-recent (pre-session_id rows / direct invocation).
        mems = [m for m in get_recent(project, limit=12,
                                      session_id=session_id or None)
                if m.get("kind") in SUMMARY_KINDS][:6]
        summary = _build_summary(mems)

        # Prefix the branch so the sessions-table summary (which has no branch
        # column) still carries branch context in plain text.
        git = get_git_context()
        if git:
            summary = f"[branch:{git['branch']}] {summary}"

        # 2. Finalize the sessions-table row. start_session is INSERT OR IGNORE,
        #    so this creates the row if the start hook used a different/absent id
        #    — never a silent no-op UPDATE. This ALWAYS runs (even for an empty
        #    session) so every session gets a closed, honest record — but it's a
        #    single row keyed by session_id, so it can't accumulate.
        if session_id:
            start_session(session_id, project)
            end_session(session_id, summary[:500])

        # 3. Persist a branch-tagged context memory row ONLY when there was real
        #    work to record. Skipping the write for an empty session is what keeps
        #    the memory table from filling with "no decisions captured" rows that
        #    would then pollute future recall and summaries.
        if mems:
            row_id = save_with_git(
                summary[:200], detail=summary[:500], kind="context",
                project=project, importance=0.6)
            sys.stderr.write(
                f"[skillgod/session_end] session summarized -> memory #{row_id} "
                f"(project={project}, session={session_id or 'n/a'})\n")
        else:
            sys.stderr.write(
                f"[skillgod/session_end] empty session (no decisions/patterns "
                f"captured) — sessions row closed, no memory row written "
                f"(project={project}, session={session_id or 'n/a'})\n")

    except Exception as e:
        # Fail safely but VISIBLY — never crash session teardown, but don't
        # swallow the reason either (runPython()/error-surfacing standard).
        sys.stderr.write(f"[skillgod/session_end] warning: {e}\n")


if __name__ == "__main__":
    main()
