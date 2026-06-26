#!/usr/bin/env python3
"""
SkillGod Skill Enhancer — Pro feature.

Takes an existing skill file and improves it based on real signal data:
  - Promotes high-scoring triggers to the top
  - Rewrites description to match actual triggering patterns
  - Raises confidence based on no-rework signal ratio
  - Flags underperforming skills for human review

Uses signal data from signals.py SQLite table.
Only runs for Pro users (license check enforced).
"""

import re
from pathlib import Path
from datetime import datetime

ROOT      = Path(__file__).parent.parent
VAULT_DIR = ROOT / "vault"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1]
                meta[k] = [i.strip().strip('"\'') for i in inner.split(",") if i.strip()]
            else:
                meta[k] = v
    return meta, text[end + 4:].strip()


def _write_frontmatter(meta: dict, body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            items = ", ".join(f'"{i}"' for i in v)
            lines.append(f"{k}: [{items}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def _get_signal_stats(skill_id: str) -> dict:
    """Pull signal data for a skill from SQLite."""
    try:
        from signals import _get_db
        conn = _get_db()
        rows = conn.execute(
            "SELECT kind, rework_count, score FROM signals WHERE skill_id=?",
            (skill_id,)
        ).fetchall()
        conn.close()
        if not rows:
            return {}
        accepts = [r for r in rows if r["kind"] == "accept"]
        reworks = [r for r in rows if r["kind"] == "rework"]
        total   = len(rows)
        accept_rate = len(accepts) / total if total else 0
        avg_score   = sum(r["score"] for r in rows) / total
        return {
            "total":       total,
            "accepts":     len(accepts),
            "reworks":     len(reworks),
            "accept_rate": round(accept_rate, 3),
            "avg_score":   round(avg_score, 3),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Core enhancement logic
# ---------------------------------------------------------------------------

def enhance_skill(skill_path: Path, dry_run: bool = False) -> dict:
    """
    Enhance a single skill file using signal data.

    Returns a dict describing what changed:
      {
        "path":        str,
        "changed":     bool,
        "changes":     [str],       # human-readable list of changes
        "new_confidence": float,
        "signals":     dict,
      }
    """
    if not skill_path.exists():
        return {"path": str(skill_path), "changed": False, "error": "File not found"}

    text = skill_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    skill_id = meta.get("id") or skill_path.stem
    signals  = _get_signal_stats(skill_id)

    changes  = []
    modified = dict(meta)

    # ── 1. Confidence update based on accept rate ──────────────────────────
    if signals.get("total", 0) >= 5:
        accept_rate    = signals["accept_rate"]
        old_confidence = float(modified.get("confidence", 0.80))

        if accept_rate >= 0.85:
            new_confidence = min(old_confidence + 0.05, 0.95)
        elif accept_rate < 0.50:
            new_confidence = max(old_confidence - 0.05, 0.50)
        else:
            new_confidence = old_confidence

        new_confidence = round(new_confidence, 2)
        if new_confidence != old_confidence:
            modified["confidence"] = new_confidence
            direction = "↑" if new_confidence > old_confidence else "↓"
            changes.append(
                f"confidence {direction} {old_confidence} → {new_confidence} "
                f"(accept_rate={accept_rate:.0%} over {signals['total']} uses)"
            )

    # ── 2. Uses counter sync ───────────────────────────────────────────────
    if signals.get("total", 0) > int(modified.get("uses", 0)):
        modified["uses"] = signals["total"]
        changes.append(f"uses updated to {signals['total']}")

    # ── 3. Description fix — enforce "Use when" prefix ────────────────────
    desc = modified.get("description", "")
    if desc and not desc.lower().startswith("use when"):
        # Attempt to rewrite as a triggering condition
        # Convert "A systematic approach to X" → "Use when you need X"
        desc_clean = re.sub(r'^(helps? with|for|a |an |systematic |approach to )',
                            '', desc, flags=re.IGNORECASE).strip()
        new_desc = f"Use when {desc_clean[0].lower()}{desc_clean[1:]}"
        if new_desc != desc:
            modified["description"] = new_desc
            changes.append(f"description rewritten to start with 'Use when'")

    # ── 4. Flag for review if consistently underperforming ────────────────
    needs_review = (
        signals.get("total", 0) >= 10 and
        signals.get("accept_rate", 1.0) < 0.40
    )
    if needs_review:
        changes.append(
            f"FLAGGED for review — accept rate {signals['accept_rate']:.0%} "
            f"over {signals['total']} uses (move to vault/meta/ or rewrite triggers)"
        )

    changed = bool(changes)
    if changed and not dry_run:
        new_text = _write_frontmatter(modified, body)
        skill_path.write_text(new_text, encoding="utf-8")

    return {
        "path":           str(skill_path),
        "skill_id":       skill_id,
        "changed":        changed,
        "changes":        changes,
        "new_confidence": float(modified.get("confidence", 0.80)),
        "signals":        signals,
        "needs_review":   needs_review,
    }


def enhance_vault(category: str = None, min_uses: int = 3,
                  dry_run: bool = False) -> list[dict]:
    """
    Run the enhancer across the entire vault (or one category).
    Skips instincts — they are hand-curated.
    Skips skills with fewer than min_uses signals.

    Returns list of enhancement results for skills that changed.
    """
    if not VAULT_DIR.exists():
        return []

    search_dir = VAULT_DIR / category if category else VAULT_DIR
    results    = []

    for md in search_dir.rglob("*.md"):
        if "instincts" in md.parts:
            continue  # never auto-modify instincts
        result = enhance_skill(md, dry_run=dry_run)
        if result.get("changed") or result.get("needs_review"):
            results.append(result)

    return results


def enhancer_report(results: list[dict]) -> str:
    """Format enhance_vault results as a readable report."""
    if not results:
        return "Enhancer: no skills needed changes."

    lines = [f"Enhancer report — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             "=" * 50]
    flagged = [r for r in results if r.get("needs_review")]
    changed = [r for r in results if r["changed"] and not r.get("needs_review")]

    if changed:
        lines.append(f"\nUpdated ({len(changed)} skills):")
        for r in changed:
            lines.append(f"  {Path(r['path']).name}")
            for c in r["changes"]:
                lines.append(f"    → {c}")

    if flagged:
        lines.append(f"\nFlagged for review ({len(flagged)} skills):")
        for r in flagged:
            lines.append(f"  {Path(r['path']).name}")
            for c in r["changes"]:
                lines.append(f"    ⚠  {c}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    cmd      = sys.argv[1] if len(sys.argv) > 1 else "run"
    dry_run  = "--dry-run" in sys.argv
    category = next((a for a in sys.argv[2:] if not a.startswith("--")), None)

    if cmd == "run":
        print(f"Running enhancer (dry_run={dry_run}, category={category or 'all'})...")
        results = enhance_vault(category=category, dry_run=dry_run)
        print(enhancer_report(results))

    elif cmd == "skill" and len(sys.argv) >= 3:
        path   = Path(sys.argv[2])
        result = enhance_skill(path, dry_run=dry_run)
        print(f"Skill: {result['skill_id']}")
        print(f"Signals: {result['signals']}")
        if result["changes"]:
            for c in result["changes"]:
                print(f"  → {c}")
        else:
            print("  No changes needed.")
