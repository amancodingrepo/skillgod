#!/usr/bin/env python3
"""Task 1c — regression tests for the decision-importance classifier.

These use the EXACT strings from the live incident where explicit
"decision: ..." commits were dropped and a routine docs commit was captured at
0.9. Run: python -m pytest engine/tests/test_decision_classifier.py -q
or standalone: python engine/tests/test_decision_classifier.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from memory import score_importance  # noqa: E402


# --- MUST score >= 0.8 (explicit decisions — the incident's dropped commits) ---
HIGH = [
    "decision: use PostgreSQL for session storage instead of Redis",
    "decision: switching session storage to PostgreSQL",
    "decision: adopt PostgreSQL for session storage",
    "chose Razorpay over LemonSqueezy for INR support",
    "switching from REST to gRPC for internal services",
    "we decided to keep SQLite for local storage",
    "adopting trunk-based development instead of gitflow",
]

# --- MUST score <= 0.4 (noise — the incident's falsely-captured docs commit) ---
LOW = [
    "docs: add hooks/project-id fix report and session handoff document",
    "chore: bump dependencies",
    "wip",
    "fix typo in README",
    "Merge branch 'main' into feature/x",
    "formatting",
]


def test_high_importance_decisions():
    for msg in HIGH:
        imp, markers = score_importance(msg)
        assert imp >= 0.8, f"{msg!r} scored {imp} (<0.8), markers={markers}"


def test_low_importance_noise():
    for msg in LOW:
        imp, markers = score_importance(msg)
        assert imp <= 0.4, f"{msg!r} scored {imp} (>0.4), markers={markers}"


def test_docs_with_slam_dunk_in_subject():
    # docs: prefix BUT a slam-dunk marker in the subject → not capped, >= 0.7
    imp, _ = score_importance("docs: decision record — why we chose PostgreSQL")
    assert imp >= 0.7, f"docs+slam-dunk scored {imp} (<0.7)"


def test_ordinary_commit_midrange():
    imp, _ = score_importance("Fixed the bug where sessions dropped")
    assert 0.25 <= imp <= 0.55, f"ordinary commit scored {imp} (want ~0.3-0.5)"


def test_empty_message_no_crash():
    imp, markers = score_importance("")
    assert imp <= 0.1 and markers == ["empty"], f"empty scored {imp}, {markers}"


def test_non_ascii_no_crash():
    # French/accented + CJK must not raise (Task 5 encoding safety at classify time)
    imp, _ = score_importance("décision: utiliser PostgreSQL")
    assert 0.0 <= imp <= 1.0
    imp2, _ = score_importance("commit — em-dash, naïve, 日本語")
    assert 0.0 <= imp2 <= 1.0


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
    # detailed score dump for visibility
    print("\n  --- scores ---")
    for msg in HIGH + LOW:
        imp, mk = score_importance(msg)
        print(f"    {imp:.2f}  {msg[:60]!r}  {mk}")
    print(f"\n  {passed}/{len(fns)} tests passed")
    return passed == len(fns)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
