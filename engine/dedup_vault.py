#!/usr/bin/env python3
"""
SkillGod Vault Deduplicator — dry-run first.

Ingestion produced many same-named skill files (some are stale copies of each
other). The runtime dedup in skills.find_skills() masks this at query time, but
the redundant files still live in the vault. This script cleans the data.

Strategy (safe by construction):
  1. Scan every *.md in vault/ and vault_free/.
  2. Group files by their frontmatter `name:` field.
  3. Within each name-group, sub-group by NORMALISED BODY (content hash):
       - Files with an identical body are TRUE duplicates. Keep the best one
         (highest confidence, newest `created:` on ties); mark the rest DELETE.
       - If a name has more than one distinct body, those distinct variants are
         a CONFLICT — real content differs, so a human must decide. Never
         auto-deleted.
  4. Dry run (default) prints the full plan and totals; deletes nothing.
  5. --execute performs the marked deletions, then rebuilds the SQLite index.

Usage:
  python engine/dedup_vault.py            # dry run (default)
  python engine/dedup_vault.py --execute  # actually delete + reindex
"""

import sys, re, hashlib
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from skills import _parse_frontmatter, VAULT_DIR, VAULT_FREE_DIR  # reuse parser

SCAN_DIRS = [VAULT_DIR, VAULT_FREE_DIR]


# ---------------------------------------------------------------------------
# Load + normalise
# ---------------------------------------------------------------------------

def _norm_body(body: str) -> str:
    """Normalise a skill body for content comparison: collapse whitespace."""
    return re.sub(r"\s+", " ", body).strip().lower()


def _body_hash(body: str) -> str:
    return hashlib.sha1(_norm_body(body).encode("utf-8")).hexdigest()


def _parse_created(v: str):
    """Best-effort sortable key for the `created:` field. Missing → oldest."""
    return str(v or "")


def _load(path: Path, vault_root: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_frontmatter(text)
    return {
        "path":       path,
        # vault_free/ is a curated free-tier SUBSET of vault/ — its files are
        # identical to their full-vault twins BY DESIGN. Never dedup across the
        # two vaults, or we delete the free tier. Namespace every skill by the
        # vault it lives in so grouping only collapses within-vault duplicates.
        "vault":      vault_root.name,
        "name":       (meta.get("name") or path.stem).strip(),
        "confidence": float(meta.get("confidence", 0.8) or 0.8),
        "created":    _parse_created(meta.get("created", "")),
        "bodyhash":   _body_hash(body),
    }


def _rank_key(f: dict):
    """Winner = highest confidence, newest created on ties."""
    return (f["confidence"], f["created"])


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def build_plan():
    files = []
    for d in SCAN_DIRS:
        if d.exists():
            files.extend(_load(p, d) for p in d.rglob("*.md"))

    # Group by (vault, name) so vault_free/ and vault/ are deduped independently.
    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in files:
        by_name[(f["vault"], f["name"].lower())].append(f)

    to_delete: list[tuple[dict, dict]] = []   # (loser, winner)
    conflicts: list[tuple[str, list[dict]]] = []  # (name, distinct variants)
    dup_group_sizes: dict[str, int] = {}

    for (vault, nm), group in by_name.items():
        if len(group) < 2:
            continue
        label = f"{nm} [{vault}]"
        dup_group_sizes[label] = len(group)

        # sub-group by identical body content
        by_body: dict[str, list[dict]] = defaultdict(list)
        for f in group:
            by_body[f["bodyhash"]].append(f)

        # within each identical-body cluster, keep the best, delete the rest
        for cluster in by_body.values():
            if len(cluster) < 2:
                continue
            winner = max(cluster, key=_rank_key)
            for f in cluster:
                if f["path"] != winner["path"]:
                    to_delete.append((f, winner))

        # more than one DISTINCT body under the same name → conflict
        if len(by_body) > 1:
            reps = [max(c, key=_rank_key) for c in by_body.values()]
            conflicts.append((label, reps))

    return files, by_name, to_delete, conflicts, dup_group_sizes


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(VAULT_DIR.parent))
    except ValueError:
        return str(p)


def run(execute: bool = False):
    files, by_name, to_delete, conflicts, dup_sizes = build_plan()

    print("=" * 68)
    print("SkillGod Vault Dedup —", "EXECUTE" if execute else "DRY RUN")
    print("=" * 68)

    if to_delete:
        print("\n--- Files that would be DELETED (exact content duplicates) ---")
        for loser, winner in sorted(to_delete, key=lambda x: x[0]["name"]):
            print(f"\n  name: {loser['name']}")
            print(f"    DELETE {_rel(loser['path'])}"
                  f"  (conf={loser['confidence']}, created={loser['created'] or '-'})")
            print(f"    KEEP   {_rel(winner['path'])}"
                  f"  (conf={winner['confidence']}, created={winner['created'] or '-'})")
            reason = ("higher confidence"
                      if winner["confidence"] > loser["confidence"]
                      else "newer created (confidence tied)")
            print(f"    WHY    winner has {reason}")

    if conflicts:
        print("\n--- CONFLICTS (same name, DIFFERENT content — manual review) ---")
        for name, reps in sorted(conflicts):
            print(f"\n  name: {name}  ({len(reps)} distinct versions)")
            for f in sorted(reps, key=lambda x: _rel(x["path"])):
                print(f"    - {_rel(f['path'])}"
                      f"  (conf={f['confidence']}, created={f['created'] or '-'})")

    unique_names = len(by_name)
    dup_groups   = len(dup_sizes)
    top10 = sorted(dup_sizes.items(), key=lambda x: -x[1])[:10]

    print("\n" + "=" * 68)
    print("SUMMARY")
    print("=" * 68)
    print(f"  Total files scanned          : {len(files)}")
    print(f"  Unique skill names           : {unique_names}")
    print(f"  Duplicate groups (>1 file)   : {dup_groups}")
    print(f"  Files to delete (exact dupes): {len(to_delete)}")
    print(f"  Conflicts (manual review)    : {len(conflicts)}")
    print(f"  Files remaining after delete : {len(files) - len(to_delete)}")
    print(f"\n  Top 10 most duplicated skill names:")
    for name, n in top10:
        print(f"    {n:>3}x  {name}")

    if not execute:
        print("\n[dry run] Nothing deleted. Re-run with --execute to apply.")
        return

    # --- execute ---
    print("\n--- EXECUTING DELETIONS ---")
    deleted = 0
    for loser, _winner in to_delete:
        try:
            loser["path"].unlink()
            print(f"  deleted {_rel(loser['path'])}")
            deleted += 1
        except Exception as e:
            print(f"  FAILED  {_rel(loser['path'])}: {e}")
    print(f"\n  Deleted {deleted} files.")

    print("\n--- REBUILDING INDEX ---")
    from skills import rebuild_index
    count = rebuild_index()
    print(f"  Index rebuilt — {count} skills indexed.")
    if conflicts:
        print(f"\n[!] {len(conflicts)} name conflicts still need manual review "
              f"(different content under one name).")


if __name__ == "__main__":
    run(execute="--execute" in sys.argv)
