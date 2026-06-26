#!/usr/bin/env python3
"""
SkillGod PreToolUse hook.

Fires before every Claude tool call.
1. Runs security scan — blocks injection attempts (exit code 2 = block)
2. Scores and injects relevant skills
3. Attaches relevant project memory
Prints augmented context to stdout.

Wire in ~/.claude/settings.json:
  "hooks": {
    "PreToolUse": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\path\\to\\hooks\\pre_tool.py"}]
    }]
  }

Input  (stdin): JSON with keys { "tool_name": "...", "tool_input": {...},
                                  "session_id": "...", "project": "..." }
Output (stdout): context to inject (empty = nothing injected)
Exit code 2    : block the tool call (security threat detected)
"""

import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

# Module-level imports — fail hard. If the engine package itself is broken
# or missing, we do NOT want to silently fall through to exit(0) and let
# every tool call through unscanned. A broken install should be loud, not
# silently permissive. This intentionally lets an ImportError here crash
# the hook with a non-zero exit / traceback instead of being swallowed.
from runtime import get_runtime          # noqa: E402
from security import security_scan       # noqa: E402


def _extract_task(data: dict) -> str:
    """Pull the most useful task description from tool input."""
    tool_input = data.get("tool_input", {})
    # Prefer explicit task key
    for key in ("task", "prompt", "query", "description", "command"):
        if key in tool_input:
            return str(tool_input[key])[:500]
    # Fall back to first string value
    for v in tool_input.values():
        if isinstance(v, str) and len(v) > 10:
            return v[:500]
    return data.get("tool_name", "")


def main() -> None:
    try:
        raw = sys.stdin.read(8192)
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    task = _extract_task(data)
    if not task:
        sys.exit(0)

    project = (
        data.get("project")
        or os.environ.get("SKILLGOD_PROJECT")
        or Path.cwd().name
    )
    session_id = data.get("session_id", "")

    # --- Security gate: must fail CLOSED. Any exception here blocks the
    # tool call (exit 2) rather than letting it through unscanned. This is
    # the step the old code accidentally let fall through a catch-all
    # try/except that just printed a warning and exited 0.
    try:
        threats = security_scan(task)
    except Exception as e:
        sys.stderr.write(f"[skillgod] BLOCKED: security scan failed ({e}) — failing closed\n")
        sys.exit(2)

    if threats:
        sys.stderr.write("[skillgod] BLOCKED: injection attempt detected\n")
        sys.exit(2)

    # --- Skill injection / memory attach: may fail gracefully. A hiccup
    # building the augmented context (skills, memory) should not block the
    # already-security-cleared tool call — just inject nothing this time.
    try:
        rt = get_runtime(project=project)
        if session_id:
            rt.session_id = session_id

        result = rt.on_pre_tool(task)
        if result:
            print(result)

    except Exception as e:
        sys.stderr.write(f"[skillgod/pre_tool] warning: skill injection failed ({e})\n")


if __name__ == "__main__":
    main()
