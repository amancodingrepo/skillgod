#!/usr/bin/env python3
"""
build_engine_bundle.py — package the open-source runtime + free starter vault
into engine.zip for the one-line installer.

The installer (install.sh / install.ps1) downloads this zip from
  releases.skillgod.dev/<version>/engine.zip
and unpacks it to ~/.skillgod/ so that `sg init` can find
~/.skillgod/engine/mcp_server.py and the free vault.

What goes in (free tier only):
  engine/*.py        — the runtime (scoring, memory, security, agents, MCP server)
  vault/instincts/   — all always-on instincts (always free)
  vault/<free>/      — FREE_SKILL_COUNT highest-confidence starter skills
  requirements.txt   — engine deps (only needed for the MCP server)
  db/.gitkeep        — empty dir so the SQLite layer has somewhere to write
  VERSION            — bundle version marker

The Pro vault (full 1,927 encrypted skills) is delivered separately via
`sg sync` and build_vault_release.py — never in this bundle.

Usage:
  python engine/build_engine_bundle.py v1.0.0
  python engine/build_engine_bundle.py v1.0.0 --out dist/engine.zip
"""
import sys
import zipfile
import tempfile
from pathlib import Path

# Number of starter skills shipped free (instincts are always included on top).
FREE_SKILL_COUNT = 30

# Engine files that must NOT ship in the public bundle.
ENGINE_EXCLUDE = {
    "build_vault_release.py",  # admin: builds the encrypted Pro vault
    "build_engine_bundle.py",  # this script
    "_wtest.txt",              # scratch
}

# Engine deps required only when the MCP server actually runs.
ENGINE_REQUIREMENTS = "mcp>=1.2.0\n"

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
VAULT_DIR = REPO_ROOT / "vault"


def parse_confidence(md_path: Path) -> float:
    """Best-effort read of the `confidence:` frontmatter field."""
    try:
        with md_path.open("r", encoding="utf-8") as f:
            in_fm = False
            for line in f:
                s = line.strip()
                if s == "---":
                    if in_fm:
                        break
                    in_fm = True
                    continue
                if in_fm and s.lower().startswith("confidence:"):
                    try:
                        return float(s.split(":", 1)[1].strip())
                    except ValueError:
                        return 0.0
    except OSError:
        pass
    return 0.0


def pick_free_skills() -> list[Path]:
    """Highest-confidence skills across all non-instinct categories."""
    candidates: list[tuple[float, Path]] = []
    for md in VAULT_DIR.glob("*/*.md"):
        if md.parent.name in ("instincts", "meta"):
            continue
        candidates.append((parse_confidence(md), md))
    candidates.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in candidates[:FREE_SKILL_COUNT]]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python engine/build_engine_bundle.py <version> [--out PATH]")
        return 2
    version = sys.argv[1]

    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
    out = Path(out_path) if out_path else Path(tempfile.gettempdir()) / "engine.zip"

    engine_files = [
        p for p in ENGINE_DIR.glob("*.py") if p.name not in ENGINE_EXCLUDE
    ]
    instincts = sorted(VAULT_DIR.glob("instincts/*.md"))
    free_skills = pick_free_skills()

    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        for p in engine_files:
            zf.write(p, f"engine/{p.name}")
        for p in instincts:
            zf.write(p, f"vault/instincts/{p.name}")
        for p in free_skills:
            zf.write(p, f"vault/{p.parent.name}/{p.name}")
        zf.writestr("requirements.txt", ENGINE_REQUIREMENTS)
        zf.writestr("db/.gitkeep", "")
        zf.writestr("VERSION", version + "\n")

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"engine bundle built: {out}")
    print(f"  version:    {version}")
    print(f"  engine:     {len(engine_files)} python files")
    print(f"  instincts:  {len(instincts)}")
    print(f"  skills:     {len(free_skills)} (free starter set)")
    print(f"  size:       {size_mb:.2f} MB")
    print()
    print("Next: upload to R2 at  releases/<version>/engine.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
