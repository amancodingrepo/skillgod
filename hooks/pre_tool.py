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


def _hooklog(_event, _msg=""):
    """Task 7.3 — unconditional hook logging. Appends one line to
    <sgRoot>/logs/hooks.log (== ~/.skillgod/logs on a real install); rotates at
    1 MB. Self-contained (no engine import) so it works even if the engine is
    broken. Never raises."""
    try:
        import os, time
        _d = os.path.join(str(Path(__file__).resolve().parent.parent), "logs")
        os.makedirs(_d, exist_ok=True)
        _p = os.path.join(_d, "hooks.log")
        try:
            if os.path.getsize(_p) > 1_000_000:
                os.replace(_p, _p + ".1")
        except OSError:
            pass
        with open(_p, "a", encoding="utf-8", errors="replace") as _f:
            _f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + _event + " " + _msg + chr(10))
    except Exception:
        pass

# Windows: hook stdout/stderr are pipes, so Python encodes with the legacy
# ANSI codepage (cp1252) and printing a skill payload containing ✓/→/… dies
# with UnicodeEncodeError — injection silently delivers nothing. The host
# reads hook output as UTF-8, so emit UTF-8 explicitly.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

# Module-level imports — fail hard. If the engine package itself is broken
# or missing, we do NOT want to silently fall through to exit(0) and let
# every tool call through unscanned. A broken install should be loud, not
# silently permissive. This intentionally lets an ImportError here crash
# the hook with a non-zero exit / traceback instead of being swallowed.
from runtime import get_runtime          # noqa: E402
from security import security_scan       # noqa: E402


# Strict mode: hard-block the tool call on a detected injection pattern.
# Default (unset / "0"): warn-and-allow. Mirrors hooks/user_prompt_submit.py so
# the two security hooks behave identically. The detector matches patterns that
# also occur in legitimate developer work (discussing / testing / reviewing /
# editing security code), so a hard block by default interrupts real work more
# often than it stops a real attack. Genuine ENGINE failures (broken import,
# scan crash, unparseable input) still fail CLOSED regardless of mode.
STRICT = os.environ.get("SKILLGOD_STRICT_SECURITY", "0").strip().lower() in (
    "1", "true", "yes", "on"
)


def _derive_project_id() -> str:
    """Collision-resistant project id (BUG-016). Falls back to the folder name
    if the memory helper can't be imported for any reason."""
    try:
        from memory import derive_project_id
        return derive_project_id()
    except Exception:
        return Path.cwd().name


def _extract_task(data: dict) -> str:
    """Pull the most useful task description from tool input (for skill scoring)."""
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


def _collect_scan_text(obj, _depth: int = 0) -> str:
    """
    BUG-021 FIX — the security scan must see EVERY string in the payload, not
    just the one field _extract_task() picks. Recursively concatenate all string
    values (bounded depth) so an injection hidden in a non-preferred field is
    still scanned.
    """
    if _depth > 6:
        return ""
    parts = []
    if isinstance(obj, str):
        parts.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            parts.append(_collect_scan_text(v, _depth + 1))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            parts.append(_collect_scan_text(v, _depth + 1))
    return "\n".join(p for p in parts if p)


def main() -> None:
    _hooklog("pre_tool", "invoked")
    # BUG-021 FIX — read the FULL stdin (was capped at 8192 bytes, so any payload
    # larger than 8KB truncated → JSON parse failed → the old code fell through
    # to exit(0), letting the tool call through completely unscanned). Read it
    # all, and if a non-empty payload fails to parse, fail CLOSED (exit 2).
    raw = sys.stdin.read()
    if raw.strip():
        try:
            data = json.loads(raw)
        except Exception as e:
            sys.stderr.write(f"[skillgod] BLOCKED: unparseable hook input ({e}) — failing closed\n")
            sys.exit(2)
    else:
        data = {}

    task = _extract_task(data)

    project = (
        data.get("project")
        or os.environ.get("SKILLGOD_PROJECT")
        or _derive_project_id()   # BUG-016 FIX — git-remote/path, not bare folder name
    )
    session_id = data.get("session_id", "")

    # Self-healing watcher startup — this is the PRIMARY self-heal trigger:
    # PreToolUse fires more often than any other hook, so a watcher killed by
    # a reboot gets repaired here first in practice. ~0.1ms when already
    # running (measured) — fires unconditionally, even for a request the
    # security gate below ends up blocking, since that's still real SkillGod
    # usage. See engine/fs_watcher.py's ensure_watcher_running() docstring.
    try:
        from fs_watcher import ensure_watcher_running
        ensure_watcher_running(str(Path.cwd()))
    except Exception:
        pass

    # --- Security gate: must fail CLOSED. Scan the ENTIRE payload (every string
    # field), not just the extracted task, and block on any exception. This is
    # the step the old code accidentally let fall through a catch-all
    # try/except that just printed a warning and exited 0.
    try:
        scan_text = _collect_scan_text(data.get("tool_input", data)) or task
        threats = security_scan(scan_text)
    except Exception as e:
        sys.stderr.write(f"[skillgod] BLOCKED: security scan failed ({e}) — failing closed\n")
        sys.exit(2)

    if threats:
        names = ", ".join(t["pattern"] for t in threats[:3])
        if STRICT:
            sys.stderr.write(
                f"[skillgod] BLOCKED: injection attempt detected ({names})\n")
            sys.exit(2)
        # Default: warn, but let the tool call through. The user stays in
        # control; a false positive on legitimate work no longer halts it.
        sys.stderr.write(
            f"[skillgod] warning: possible injection pattern ({names}) — "
            f"allowing (set SKILLGOD_STRICT_SECURITY=1 to block)\n")

    # Nothing to score/inject if there's no task text — but only AFTER the
    # security gate above has run on the full payload.
    if not task:
        sys.exit(0)

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
    try:
        main()
    except Exception:
        import traceback
        _hooklog("pre_tool", "CRASHED" + chr(10) + traceback.format_exc())
        raise
