#!/usr/bin/env python3
"""
SkillGod Vault Split
====================
Selects the highest-confidence scored skills across categories and copies them
to vault_free/ for the open-source free tier. Instinct inclusion is controlled
separately by FREE_TIER_INCLUDES_INSTINCTS (all-or-nothing) — see that constant.

Non-instinct scored-skill distribution (27):
  coding     8    (biggest category, most useful)
  design     4
  writing    3
  agents     3
  devops     3
  security   2
  research   2
  react      1
  api        1

Full vault (885+) stays in vault/ for paid Pro tier.
vault_free/ ships with the open-source binary.

Usage:
    python engine/vault_split.py              # run split
    python engine/vault_split.py --dry-run    # preview without copying
    python engine/vault_split.py --list       # list the 30 selected skills
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT       = Path(__file__).parent.parent
VAULT      = ROOT / "vault"
VAULT_FREE = ROOT / "vault_free"

# ─────────────────────────────────────────────────────────────────────────
# REVERSIBLE DECISION POINT (instincts in the free tier)
# ─────────────────────────────────────────────────────────────────────────
# Instincts are always-on rules injected on every prompt. Whether the FREE tier
# ships them (vs. gating them to Pro) is a business call, not an engineering one.
# Flip this ONE constant and re-run `python engine/vault_split.py` to switch:
#
#   FREE_TIER_INCLUDES_INSTINCTS = True   → ALL instinct files ship in vault_free/
#                                           (current default: instincts are a
#                                           universal baseline every user gets)
#   FREE_TIER_INCLUDES_INSTINCTS = False  → instincts are Pro-only; vault_free/
#                                           ships ZERO instincts (they stay in
#                                           vault/ for paid users)
#
# After flipping, run:  python engine/vault_split.py   (regenerates vault_free/)
# then:                 python engine/skills.py index   (rebuilds the index)
# No other code changes are needed either way.
FREE_TIER_INCLUDES_INSTINCTS: bool = True

# How many NON-INSTINCT scored skills to pick per category. Instinct inclusion
# is governed entirely by FREE_TIER_INCLUDES_INSTINCTS above (all-or-nothing),
# NOT by a quota, because instincts are unconditional rules, not scored picks.
QUOTA: dict[str, int] = {
    "coding":    8,
    "design":    4,
    "writing":   3,
    "agents":    3,
    "devops":    3,
    "security":  2,
    "research":  2,
    "react":     1,
    "api":       1,
}


def _parse_confidence(md_path: Path) -> float:
    """Extract confidence value from skill frontmatter."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("confidence:"):
                return float(line.partition(":")[2].strip())
            if line.startswith("---") and line != "---":
                break  # malformed
    except Exception:
        pass
    return 0.80


def _parse_name(md_path: Path) -> str:
    """Extract name from skill frontmatter."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                return line.partition(":")[2].strip()
    except Exception:
        pass
    return md_path.stem


def _parse_description(md_path: Path) -> str:
    """Extract description from skill frontmatter."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                return line.partition(":")[2].strip()[:80]
    except Exception:
        pass
    return ""


def select_free_skills() -> list[dict]:
    """
    For each category in QUOTA, pick the top N skills by confidence.
    Ties broken by alphabetical filename (deterministic).
    Returns list of dicts with keys: category, path, name, confidence, description.
    """
    selected = []

    # Instincts: all-or-nothing per FREE_TIER_INCLUDES_INSTINCTS (see the
    # decision point at the top of this file). When included, EVERY instinct
    # file ships free — they're a universal baseline, not a scored subset.
    if FREE_TIER_INCLUDES_INSTINCTS:
        inst_dir = VAULT / "instincts"
        if inst_dir.exists():
            for md in sorted(inst_dir.glob("*.md")):
                selected.append({
                    "category":    "instincts",
                    "path":        md,
                    "name":        _parse_name(md),
                    "confidence":  _parse_confidence(md),
                    "description": _parse_description(md),
                })

    for cat, quota in QUOTA.items():
        cat_dir = VAULT / cat
        if not cat_dir.exists():
            print(f"  [warn] vault/{cat}/ not found — skipping")
            continue

        candidates = []
        for md in sorted(cat_dir.glob("*.md")):
            conf = _parse_confidence(md)
            candidates.append({
                "category":    cat,
                "path":        md,
                "name":        _parse_name(md),
                "confidence":  conf,
                "description": _parse_description(md),
            })

        # Sort by confidence desc, then name asc for determinism
        candidates.sort(key=lambda x: (-x["confidence"], x["name"]))
        picked = candidates[:quota]

        if len(picked) < quota:
            print(f"  [warn] vault/{cat}/ has only {len(picked)} skills "
                  f"(wanted {quota})")

        selected.extend(picked)

    return selected


def run_split(dry_run: bool = False, list_only: bool = False) -> list[dict]:
    """
    Select and copy the 30 free-tier skills to vault_free/.
    """
    print("SkillGod Vault Split")
    print("=" * 50)

    selected = select_free_skills()

    print(f"\n30 free-tier skills selected:\n")
    print(f"  {'#':<3} {'Category':<12} {'Conf':>5}  {'Name':<40}  Description")
    print(f"  {'-'*3} {'-'*12} {'-'*5}  {'-'*40}  {'-'*40}")

    for i, sk in enumerate(selected, 1):
        print(
            f"  {i:<3} {sk['category']:<12} {sk['confidence']:>5.2f}  "
            f"{sk['name']:<40}  {sk['description'][:50]}"
        )

    print(f"\n  Total: {len(selected)} skills across {len(QUOTA)} categories")

    if list_only:
        return selected

    if dry_run:
        print("\n[dry-run] No files copied.")
        return selected

    # Clean and recreate vault_free/
    if VAULT_FREE.exists():
        shutil.rmtree(VAULT_FREE)
    VAULT_FREE.mkdir(parents=True)

    copied = 0
    for sk in selected:
        dest_dir = VAULT_FREE / sk["category"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sk["path"], dest_dir / sk["path"].name)
        copied += 1

    print(f"\n[done] Copied {copied} skills to vault_free/")
    print(f"  Free vault: {VAULT_FREE}")

    # Write a manifest
    manifest_lines = [
        "# SkillGod Free Vault — 30 Starter Skills",
        "# Generated by engine/vault_split.py",
        "# Full vault (885+ skills): sg sync --key YOUR_LICENSE_KEY",
        "",
    ]
    for sk in selected:
        manifest_lines.append(
            f"{sk['category']}/{sk['path'].name}  "
            f"# conf={sk['confidence']:.2f}  {sk['name']}"
        )
    (VAULT_FREE / "MANIFEST.txt").write_text(
        "\n".join(manifest_lines), encoding="utf-8"
    )
    print(f"  Manifest:   {VAULT_FREE / 'MANIFEST.txt'}")

    return selected


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SkillGod free vault selector")
    p.add_argument("--dry-run", action="store_true",
                   help="Preview selection without copying files")
    p.add_argument("--list",    action="store_true",
                   help="List selected skills and exit (no file operations)")
    args = p.parse_args()
    run_split(dry_run=args.dry_run, list_only=args.list)
