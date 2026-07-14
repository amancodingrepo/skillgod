#!/usr/bin/env python3
"""
SkillGod PostToolUse hook.
Runs after every Claude response.

Wire this in ~/.claude/settings.json:
  "hooks": {
    "PostToolUse": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\...\\hooks\\post_tool.py"}]
    }]
  }

Input (stdin): JSON with keys task, output, active_skills, session_id
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))


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

# Windows: hook stdout/stderr are pipes (legacy cp1252 default) — emit UTF-8
# so captured output containing non-ANSI characters can't crash the hook.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

from signals  import record_no_rework, record_rework, count_rework_signals
from variants import scan_meta_for_variants, add_to_promotion_queue, auto_enqueue_candidates

# Rework-intent phrases to detect in user follow-up
REWORK_WORDS = [
    "actually", "change that", "fix that", "not quite", "redo",
    "that is wrong", "no wait", "instead", "try again", "wrong",
    "that's not right", "incorrect", "nope", "revert",
]


def run(hook_input: dict) -> None:
    _hooklog("post_tool", "invoked")
    task        = hook_input.get("task", "")
    output      = hook_input.get("output", "")
    session_id  = hook_input.get("session_id", "unknown")
    active_skills = hook_input.get("active_skills", [])

    # Capture decision→memory from the AI's output, keyed to THIS project's
    # git-aware id (the SAME derive_project_id() the MCP server and other hooks
    # use), so memory created here is visible to every tool in the same project.
    # Previously nothing wired this: runtime.on_post_tool() held the logic but no
    # hook ever called it, so output-driven memory capture was dead. Guarded so a
    # capture hiccup never breaks the post-response hook.
    try:
        from memory import derive_project_id
        from runtime import capture_memory
        project = hook_input.get("project") or derive_project_id()
        if task or output:
            # session_id threads through to the memory row so session_end.py
            # can summarize THIS session's rows only.
            capture_memory(task, output, project, session_id=session_id)
    except Exception as e:
        sys.stderr.write(f"[skillgod/post_tool] memory capture warning: {e}\n")

    # Detect rework signals — BUG-039 FIX: scan only the USER's task text.
    # The AI's own output routinely says "instead"/"actually", which counted
    # as rework and unfairly dinged the active skills' quality scores.
    rework_count = count_rework_signals(task.lower())

    # Record signal for each active skill
    for sk in active_skills:
        skill_id   = sk.get("id") or sk.get("name", "unknown")
        skill_name = sk.get("name", skill_id)

        if rework_count == 0:
            record_no_rework(skill_id, skill_name, session_id)
        else:
            record_rework(skill_id, skill_name, rework_count, session_id)

    # Background: auto-enqueue any newly eligible meta skills
    # Only run every ~10 calls to avoid overhead (check via session_id hash)
    if hash(session_id) % 10 == 0:
        try:
            added = auto_enqueue_candidates()
            if added:
                sys.stderr.write(
                    f"[SkillGod] {added} skill(s) added to promotion queue\n"
                )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Called directly without stdin — demo mode
        data = {
            "task":          "debug this python traceback",
            "output":        "Here are the steps to fix it...",
            "session_id":    "demo-session",
            "active_skills": [
                {"id": "python-debug", "name": "Python Debugging"},
            ],
        }
    try:
        run(data)
    except Exception:
        import traceback
        _hooklog("post_tool", "CRASHED" + chr(10) + traceback.format_exc())
        raise
