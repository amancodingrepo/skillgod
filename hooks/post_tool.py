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

from signals  import record_no_rework, record_rework, count_rework_signals
from variants import scan_meta_for_variants, add_to_promotion_queue, auto_enqueue_candidates

# Rework-intent phrases to detect in user follow-up
REWORK_WORDS = [
    "actually", "change that", "fix that", "not quite", "redo",
    "that is wrong", "no wait", "instead", "try again", "wrong",
    "that's not right", "incorrect", "nope", "revert",
]


def run(hook_input: dict) -> None:
    task        = hook_input.get("task", "")
    output      = hook_input.get("output", "")
    session_id  = hook_input.get("session_id", "unknown")
    active_skills = hook_input.get("active_skills", [])

    # Detect rework signals
    combined     = f"{task} {output}".lower()
    rework_count = count_rework_signals(combined)

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
    run(data)
