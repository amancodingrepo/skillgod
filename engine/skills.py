#!/usr/bin/env python3
"""
SkillGod Skills Engine
Scoring algorithm + injector from CLAUDE.md spec.
Format: superpowers/obra SKILL.md standard.

Scoring:
    trigger exact match  +0.35
    trigger fuzzy        +0.15  (difflib >= 0.82)
    tag exact            +0.20
    tag word match       +0.08
    word_overlap desc    up to +0.25
    confidence mult      × (0.7 + 0.3 * confidence)
    frequency boost      + min(uses * 0.008, 0.04)

Threshold: inject top 3 scoring >= 0.18
Instincts: ALL injected, no scoring.
"""

import re, json, sqlite3
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

ROOT      = Path(__file__).parent.parent
VAULT_DIR = ROOT / "vault"
DB_PATH   = ROOT / "db" / "skillgod.db"

SCORE_THRESHOLD = 0.18
TOP_K_DEFAULT   = 3


# ---------------------------------------------------------------------------
# Frontmatter parser
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
            # Parse YAML-style lists: [a, b, c]
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1]
                meta[k] = [i.strip().strip('"\'') for i in inner.split(",") if i.strip()]
            else:
                meta[k] = v
    return meta, text[end + 4:].strip()


def _load_skill_file(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta, body = _parse_frontmatter(text)
    return {
        "id":          meta.get("id") or path.stem,
        "name":        meta.get("name") or path.stem,
        "description": meta.get("description", ""),
        "tags":        meta.get("tags") or [],
        "triggers":    meta.get("triggers") or [],
        "skill_type":  meta.get("type") or meta.get("skill_type", "skill"),
        "confidence":  float(meta.get("confidence", 0.8)),
        "uses":        int(meta.get("uses", 0)),
        "lib_id":      meta.get("lib_id", ""),
        "source":      meta.get("source", ""),
        "body":        body,
        "path":        str(path),
    }


# ---------------------------------------------------------------------------
# Vault loader
# ---------------------------------------------------------------------------

def _load_all_skills(include_instincts: bool = True) -> list[dict]:
    skills = []
    if not VAULT_DIR.exists():
        return skills
    for md in VAULT_DIR.rglob("*.md"):
        sk = _load_skill_file(md)
        if sk is None:
            continue
        # Determine type from path if not set
        if "instincts" in md.parts and sk["skill_type"] == "skill":
            sk["skill_type"] = "instinct"
        if not include_instincts and sk["skill_type"] == "instinct":
            continue
        skills.append(sk)
    return skills


# ---------------------------------------------------------------------------
# Scoring (CLAUDE.md algorithm)
# ---------------------------------------------------------------------------

def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _word_overlap(desc: str, task: str) -> float:
    d_words = set(re.findall(r'\b\w{4,}\b', desc.lower()))
    t_words = set(re.findall(r'\b\w{4,}\b', task.lower()))
    if not d_words or not t_words:
        return 0.0
    overlap = len(d_words & t_words) / max(len(d_words), len(t_words))
    return min(overlap * 0.25, 0.25)


def _score_skill(skill: dict, task: str) -> float:
    task_lower = task.lower()
    task_words = set(re.findall(r'\b\w{3,}\b', task_lower))
    score      = 0.0

    for trigger in skill.get("triggers") or []:
        t = trigger.lower()
        if t in task_lower:
            score += 0.35
        elif any(_fuzzy(t, w) > 0.82 for w in task_words):
            score += 0.15

    for tag in skill.get("tags") or []:
        t = tag.lower()
        if t in task_lower:
            score += 0.20
        elif t in task_words:
            score += 0.08

    score += _word_overlap(skill.get("description", ""), task)

    confidence = float(skill.get("confidence", 0.8))
    score     *= (0.7 + 0.3 * confidence)

    uses   = int(skill.get("uses", 0))
    score += min(uses * 0.008, 0.04)

    return round(score, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_skills(task: str, top_k: int = TOP_K_DEFAULT) -> list[dict]:
    """
    Score all vault skills against a task.
    Returns top_k skills with score >= SCORE_THRESHOLD, highest first.
    Instincts are NOT returned here (use load_instincts() for those).
    """
    skills = _load_all_skills(include_instincts=False)

    # Fall back to DB if vault is empty
    if not skills:
        skills = _load_from_db()

    scored = []
    for sk in skills:
        if sk["skill_type"] == "instinct":
            continue
        s = _score_skill(sk, task)
        if s >= SCORE_THRESHOLD:
            sk["score"] = s
            scored.append(sk)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def load_instincts() -> str:
    """Load all instinct files. Returns concatenated string for injection."""
    instincts_dir = VAULT_DIR / "instincts"
    if not instincts_dir.exists():
        return ""
    parts = []
    for md in sorted(instincts_dir.glob("*.md")):
        sk = _load_skill_file(md)
        if sk:
            parts.append(f"### {sk['name']}\n{sk['body']}")
    if not parts:
        return ""
    return "**Always-on instincts:**\n\n" + "\n\n---\n\n".join(parts)


def inject_skills(task: str, skills: list[dict]) -> str:
    """Format a list of skills for injection into a prompt."""
    if not skills:
        return task
    lines = [task, "", "---", "**Relevant skills for this task:**", ""]
    for sk in skills:
        score_str = f" (score={sk.get('score', 0):.2f})" if "score" in sk else ""
        lines.append(f"### {sk['name']}{score_str}")
        lines.append(sk.get("body", "").strip())
        lines.append("")
    return "\n".join(lines)


def build_augmented_prompt(task: str, skills: list[dict] = None,
                            memory_context: str = "") -> str:
    """
    Build the full augmented prompt combining:
    task + instincts + matched skills + relevant memory.
    """
    parts = []

    instincts = load_instincts()
    if instincts:
        parts.append(instincts)

    if memory_context:
        parts.append(memory_context)

    if skills:
        skill_block = inject_skills("", skills).strip()
        if skill_block:
            parts.append(skill_block)

    parts.append(f"**Task:**\n{task}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Learning (auto-skill from session output)
# ---------------------------------------------------------------------------

MIN_BODY_WORDS   = 60
MIN_CODE_BLOCKS  = 1
LEARN_CONFIDENCE = 0.55

def _is_reusable(task: str, output: str) -> bool:
    """Heuristic: is this output worth saving as a skill?"""
    words      = len(output.split())
    code_blocks = output.count("```")
    steps       = len(re.findall(r'^\s*\d+[\.\)]\s', output, re.MULTILINE))
    return words >= MIN_BODY_WORDS and (code_blocks >= MIN_CODE_BLOCKS or steps >= 3)


def learn_skill(task: str, output: str,
                project: str = "default") -> Path | None:
    """
    Maybe learn a new skill from a task+output pair.
    Saves to vault/meta/ at confidence <= 0.69.
    Returns Path if saved, None if not reusable.
    """
    if not _is_reusable(task, output):
        return None

    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()[:50]).strip("-")
    name = task[:80].strip()
    desc = f"Use when {task[:120].lower().rstrip('.')}"

    # Extract tags from output words
    common = re.findall(r'\b[a-z]{4,}\b', output.lower())
    freq   = {}
    for w in common:
        freq[w] = freq.get(w, 0) + 1
    stopwords = {"this", "that", "with", "from", "have", "will", "your",
                 "code", "here", "then", "when", "each", "them", "they"}
    tags = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])
            if w not in stopwords][:5]

    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"type: skill\n"
        f"tags: [{', '.join(tags)}]\n"
        f"triggers: [{', '.join(task.lower().split()[:4])}]\n"
        f"description: {desc}\n"
        f"confidence: {LEARN_CONFIDENCE}\n"
        f"source: auto-learned\n"
        f"created: {datetime.now().date()}\n"
        f"uses: 0\n"
        f"---\n\n"
    )

    meta_dir = VAULT_DIR / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    dest = meta_dir / f"{slug}.md"
    dest.write_text(frontmatter + output, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# SQLite index
# ---------------------------------------------------------------------------

def rebuild_index() -> int:
    """
    Scan vault/*.md and upsert into DB skills table.
    Returns count of indexed skills.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY, path TEXT UNIQUE, name TEXT,
            description TEXT, tags TEXT, triggers TEXT,
            skill_type TEXT DEFAULT 'skill', confidence REAL DEFAULT 0.8,
            uses INTEGER DEFAULT 0, created_at TEXT, body TEXT, lib_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_skills_type ON skills(skill_type);
    """)
    conn.commit()

    count = 0
    for md in VAULT_DIR.rglob("*.md"):
        sk = _load_skill_file(md)
        if not sk:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO skills "
            "(id, path, name, description, tags, triggers, skill_type, "
            "confidence, uses, created_at, body, lib_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sk["id"],
                sk["path"],
                sk["name"],
                sk["description"],
                json.dumps(sk["tags"]),
                json.dumps(sk["triggers"]),
                sk["skill_type"],
                sk["confidence"],
                sk["uses"],
                datetime.now().isoformat(),
                sk["body"][:2000],
                sk["lib_id"],
            )
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def _load_from_db() -> list[dict]:
    """Load skills from SQLite if vault is empty."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM skills").fetchall()
        conn.close()
        result = []
        for r in rows:
            sk = dict(r)
            sk["tags"]     = json.loads(sk.get("tags") or "[]")
            sk["triggers"] = json.loads(sk.get("triggers") or "[]")
            result.append(sk)
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Stocktake (vault health audit)
# ---------------------------------------------------------------------------

FALLBACK_MARKER = "use when working with"   # auto-fallback pattern to flag


def stocktake() -> str:
    """
    Audit the vault. Returns a human-readable health report.
    Checks: description format, fallback descriptions, missing fields,
    confidence distribution, and description quality score.
    """
    all_skills = _load_all_skills(include_instincts=True)

    if not all_skills:
        return "Vault is empty. Run: python engine/ingest.py"

    total         = len(all_skills)
    bad_desc      = []      # does not start with "Use when"
    fallback_desc = []      # uses the generic "Use when working with X" pattern
    good_desc     = []      # proper "Use when <condition>" descriptions
    missing_tags  = []
    low_conf      = []
    by_type       = {}
    by_cat        = {}

    for sk in all_skills:
        t = sk["skill_type"]
        by_type[t] = by_type.get(t, 0) + 1

        p = Path(sk["path"])
        cat = p.parent.name if p.parent.name != "vault" else "root"
        by_cat[cat] = by_cat.get(cat, 0) + 1

        desc = sk.get("description", "").strip()

        if t != "instinct":
            if not desc.lower().startswith("use when"):
                bad_desc.append(sk["name"])
            elif desc.lower().startswith(FALLBACK_MARKER):
                fallback_desc.append(sk["name"])
            else:
                good_desc.append(sk["name"])

        if not sk.get("tags"):
            missing_tags.append(sk["name"])

        if sk.get("confidence", 1.0) < 0.5:
            low_conf.append(sk["name"])

    # Description quality score (0–100)
    non_instinct = len([s for s in all_skills if s["skill_type"] != "instinct"])
    quality_pct  = int(len(good_desc) / non_instinct * 100) if non_instinct else 0

    lines = [
        "=== SkillGod Vault Stocktake ===",
        f"Total skills  : {total}",
        f"Desc quality  : {quality_pct}%  "
        f"({len(good_desc)} good / {len(fallback_desc)} fallback / {len(bad_desc)} missing)",
        "",
        "By type:",
    ]
    for t, c in sorted(by_type.items()):
        lines.append(f"  {t:<14} {c:>4}")

    lines += ["", "By category:"]
    for c, n in sorted(by_cat.items()):
        lines.append(f"  vault/{c:<12} {n:>4}")

    # --- Fallback description section (separate from missing) ---
    if fallback_desc:
        lines += [
            "",
            f"[!] {len(fallback_desc)} skills with fallback descriptions "
            f"('Use when working with X'):",
            "   Fix: python engine/ingest.py --force",
        ] + [f"   - {n}" for n in fallback_desc[:15]]
        if len(fallback_desc) > 15:
            lines.append(f"   ... and {len(fallback_desc) - 15} more")

    if bad_desc:
        lines += [
            "",
            f"[!] {len(bad_desc)} skills with missing/broken descriptions "
            f"(must start with 'Use when'):",
        ] + [f"   - {n}" for n in bad_desc[:10]]
        if len(bad_desc) > 10:
            lines.append(f"   ... and {len(bad_desc) - 10} more")

    if missing_tags:
        lines += ["", f"[!] {len(missing_tags)} skills missing tags"]

    if low_conf:
        lines += ["", f"[!] {len(low_conf)} skills with confidence < 0.5 (review or discard)"]

    if not bad_desc and not missing_tags and not low_conf and not fallback_desc:
        lines.append("\n[ok] Vault looks healthy!")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"

    if cmd == "find":
        task = " ".join(sys.argv[2:]) or "debug Python error"
        skills = find_skills(task)
        if not skills:
            print(f"No skills matched: {task}")
        for sk in skills:
            print(f"  {sk['score']:.2f}  {sk['name']}")

    elif cmd == "stocktake":
        print(stocktake())

    elif cmd == "index":
        n = rebuild_index()
        print(f"Indexed {n} skills")

    elif cmd == "instincts":
        print(load_instincts() or "(no instincts in vault)")
