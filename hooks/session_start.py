#!/usr/bin/env python3
"""
SkillGod SessionStart hook.

Fires when Claude Code opens a session.
Loads instincts + recent project memory and prints context to stdout
(Claude Code injects stdout into the session system prompt).

Wire in ~/.claude/settings.json:
  "hooks": {
    "SessionStart": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\path\\to\\hooks\\session_start.py"}]
    }]
  }

Input  (stdin): JSON with optional keys { "project": "..." }
Output (stdout): plain text context to inject
"""

import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE))


def main() -> None:
    # Read optional hook input
    try:
        raw = sys.stdin.read(4096)
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    project = (
        data.get("project")
        or os.environ.get("SKILLGOD_PROJECT")
        or Path.cwd().name
    )

    try:
        from runtime import SkillGodRuntime
        rt  = SkillGodRuntime(project=project)
        ctx = rt.on_session_start()
        if ctx:
            print(ctx)
    except Exception as e:
        # Never break the session — fail silently
        sys.stderr.write(f"[skillgod/session_start] warning: {e}\n")


if __name__ == "__main__":
    main()
