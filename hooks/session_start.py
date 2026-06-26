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

    # FIX 8 — license / expiry check at session start. Runs the (cached) online
    # check, downgrades to free the moment a license has expired, and warns the
    # user when they're inside the 7-day expiry window. Never blocks the
    # session: an expired user simply continues on the free vault.
    try:
        from license import is_pro_active, downgrade_to_free, get_machine_id
        license_status = is_pro_active(get_machine_id())
        if not license_status.get("active"):
            downgrade_to_free()
            print("[SkillGod] ⚠️  Pro license expired.")
            print("[SkillGod] Running on 30 free skills.")
            print("[SkillGod] Renew at: app.skillgod.dev/dashboard/billing")
        elif license_status.get("warning") == "expires_soon":
            days_left = license_status.get("days_left")
            print(f"[SkillGod] ⚠️  Pro license expires in {days_left} day(s).")
            print("[SkillGod] Renew at: app.skillgod.dev/dashboard/billing")
    except Exception as e:
        sys.stderr.write(f"[skillgod/session_start] license check warning: {e}\n")

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
