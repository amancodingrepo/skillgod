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


def _check_db_integrity() -> None:
    """
    BUG-018 FIX — run `PRAGMA integrity_check` on the shared local SQLite DB
    BEFORE anything else touches it. The same file backs the license kv/cache,
    the skill index, memory, and coupons; if it's corrupted (disk full / forced
    shutdown mid-write) every subsequent read silently fails and a paying Pro
    user gets downgraded to free with no explanation. On corruption we back the
    file up, rebuild a fresh DB (skill index + empty tables), and tell the user
    exactly what happened and how to restore Pro — never fail closed silently.
    """
    import sqlite3
    from datetime import datetime

    try:
        from license import get_local_db_path
        db_path = Path(get_local_db_path())
    except Exception:
        db_path = Path(__file__).parent.parent / "db" / "skillgod.db"

    if not db_path.exists():
        return  # fresh install — nothing to check

    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result and str(result[0]).lower() == "ok":
            return  # healthy
    except Exception:
        result = ("corrupt",)  # couldn't even open it — treat as corrupted

    # --- Corruption detected: back up + rebuild -----------------------------
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_suffix(db_path.suffix + f".corrupted-{ts}")
    try:
        db_path.rename(backup)
    except Exception as e:
        sys.stderr.write(f"[SkillGod] could not back up corrupted DB: {e}\n")
        # As a last resort, try to remove it so a clean one can be built.
        try:
            db_path.unlink()
        except Exception:
            return

    # Rebuild a fresh DB: skill index + empty memory/kv tables.
    try:
        from skills import rebuild_index
        rebuild_index()
    except Exception as e:
        sys.stderr.write(f"[SkillGod] skill index rebuild after reset failed: {e}\n")
    try:
        from memory import get_db as _mem_db
        _mem_db().close()   # recreates memory/sessions tables
    except Exception:
        pass
    try:
        from license import set_kv
        set_kv("license_status", "free")  # recreates the kv table
    except Exception:
        pass

    print("[SkillGod] Local database was corrupted and has been reset.")
    print("[SkillGod] Your skill index has been rebuilt. Memory history from "
          "before this reset could not be recovered —")
    print(f"[SkillGod] a backup was saved at: {backup}")
    print("[SkillGod] If you had an active Pro license, run "
          "'sg sync --key YOUR_KEY' again to restore it.")


def main() -> None:
    # BUG-018 — integrity-check/repair the shared SQLite DB before any read.
    try:
        _check_db_integrity()
    except Exception as e:
        sys.stderr.write(f"[skillgod/session_start] db integrity check warning: {e}\n")

    # Read optional hook input
    try:
        raw = sys.stdin.read(4096)
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    # BUG-016 FIX — collision-resistant project id (git remote / abspath), not
    # the bare folder name that let unrelated "backend" folders share memory.
    def _derive_project_id() -> str:
        try:
            from memory import derive_project_id
            return derive_project_id()
        except Exception:
            return Path.cwd().name

    project = (
        data.get("project")
        or os.environ.get("SKILLGOD_PROJECT")
        or _derive_project_id()
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
