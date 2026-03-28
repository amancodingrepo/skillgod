#!/usr/bin/env python3
"""
SkillGod Security Scanner
From everything-claude-code / AgentShield patterns.

Scans every input before processing.
Blocked → logged → returned with warning → never processed.
Never disable this. It protects the product and the user.
"""

import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Injection patterns (from CLAUDE.md spec + AgentShield)
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    # Classic ignore-previous attacks
    (r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|rules?|guidelines?|constraints?)",
     "ignore-previous"),
    (r"ignore\s+all\s+(?:instructions?|rules?|guidelines?|constraints?)",
     "ignore-all"),
    (r"disregard\s+(?:all\s+)?(?:your\s+)?(?:previous\s+|above\s+)?(?:safety\s+)?(?:instructions?|rules?|training|guidelines?|constraints?)",
     "disregard-instructions"),
    (r"forget\s+(your\s+)?(instructions?|rules?|training|guidelines?|constraints?)",
     "forget-instructions"),

    # Role / persona hijacking
    (r"you\s+are\s+now\s+(?!a\s+(?:developer|assistant|coder|engineer))\S+",
     "persona-hijack"),
    (r"act\s+as\s+(unrestricted|jailbroken|dan|unc[e]nsored|evil|harmful)",
     "act-as-jailbreak"),
    (r"new\s+persona",                                "new-persona"),
    (r"\bdan\s+mode\b",                               "dan-mode"),
    (r"jailbreak",                                    "jailbreak"),
    (r"(unrestricted|uncensored)\s+(ai|mode|version)", "unrestricted-ai"),

    # Token injection (LLM-level attacks)
    (r"<\|im_start\|>",   "token-injection-start"),
    (r"<\|im_end\|>",     "token-injection-end"),
    (r"<\|system\|>",     "token-injection-system"),
    (r"\[INST\]",         "llama-instruction-injection"),
    (r"<s>",              "token-injection-bos"),

    # Prompt leaking
    (r"(reveal|show|print|output|repeat|tell me)\s+(your\s+)?(system\s+prompt|instructions?|context|initial prompt)",
     "prompt-leak"),
    (r"what\s+(are\s+)?your\s+(instructions?|rules?|system\s+prompt)",
     "prompt-leak-query"),

    # Override attempts
    (r"override\s+(all\s+)?(safety|security|filter|restriction|guideline)",
     "safety-override"),
    (r"bypass\s+(all\s+)?(safety|security|filter|restriction|guideline)",
     "safety-bypass"),
    (r"(disable|turn\s+off)\s+(safety|filter|restriction|guardrail)",
     "disable-safety"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE | re.DOTALL), name)
             for p, name in INJECTION_PATTERNS]


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def security_scan(text: str) -> list[dict]:
    """
    Scan text for prompt injection patterns.
    Returns list of threat dicts (empty = clean).

    Each threat: {"pattern": str, "match": str, "severity": str}
    """
    if not text or not isinstance(text, str):
        return []

    threats = []
    for regex, name in _COMPILED:
        m = regex.search(text)
        if m:
            threats.append({
                "pattern":  name,
                "match":    m.group(0)[:120],
                "severity": "high",
                "offset":   m.start(),
            })

    if threats:
        _log_threats(text[:200], threats)

    return threats


def is_safe(text: str) -> bool:
    """Return True if text passes security scan."""
    return len(security_scan(text)) == 0


def scan_report(text: str) -> str:
    """Human-readable security scan result."""
    threats = security_scan(text)
    if not threats:
        return "clean"
    lines = [f"BLOCKED — {len(threats)} injection pattern(s) detected:"]
    for t in threats:
        lines.append(f"  [{t['severity'].upper()}] {t['pattern']}: \"{t['match']}\"")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = Path(__file__).parent.parent / "db" / "security.log"


def _log_threats(text_snippet: str, threats: list[dict]) -> None:
    """Append blocked attempt to security log."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().isoformat()} "
                f"| {len(threats)} threat(s) "
                f"| patterns: {[t['pattern'] for t in threats]} "
                f"| snippet: {repr(text_snippet[:100])}\n"
            )
    except Exception:
        pass  # never let logging break the security check


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not text:
        # Interactive mode
        print("SkillGod Security Scanner — enter text to scan (Ctrl-C to quit):")
        while True:
            try:
                line = input("> ")
                print(scan_report(line))
            except (KeyboardInterrupt, EOFError):
                break
    else:
        print(scan_report(text))
