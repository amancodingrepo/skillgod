#!/usr/bin/env python3
"""
SkillGod UserPromptSubmit hook.

Fires the moment the user submits a prompt — BEFORE Claude processes it.
Runs the security scan only (skill/memory injection happens at PreToolUse).
This is the "scans your prompt before the AI ever sees it" layer from the
CLAUDE.md spec.

DEFAULT BEHAVIOR: warn-and-allow.
  The injection scanner matches on patterns that also appear in legitimate
  developer prompts (discussing, testing, reviewing, or coding security
  features). A false-positive HARD BLOCK interrupts real work and can make
  a user lose a carefully-written prompt — a worse outcome than the rare
  real attack it guards against. So by default this hook WARNS on a detected
  pattern and lets the prompt through. The user stays in control.

  Set SKILLGOD_STRICT_SECURITY=1 to restore hard-blocking for detected
  injection patterns (for users who want the prompt actually stopped).

  Genuine ENGINE FAILURES (broken import, scanner crash, unparseable input)
  still fail CLOSED regardless of mode — those are real errors, not
  false-positive-prone detections, and a broken engine must be loud.

Wire in ~/.claude/settings.json:
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{"type": "command",
                 "command": "python C:\\path\\to\\hooks\\user_prompt_submit.py"}]
    }]
  }

Input  (stdin): JSON with key { "prompt": "..." }
Exit code 2   : block the prompt (engine failure always; detected injection
                only when SKILLGOD_STRICT_SECURITY=1)
Exit code 0   : allow (default for detected injection — warning is emitted)
"""

import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

# Windows: hook stderr is a pipe (legacy cp1252 default) — emit UTF-8 so a
# message containing non-ANSI characters can't itself crash the hook.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

# Fail hard on import — a broken engine must be loud, not silently permissive
# (same policy as pre_tool.py). This is an ENGINE failure, not a detection,
# so it fails closed even in the default warn mode.
from security import security_scan  # noqa: E402


# Strict mode: hard-block on a detected injection pattern.
# Default (unset / "0"): warn-and-allow on detection.
STRICT = os.environ.get("SKILLGOD_STRICT_SECURITY", "0").strip().lower() in (
    "1", "true", "yes", "on"
)


def main() -> None:
    # Read FULL stdin; fail CLOSED on unparseable non-empty payload
    # (this is an input/engine error, not a false-positive-prone detection).
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

    # A scanner CRASH is an engine failure — fail closed regardless of mode.
    try:
        threats = security_scan(prompt)
    except Exception as e:
        sys.stderr.write(
            f"[skillgod] BLOCKED: security scan failed ({e}) — failing closed\n")
        sys.exit(2)

    # A detected injection PATTERN is the false-positive-prone case.
    if threats:
        names = ", ".join(t["pattern"] for t in threats[:3])
        if STRICT:
            sys.stderr.write(
                f"[skillgod] BLOCKED: injection attempt detected ({names})\n")
            sys.exit(2)
        # Default: warn, but let the prompt through. User keeps control.
        sys.stderr.write(
            f"[skillgod] warning: possible injection pattern ({names}) — "
            f"allowing (set SKILLGOD_STRICT_SECURITY=1 to block)\n")
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()