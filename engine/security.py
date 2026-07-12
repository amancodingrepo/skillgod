#!/usr/bin/env python3
"""
SkillGod Security Scanner
From everything-claude-code / AgentShield patterns.

Scans every input before processing.
Blocked → logged → returned with warning → never processed.
Never disable this. It protects the product and the user.
"""

import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# BUG-020 FIX — homoglyph fold. A minimal Cyrillic/Greek→Latin map covering the
# letters that spell the trigger words below, so `іgnore` / `іgnоre` (Cyrillic)
# normalises to `ignore` before matching. NFKC alone doesn't fold these.
_HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ԁ": "d", "ո": "n", "ⅼ": "l", "ɡ": "g", "ν": "v",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "τ": "t", "κ": "k", "ι": "i",
}

# Zero-width / bidi / joiner characters attackers insert between letters to
# defeat exact-match regex (ZWSP, ZWNJ, ZWJ, LRO/RLO/PDF, BOM, word-joiner).
_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C,
     0x202D, 0x202E, 0x2060, 0x2061, 0x2062, 0x2063, 0xFEFF], None
)


def _normalize_for_scan(text: str) -> str:
    """
    Canonicalise input before pattern matching so obfuscation can't trivially
    bypass the regex layer: strip zero-width / bidi characters, NFKC-normalise,
    fold common homoglyphs to Latin, lowercase. Word boundaries are preserved so
    the existing space-aware INJECTION_PATTERNS still match. The original text is
    what actually runs downstream; this surface only DECIDES whether to block.
    """
    if not text:
        return ""
    text = text.translate(_ZERO_WIDTH)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)
    return text.lower()


# BUG-020 FIX — compact signatures matched against an alphanumeric-only surface
# (all spaces/dots/hyphens removed), catching letter-spacing obfuscation like
# `i.g.n.o.r.e p-r-e-v-i-o-u-s` or `i g n o r e   a l l` that the space-aware
# regexes miss. Each is the trigger phrase with separators stripped.
_COMPACT_SIGNATURES = [
    ("ignoreprevious",       "ignore-previous"),
    ("ignoreall",            "ignore-all"),
    ("ignoreabove",          "ignore-previous"),
    ("disregardprevious",    "disregard-instructions"),
    ("disregardall",         "disregard-instructions"),
    ("disregardyour",        "disregard-instructions"),
    ("forgetyourinstruct",   "forget-instructions"),
    ("forgetinstruct",       "forget-instructions"),
    ("forgetyourrules",      "forget-instructions"),
    # Jailbreak family — INTENT-bearing compact forms only. Bare "jailbreak"
    # was removed: it matched "jailbreak detector" / "jailbreak attempt" in
    # ordinary security-dev prompts. These require an activation verb or an
    # AI-directed "jailbroken <ai|assistant|model>" (defeats letter-spacing
    # while still requiring the same intent as the spaced regexes above).
    ("enablejailbreak",      "jailbreak-activate"),
    ("enterjailbreak",       "jailbreak-activate"),
    ("activatejailbreak",    "jailbreak-activate"),
    ("turnonjailbreak",      "jailbreak-activate"),
    ("intojailbreak",        "jailbreak-activate"),
    ("jailbrokenai",         "jailbroken-ai"),
    ("jailbrokenassistant",  "jailbroken-ai"),
    ("jailbrokenmodel",      "jailbroken-ai"),
    ("jailbrokenchatbot",    "jailbroken-ai"),
    ("dan mode".replace(" ", ""), "dan-mode"),
    # Privileged-mode jailbreaks require the activation verb (bare
    # "developermode" / "sudomode" / "godmode" were ordinary-feature false
    # positives — e.g. "developer mode", a game "god mode", "sudo mode").
    ("enabledevelopermode",  "privileged-mode-jailbreak"),
    ("enablegodmode",        "privileged-mode-jailbreak"),
    ("enablesudomode",       "privileged-mode-jailbreak"),
    ("activategodmode",      "privileged-mode-jailbreak"),
    # BUG-037 FIX — bare "systemprompt" blocked every legitimate mention of
    # "system prompt" (e.g. "design a system prompt template for my chatbot").
    # Only flag when a leak verb or possessive is attached, mirroring the
    # spaced prompt-leak regex above.
    ("yoursystemprompt",     "prompt-leak"),
    ("revealsystemprompt",   "prompt-leak"),
    ("showsystemprompt",     "prompt-leak"),
    ("printsystemprompt",    "prompt-leak"),
    ("outputsystemprompt",   "prompt-leak"),
    ("repeatsystemprompt",   "prompt-leak"),
    ("dumpsystemprompt",     "prompt-leak"),
    ("leaksystemprompt",     "prompt-leak"),
    # bare "newpersona" removed — it flagged "add a new persona field to the
    # user model". The spaced regex still catches "new persona:" / "adopt a
    # new persona" (assignment/command intent).
    ("actasunrestricted",    "act-as-jailbreak"),
    ("actasjailbroken",      "act-as-jailbreak"),
    ("bypasssafety",         "safety-bypass"),
    ("overridesafety",       "safety-override"),
    ("disablesafety",        "disable-safety"),
]

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

    # Role / persona hijacking.
    # These require INJECTION INTENT — an imperative directed at the assistant
    # to adopt a new identity or escape its instructions — not the mere mention
    # of a concept word. "discuss the jailbreak detector", "test a jailbreak
    # attempt", "detect jailbroken devices", "add a new persona field",
    # "enable debug mode" are all legitimate developer prompts and must NOT trip.
    # "you are now <identity>" — a persona reassignment. Exclude benign
    # capability continuations ("you are now able/ready/logged in/on the …")
    # so ordinary status sentences don't trip it; identity words still match.
    (r"you\s+are\s+now\s+"
     r"(?!(?:a\s+(?:developer|assistant|coder|engineer)|able|allowed|ready|free|"
     r"logged|signed|connected|online|offline|in\b|on\b|off\b|viewing|seeing|"
     r"looking|running|using|able\s+to)\b)\S+",
     "persona-hijack"),
    (r"act\s+as\s+(?:an?\s+)?(unrestricted|jailbroken|dan|unc[e]nsored|evil|harmful)",
     "act-as-jailbreak"),
    # "new persona" only as an assignment/command, not "a new persona field".
    (r"(?:(?:adopt|assume|become|take\s+on|switch\s+to)\s+(?:a\s+)?new\s+persona"
     r"|new\s+persona\s*[:=])",
     "new-persona"),
    (r"\bdan\s+mode\b",                               "dan-mode"),
    # Privileged-mode jailbreaks require the ACTIVATION verb — bare "debug mode"
    # / "developer mode" / "admin mode" are ordinary app features.
    (r"(?:enable|enter|activate|turn\s+on|switch\s+to)\s+(?:the\s+)?(developer|god|sudo|kernel)\s+mode\b",
     "privileged-mode-jailbreak"),
    # "jailbreak" only when it's an imperative to jailbreak (activation verb) or
    # a claim that the ASSISTANT is jailbroken — never a bare noun mention.
    (r"(?:enable|enter|activate|turn\s+on|initiate|switch\s+to|into)\s+(?:the\s+)?jailbreak(?:\s+mode)?\b",
     "jailbreak-activate"),
    (r"you(?:'?re|\s+are)\s+(?:now\s+)?jailbroken\b",
     "jailbroken-you"),
    (r"\bjailbroken\s+(?:ai|assistant|model|chatbot|llm|bot)\b",
     "jailbroken-ai"),
    # AI-directed "unrestricted/uncensored AI", not "unrestricted version/mode".
    (r"(unrestricted|uncensored|unfiltered)\s+(ai|assistant|model|chatbot|llm|bot)",
     "unrestricted-ai"),

    # Token injection (LLM-level attacks)
    (r"<\|im_start\|>",   "token-injection-start"),
    (r"<\|im_end\|>",     "token-injection-end"),
    (r"<\|system\|>",     "token-injection-system"),
    (r"\[INST\]",         "llama-instruction-injection"),
    (r"<s>",              "token-injection-bos"),

    # Prompt leaking
    (r"(reveal|show|print|output|repeat|tell me|give me|dump|leak)\s+(me\s+)?(your\s+)?(system\s+prompt|instructions?|context|initial prompt)",
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

    # Pretend / roleplay attacks
    (r"pretend\s+(?:you\s+)?(?:have\s+no|don.t\s+have|without)\s+(?:any\s+)?(?:rules?|restrictions?|guidelines?|limits?|constraints?)",
     "pretend-no-rules"),
    (r"pretend\s+(?:to\s+be|you.?re)\s+(?:an?\s+)?(?:unrestricted|uncensored|unfiltered|jailbroken)",
     "pretend-jailbreak"),
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

    # BUG-020 FIX — match against a normalised surface (zero-width/bidi stripped,
    # NFKC, homoglyphs folded) so obfuscated triggers can't slip past the regex.
    scan_surface = _normalize_for_scan(text)

    threats = []
    seen = set()
    for regex, name in _COMPILED:
        m = regex.search(scan_surface)
        if m:
            threats.append({
                "pattern":  name,
                "match":    m.group(0)[:120],
                "severity": "high",
                "offset":   m.start(),
            })
            seen.add(name)

    # Compact pass: strip ALL non-alphanumerics and look for concatenated
    # signatures (defeats letter-spacing: "i.g.n.o.r.e p-r-e-v-i-o-u-s").
    compact = re.sub(r"[^a-z0-9]+", "", scan_surface)
    for sig, name in _COMPACT_SIGNATURES:
        if sig in compact and name not in seen:
            threats.append({
                "pattern":  name,
                "match":    sig,
                "severity": "high",
                "offset":   compact.find(sig),
            })
            seen.add(name)

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
    except Exception as e:
        # Logging failed — do not swallow silently in a security context.
        print(f"[SkillGod] security logger error: {e}", file=sys.stderr)


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
