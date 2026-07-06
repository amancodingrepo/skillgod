#!/usr/bin/env python3
"""
SkillGod UserPromptSubmit hook.

Fires the moment the user submits a prompt — BEFORE Claude processes it.
Runs the security scan only (skill/memory injection happens at PreToolUse).
This is the "scans your prompt before the AI ever sees it" layer from the
CLAUDE.md spec; previously only SessionStart/PreToolUse/PostToolUse existed.

Wire in ~/.claude/settings.json:
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\path\\to\\hooks\\user_prompt_submit.py"}]
    }]
  }

Input  (stdin): JSON with key { "prompt": "..." }
Exit code 2   : block the prompt (security threat detected)
Exit code 0   : allow
"""

import json
import sys
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

# Fail hard on import — a broken engine must be loud, not silently permissive
# (same policy as pre_tool.py).
from security import security_scan  # noqa: E402


def main() -> None:
    # Read FULL stdin; fail CLOSED on unparseable non-empty payload
    # (same policy as pre_tool.py / BUG-021).
    raw = sys.stdin.read()
    if raw.strip():
        try:
            data = json.loads(raw)
        except Exception as e:
            sys.stderr.write(
                f"[skillgod] BLOCKED: unparseable hook input ({e}) — failing closed\n")
            sys.exit(2)
    else:
        data = {}

    prompt = str(data.get("prompt", ""))
    if not prompt:
        sys.exit(0)

    try:
        threats = security_scan(prompt)
    except Exception as e:
        sys.stderr.write(
            f"[skillgod] BLOCKED: security scan failed ({e}) — failing closed\n")
        sys.exit(2)

    if threats:
        names = ", ".join(t["pattern"] for t in threats[:3])
        sys.stderr.write(f"[skillgod] BLOCKED: injection attempt detected ({names})\n")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
