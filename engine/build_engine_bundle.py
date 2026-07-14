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
  hooks/*.py         — the 5 Claude Code lifecycle hooks (session_start,
                       user_prompt_submit, pre_tool, post_tool, session_end).
                       CRITICAL: `sg init` registers these into
                       ~/.claude/settings.json as absolute paths under
                       sgRoot/hooks/ (== ~/.skillgod/hooks/ on a real install).
                       Without them here, a fresh install registers hooks that
                       point at files that do not exist — every hook silently
                       non-functional, including SessionEnd.
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
import hashlib
import json
import subprocess
import sys
import zipfile
import tempfile
from pathlib import Path


def _git_short_sha() -> str:
    """Short git sha for the VERSION build-metadata suffix, or 'nogit'."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parent.parent),
             "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        ).strip() or "nogit"
    except Exception:
        return "nogit"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

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
HOOKS_DIR = REPO_ROOT / "hooks"
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
    # The 5 Claude Code lifecycle hooks. init.go registers them at
    # sgRoot/hooks/<name>, and the installer extracts engine.zip flat into
    # ~/.skillgod, so they MUST ship here at hooks/<name>.
    hook_files = sorted(HOOKS_DIR.glob("*.py"))
    instincts = sorted(VAULT_DIR.glob("instincts/*.md"))
    free_skills = pick_free_skills()

    # Task 4 — stamp a precise version: <base>+<short-sha>. The 'v' prefix is
    # normalized out on the reader side (cli/cmd/root.go versionBase).
    base = version.lstrip("vV")
    full_version = f"{base}+{_git_short_sha()}"

    # Task 4 — MANIFEST.json: sha256 of every engine/*.py and hooks/*.py so
    # `sg doctor` can detect a partially-updated / tampered engine on disk.
    manifest = {"version": full_version, "files": {}}
    for p in engine_files:
        manifest["files"][f"engine/{p.name}"] = _sha256(p)
    for p in hook_files:
        manifest["files"][f"hooks/{p.name}"] = _sha256(p)

    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        for p in engine_files:
            zf.write(p, f"engine/{p.name}")
        for p in hook_files:
            zf.write(p, f"hooks/{p.name}")
        for p in instincts:
            zf.write(p, f"vault/instincts/{p.name}")
        for p in free_skills:
            zf.write(p, f"vault/{p.parent.name}/{p.name}")
        zf.writestr("requirements.txt", ENGINE_REQUIREMENTS)
        zf.writestr("db/.gitkeep", "")
        zf.writestr("VERSION", full_version + "\n")
        zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True))

    # Guardrail: a bundle missing hooks is the exact bug this fixes — fail loud.
    EXPECTED_HOOKS = {"session_start.py", "user_prompt_submit.py",
                      "pre_tool.py", "post_tool.py", "session_end.py"}
    shipped = {p.name for p in hook_files}
    missing = EXPECTED_HOOKS - shipped
    if missing:
        print(f"ERROR: engine bundle is missing required hooks: {sorted(missing)}",
              file=sys.stderr)
        return 1

    # Task 4/3 self-check: the bundle must (a) contain VERSION + MANIFEST + all
    # hooks, and (b) import cleanly. Verify against the EXTRACTED tree so a
    # broken bundle fails the build, not the user's install.
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(str(out)) as zf:
            zf.extractall(td)
        root = Path(td)
        for req in ("VERSION", "MANIFEST.json", "engine/mcp_server.py"):
            if not (root / req).exists():
                print(f"ERROR: bundle self-check failed — missing {req}", file=sys.stderr)
                return 1
        # import smoke: the engine package must import against the bundled tree
        chk = subprocess.run(
            [sys.executable, "-c",
             "import sys,os; sys.path.insert(0, os.path.join(sys.argv[1],'engine')); "
             "import memory, runtime, security, license, fs_watcher; print('import-ok')",
             str(root)],
            capture_output=True, text=True)
        if "import-ok" not in (chk.stdout or ""):
            print(f"ERROR: bundle self-check failed — engine did not import:\n{chk.stderr}",
                  file=sys.stderr)
            return 1

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"engine bundle built: {out}")
    print(f"  version:    {full_version}")
    print(f"  engine:     {len(engine_files)} python files")
    print(f"  hooks:      {len(hook_files)} lifecycle hooks")
    print(f"  instincts:  {len(instincts)}")
    print(f"  skills:     {len(free_skills)} (free starter set)")
    print(f"  size:       {size_mb:.2f} MB")
    print()
    print("Next: upload to R2 at  releases/<version>/engine.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
