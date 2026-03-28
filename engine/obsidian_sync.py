#!/usr/bin/env python3
"""
SkillGod Obsidian Integration.

Creates a SKILLGOD_INDEX.md with Dataview queries so developers who keep
their vault in Obsidian get live skill tables without any extra config.

Usage:
    python engine/obsidian_sync.py        # write index
    sg vault                              # opens Obsidian if installed

The vault/ directory is a valid Obsidian vault already — skills are
plain markdown with frontmatter. No plugin needed, Dataview is optional.
"""

import os
from datetime import datetime
from pathlib import Path

ROOT      = Path(__file__).parent.parent
VAULT_DIR = ROOT / "vault"


def get_vault_mtime() -> float:
    """Return the most recent mtime across all vault .md files."""
    latest = 0.0
    for md in VAULT_DIR.rglob("*.md"):
        try:
            t = md.stat().st_mtime
            if t > latest:
                latest = t
        except OSError:
            pass
    return latest


def _count_by_category() -> dict[str, int]:
    cats: dict[str, int] = {}
    for md in VAULT_DIR.rglob("*.md"):
        if md.name in (".gitkeep", "SKILLGOD_INDEX.md"):
            continue
        cat = md.parent.name
        cats[cat] = cats.get(cat, 0) + 1
    return cats


def create_obsidian_dataview_note() -> Path:
    """
    Write vault/SKILLGOD_INDEX.md — a Dataview-powered index of all skills.
    Safe to call repeatedly; always overwrites with fresh counts.
    """
    cats   = _count_by_category()
    total  = sum(cats.values())
    today  = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "---",
        "name: SkillGod Index",
        "type: index",
        "description: Use when browsing the full skill vault in Obsidian or reviewing vault health",
        f"updated: {today}",
        f"total_skills: {total}",
        "---",
        "",
        "# SkillGod Vault Index",
        "",
        f"> Auto-generated {today} · {total} skills across {len(cats)} categories",
        "",
        "## By Category",
        "",
        "| Category | Skills |",
        "|---|---|",
    ]
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"| [[{cat}]] | {n} |")

    lines += [
        "",
        "## All Skills (Dataview)",
        "",
        "```dataview",
        "TABLE description, confidence, source",
        "FROM \"vault\"",
        "WHERE type = \"skill\"",
        "SORT confidence DESC",
        "LIMIT 50",
        "```",
        "",
        "## Instincts (always-on)",
        "",
        "```dataview",
        "LIST description",
        "FROM \"vault/instincts\"",
        "WHERE type = \"instinct\"",
        "```",
        "",
        "## Top Agent Skills",
        "",
        "```dataview",
        "TABLE description, source",
        "FROM \"vault/agents\"",
        "SORT file.mtime DESC",
        "LIMIT 20",
        "```",
        "",
        "## Recently Added",
        "",
        "```dataview",
        "TABLE description, confidence",
        "FROM \"vault\"",
        "SORT file.mtime DESC",
        "LIMIT 10",
        "```",
    ]

    out = VAULT_DIR / "SKILLGOD_INDEX.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def open_in_obsidian(vault_path: Path = None) -> bool:
    """
    Open the vault in Obsidian via the obsidian:// URI scheme.
    Returns True if the launch command was sent (does not guarantee Obsidian is installed).
    """
    import subprocess
    vp = str(vault_path or VAULT_DIR.resolve())
    uri = f"obsidian://open?path={vp}"
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "", uri], shell=False)
        elif os.uname().sysname == "Darwin":
            subprocess.Popen(["open", uri])
        else:
            subprocess.Popen(["xdg-open", uri])
        return True
    except Exception:
        return False


if __name__ == "__main__":
    idx = create_obsidian_dataview_note()
    mtime = get_vault_mtime()
    print(f"Index written: {idx}")
    print(f"Vault mtime:   {mtime}")
    print(f"Total skills:  {sum(_count_by_category().values())}")
