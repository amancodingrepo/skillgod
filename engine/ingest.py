#!/usr/bin/env python3
"""
SkillGod Ingestion Pipeline
Reads every source repo and normalises into vault/

Source types handled:
  filesystem  — walk dirs for SKILL.md files (anthropic, superpowers, everything-cc)
  catalog     — parse README.md for GitHub links, fetch each (voltagent, awesome-cc)
  hooks       — extract hooks/commands from .claude/ dirs (awesome-claude-code)
  agents      — extract agent definitions from agent dirs (ruflo, agency-agents)

Usage:
  python engine/ingest.py                     # ingest everything
  python engine/ingest.py --source anthropic  # one source only
  python engine/ingest.py --dry-run           # preview, no writes
  python engine/ingest.py --stats             # show vault counts
"""

import os, re, sys, json, time, hashlib, textwrap, argparse
import urllib.request
from pathlib import Path
from datetime import datetime

ROOT        = Path(__file__).parent.parent
SOURCES_DIR = ROOT / "sources"
VAULT_DIR   = ROOT / "vault"
DB_DIR      = ROOT / "db"

CATEGORIES = {
    "instincts": ["always", "never", "must", "every time", "before claiming",
                  "verify before", "check before", "rule"],
    "coding":    ["python", "javascript", "typescript", "react", "debug", "refactor",
                  "test", "api", "backend", "frontend", "sql", "git", "code review",
                  "pr", "pull request", "function", "class", "module"],
    "design":    ["ui", "ux", "design", "figma", "layout", "component", "visual",
                  "wireframe", "prototype", "accessibility", "responsive"],
    "writing":   ["write", "document", "readme", "blog", "email", "communication",
                  "docs", "technical writing", "copywriting"],
    "devops":    ["deploy", "docker", "ci", "cd", "terraform", "aws", "cloud",
                  "kubernetes", "pipeline", "infrastructure", "helm"],
    "security":  ["security", "scan", "injection", "vulnerability", "audit", "owasp",
                  "penetration", "threat", "exploit", "xss", "csrf"],
    "research":  ["research", "search", "analyse", "analyze", "summarize", "investigate"],
    "agents":    ["agent", "swarm", "orchestrate", "spawn", "multi-agent", "hive",
                  "specialist", "autonomous", "loop", "prd"],
}

CONFIDENCE = {
    "anthropic":          0.92,
    "anthropic-native":   0.92,
    "superpowers":        0.88,
    "everything-cc":      0.85,
    "vercel-skills":      0.82,
    "vercel-agent-skills":0.80,
    "ruflo":              0.78,
    "agency-agents":      0.76,
    "mirofish":           0.72,
    "ui-ux-pro-max":      0.82,
    "ralph":              0.75,
    "voltagent":          0.70,
    "awesome-claude-code":0.68,
    "skill-seekers":      0.70,
}

SOURCES = {
    "anthropic": {
        "type": "filesystem",
        "path": SOURCES_DIR / "anthropic-skills",
        "glob": "skills/*/SKILL.md",
    },
    "anthropic-native": {
        "type": "filesystem",
        "path": SOURCES_DIR / "anthropic-native",
        "glob": "skills/*/SKILL.md",
    },
    "superpowers": {
        "type": "filesystem",
        "path": SOURCES_DIR / "superpowers",
        "glob": "skills/*/SKILL.md",
    },
    "everything-cc": {
        "type": "filesystem",
        "path": SOURCES_DIR / "everything-claude-code",
        "glob": "skills/*/SKILL.md",
    },
    "vercel-skills": {
        "type": "filesystem",
        "path": SOURCES_DIR / "vercel-skills",
        "glob": "**/SKILL.md",
    },
    "vercel-agent-skills": {
        "type": "filesystem",
        "path": SOURCES_DIR / "vercel-agent-skills",
        "glob": "**/SKILL.md",
    },
    "ruflo": {
        "type": "agents",
        "path": SOURCES_DIR / "ruflo",
        "skill_glob": "skills/*/SKILL.md",
        "agent_glob": "agents/**/*.md",
    },
    "agency-agents": {
        "type": "agents",
        "path": SOURCES_DIR / "agency-agents",
        "skill_glob": "**/SKILL.md",
        "agent_glob": "**/*.md",
    },
    "mirofish": {
        "type": "filesystem",
        "path": SOURCES_DIR / "mirofish",
        "glob": "**/SKILL.md",
    },
    "ui-ux-pro-max": {
        "type": "filesystem",
        "path": SOURCES_DIR / "ui-ux-pro-max",
        "glob": "**/SKILL.md",
    },
    "ralph": {
        "type": "filesystem",
        "path": SOURCES_DIR / "ralph",
        "glob": "**/SKILL.md",
    },
    "voltagent": {
        "type": "catalog",
        "path": SOURCES_DIR / "voltagent-skills",
        "readme": "README.md",
    },
    "awesome-claude-code": {
        "type": "hooks",
        "path": SOURCES_DIR / "awesome-claude-code",
        "readme": "README.md",
    },
}


# ─────────────────────────────────────────────
# FRONTMATTER PARSER
# ─────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    fm_raw, body = match.group(1), match.group(2).strip()
    meta = {}
    for line in fm_raw.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"\'') for x in v[1:-1].split(",") if x.strip()]
        meta[k.strip()] = v
    return meta, body


# ─────────────────────────────────────────────
# NORMALISATION
# ─────────────────────────────────────────────

def detect_category(name: str, desc: str, body: str) -> str:
    text = f"{name} {desc} {body}".lower()
    scores = {cat: sum(1 for kw in kws if kw in text)
              for cat, kws in CATEGORIES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "coding"


def fix_description(desc: str, name: str) -> str:
    if not desc:
        return f"Use when working on {name.replace('-', ' ').replace('_', ' ')} tasks"
    desc = desc.strip()
    if re.match(r"use (when|this|for)", desc, re.I):
        return desc
    # strip common bad prefixes
    for prefix in ["This skill", "A skill that", "Skill for",
                   "Helps with", "Provides", "Tool for", "Use to"]:
        if desc.lower().startswith(prefix.lower()):
            rest = desc[len(prefix):].strip().lstrip("that ").lstrip("to ").lstrip("for ")
            return f"Use when {rest[0].lower()}{rest[1:]}" if rest else desc
    return f"Use when {desc[0].lower()}{desc[1:]}"


def extract_triggers(name: str, desc: str) -> list[str]:
    stop = {"the","a","an","is","are","how","to","what","for","in","of","and",
            "or","with","this","skill","when","you","your","use","any","all",
            "use","when","working","tasks","want","need","does","from"}
    text = f"{name} {desc}".lower()
    words = [w for w in re.findall(r'\b\w{3,}\b', text) if w not in stop]
    seen, triggers = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            triggers.append(w)
        if len(triggers) >= 6:
            break
    return triggers


def make_slug(name: str) -> str:
    return re.sub(r"[^\w]+", "-", name.lower()).strip("-")[:50]


def normalise(name: str, desc: str, body: str, source: str,
              original_path: str = "", skill_type: str = "") -> dict:
    name  = (name or Path(original_path).parent.name or "unnamed").strip()
    desc  = fix_description(desc, name)
    cat   = detect_category(name, desc, body)

    # Auto-detect instinct: short body + absolute language
    word_count = len(body.split())
    has_absolute = bool(re.search(r"\b(always|never|must|every)\b", body.lower()))
    if not skill_type:
        skill_type = "instinct" if (word_count < 100 and has_absolute) else "skill"

    if skill_type == "instinct":
        cat = "instincts"

    return {
        "slug":          make_slug(name),
        "name":          name,
        "type":          skill_type,
        "category":      cat,
        "tags":          extract_triggers(name, desc),
        "triggers":      extract_triggers(name, desc)[:4],
        "description":   desc,
        "confidence":    CONFIDENCE.get(source, 0.70),
        "source":        source,
        "original_path": original_path,
        "created":       datetime.now().strftime("%Y-%m-%d"),
        "uses":          0,
        "body":          body,
    }


def to_markdown(skill: dict) -> str:
    tags_str     = "[" + ", ".join(skill["tags"])     + "]"
    triggers_str = "[" + ", ".join(skill["triggers"]) + "]"
    return textwrap.dedent(f"""\
        ---
        name: {skill["name"]}
        type: {skill["type"]}
        tags: {tags_str}
        triggers: {triggers_str}
        description: {skill["description"]}
        confidence: {skill["confidence"]}
        source: {skill["source"]}
        created: {skill["created"]}
        uses: 0
        ---

        {skill["body"]}
    """).strip()


def write_skill(skill: dict, dry_run: bool = False) -> tuple[Path, str]:
    """Write skill to vault. Returns (path, status)."""
    cat_dir = VAULT_DIR / skill["category"]
    out_path = cat_dir / f"{skill['slug']}.md"
    content  = to_markdown(skill)

    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        if existing.strip() == content.strip():
            return out_path, "unchanged"
        uid = hashlib.md5(skill["source"].encode()).hexdigest()[:4]
        out_path = cat_dir / f"{skill['slug']}-{uid}.md"

    if not dry_run:
        cat_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")

    return out_path, "written"


# ─────────────────────────────────────────────
# PARSERS
# ─────────────────────────────────────────────

def parse_filesystem(source_name: str, config: dict,
                     dry_run: bool = False) -> list[dict]:
    base    = config["path"]
    pattern = config.get("glob", "**/SKILL.md")
    results = []

    if not base.exists():
        print(f"  [skip] {source_name} — not found: {base}")
        return results

    files = list(base.glob(pattern))
    print(f"  [{source_name}] {len(files)} SKILL.md files")

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            meta, body = parse_frontmatter(text)
            if not body.strip():
                continue
            skill = normalise(
                name=meta.get("name", ""),
                desc=meta.get("description", ""),
                body=body,
                source=source_name,
                original_path=str(f),
            )
            path, status = write_skill(skill, dry_run)
            results.append({"name": skill["name"], "path": str(path),
                           "status": status, "category": skill["category"]})
        except Exception as e:
            print(f"    [error] {f.name}: {e}")

    return results


def parse_agents(source_name: str, config: dict,
                 dry_run: bool = False) -> list[dict]:
    """Parse both SKILL.md files and agent definition files."""
    results = parse_filesystem(source_name, {
        "path": config["path"],
        "glob": config.get("skill_glob", "**/SKILL.md"),
    }, dry_run)

    # Also ingest agent .md files as agent-type skills
    agent_glob = config.get("agent_glob", "agents/**/*.md")
    base = config["path"]
    if not base.exists():
        return results

    agent_files = [f for f in base.glob(agent_glob)
                   if f.name != "SKILL.md" and f.suffix == ".md"]
    print(f"  [{source_name}] {len(agent_files)} agent definition files")

    for f in agent_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            meta, body = parse_frontmatter(text)
            if not body.strip() or len(body.split()) < 20:
                continue
            name = meta.get("name", f.stem.replace("-", " ").replace("_", " "))
            skill = normalise(
                name=name,
                desc=meta.get("description", ""),
                body=body,
                source=source_name,
                original_path=str(f),
                skill_type="skill",
            )
            skill["category"] = "agents"
            path, status = write_skill(skill, dry_run)
            results.append({"name": skill["name"], "path": str(path),
                           "status": status, "category": "agents"})
        except Exception as e:
            print(f"    [error] {f.name}: {e}")

    return results


GITHUB_LINK_RE = re.compile(
    r'\[([^\]]+)\]\((https://github\.com/([^/]+)/([^/\)#\s]+)[^\)]*)\)'
)

def parse_catalog(source_name: str, config: dict,
                  dry_run: bool = False) -> list[dict]:
    """Parse catalog README for GitHub links, fetch each SKILL.md."""
    readme = config["path"] / config.get("readme", "README.md")
    if not readme.exists():
        print(f"  [skip] {source_name} — README not found")
        return []

    text  = readme.read_text(encoding="utf-8", errors="ignore")
    links = []
    seen  = set()

    for m in GITHUB_LINK_RE.finditer(text):
        label, url, owner, repo = m.groups()
        if any(s in url for s in ["/issues", "/blob/", "/tree/main/README",
                                   "LICENSE", "/wiki", "github.com/topics"]):
            continue
        if url in seen:
            continue
        seen.add(url)

        # Normalise to raw SKILL.md URL
        if "/tree/" in url or "/blob/" in url:
            raw = url.replace("github.com", "raw.githubusercontent.com")
            raw = re.sub(r"/(tree|blob)/", "/", raw)
            if not raw.endswith("SKILL.md"):
                raw = raw.rstrip("/") + "/SKILL.md"
        else:
            raw = (f"https://raw.githubusercontent.com/{owner}/{repo}"
                   f"/main/SKILL.md")

        links.append({"label": label, "url": url, "raw": raw,
                     "owner": owner, "repo": repo})

    print(f"  [{source_name}] {len(links)} catalog links found")
    results = []
    fetched = 0

    for link in links[:100]:  # cap at 100 per catalog to avoid rate limits
        try:
            req = urllib.request.Request(
                link["raw"],
                headers={"User-Agent": "SkillGod/1.0"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status != 200:
                    continue
                content = resp.read().decode("utf-8", errors="ignore")

            meta, body = parse_frontmatter(content)
            if not body.strip() or len(body.split()) < 30:
                continue

            skill = normalise(
                name=meta.get("name", link["label"]),
                desc=meta.get("description", ""),
                body=body,
                source=source_name,
                original_path=link["url"],
            )
            path, status = write_skill(skill, dry_run)
            results.append({"name": skill["name"], "path": str(path),
                           "status": status, "category": skill["category"]})
            fetched += 1
            time.sleep(0.3)  # polite rate limiting

        except Exception:
            pass  # network errors are expected, skip silently

    print(f"  [{source_name}] fetched {fetched} skills from catalog")
    return results


def parse_hooks(source_name: str, config: dict,
                dry_run: bool = False) -> list[dict]:
    """Extract hooks and commands from awesome-claude-code style repos."""
    base = config["path"]
    results = []

    if not base.exists():
        print(f"  [skip] {source_name} — not found")
        return results

    # First treat as filesystem for any SKILL.md files
    results += parse_filesystem(source_name, {
        "path": base,
        "glob": "**/SKILL.md",
    }, dry_run)

    # Also check .claude/commands/ for slash commands as skills
    commands_dirs = list(base.glob("**/.claude/commands/")) + \
                    list(base.glob("**/commands/"))

    cmd_count = 0
    for cmd_dir in commands_dirs:
        for f in cmd_dir.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                meta, body = parse_frontmatter(text)
                if not body.strip() or len(body.split()) < 15:
                    continue
                skill = normalise(
                    name=meta.get("name", f.stem.replace("-", " ")),
                    desc=meta.get("description", ""),
                    body=body,
                    source=source_name,
                    original_path=str(f),
                    skill_type="skill",
                )
                path, status = write_skill(skill, dry_run)
                results.append({"name": skill["name"], "path": str(path),
                               "status": status, "category": skill["category"]})
                cmd_count += 1
            except Exception:
                pass

    if cmd_count:
        print(f"  [{source_name}] {cmd_count} slash commands extracted")

    return results


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

PARSERS = {
    "filesystem": parse_filesystem,
    "catalog":    parse_catalog,
    "agents":     parse_agents,
    "hooks":      parse_hooks,
}


def ingest_all(only: str = None, dry_run: bool = False) -> dict:
    """Run ingestion for all sources (or one). Returns summary."""
    DB_DIR.mkdir(exist_ok=True)
    VAULT_DIR.mkdir(exist_ok=True)

    summary = {"written": 0, "unchanged": 0, "errors": 0, "by_category": {}}

    sources = {k: v for k, v in SOURCES.items()
               if only is None or k == only}

    for source_name, config in sources.items():
        print(f"\n[{source_name}]")
        parser = PARSERS.get(config["type"], parse_filesystem)
        try:
            results = parser(source_name, config, dry_run)
            for r in results:
                summary[r["status"]] = summary.get(r["status"], 0) + 1
                cat = r.get("category", "coding")
                summary["by_category"][cat] = \
                    summary["by_category"].get(cat, 0) + 1
        except Exception as e:
            print(f"  [ERROR] {source_name}: {e}")
            summary["errors"] += 1

    return summary


def show_stats() -> None:
    """Print vault statistics."""
    if not VAULT_DIR.exists():
        print("Vault is empty — run ingest first.")
        return
    total = 0
    for cat_dir in sorted(VAULT_DIR.iterdir()):
        if cat_dir.is_dir():
            count = len(list(cat_dir.glob("*.md")))
            total += count
            print(f"  {cat_dir.name:<20} {count} skills")
    print(f"  {'TOTAL':<20} {total}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SkillGod ingestion pipeline")
    ap.add_argument("--source", help="Ingest one source only")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing")
    ap.add_argument("--stats", action="store_true", help="Show vault stats")
    args = ap.parse_args()

    if args.stats:
        show_stats()
        sys.exit(0)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    target = args.source or "all sources"
    print(f"SkillGod ingestion — {mode} — {target}")
    print("=" * 50)

    summary = ingest_all(only=args.source, dry_run=args.dry_run)

    print("\n" + "=" * 50)
    print(f"Written:   {summary.get('written', 0)}")
    print(f"Unchanged: {summary.get('unchanged', 0)}")
    print(f"Errors:    {summary.get('errors', 0)}")
    print("\nBy category:")
    for cat, count in sorted(summary["by_category"].items()):
        print(f"  {cat:<20} {count}")