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

ROOT           = Path(__file__).parent.parent
VAULT_DIR      = ROOT / "vault"
VAULT_FREE_DIR = ROOT / "vault_free"   # 30 hand-picked starter skills
DB_PATH        = ROOT / "db" / "skillgod.db"

SCORE_THRESHOLD = 0.18
TOP_K_DEFAULT   = 3

# REVERSIBLE DECISION POINT (how instincts are XML-fenced on injection).
# False (default): instincts + scored skills share one <injected_expert_skills>
#                  envelope (they are all always-on/expert reference material).
# True:            instincts get a DEDICATED <injected_instincts> tag, separate
#                  from <injected_expert_skills> (which then holds only scored
#                  skills). Flip this ONE line — no other change needed; the very
#                  next injected prompt uses the chosen shape.
INSTINCTS_IN_SEPARATE_XML_TAG: bool = False


def get_license_tier() -> str:
    """
    Return 'pro' or 'free' from the local kv store (set by session_start.py's
    online check). No network call; falls back to 'free' if the key is missing.
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT value FROM kv WHERE key='license_status'"
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] == "pro" else "free"
    except Exception:
        return "free"


def get_active_skill_count() -> int:
    """
    Number of skills actually available to score for THIS install's tier.
    Pro  → full vault/ skill count. Free → vault_free/ skill count.
    Counts files on disk (the DB indexes vault/ only), so it matches exactly
    what find_skills() scores against via _get_active_vault_dir().
    """
    active = _get_active_vault_dir()
    if not active.exists():
        return 0
    return sum(1 for _ in active.rglob("*.md"))


def get_full_vault_count() -> int:
    """Total unique skill files in the full vault/ (all tiers)."""
    if not VAULT_DIR.exists():
        return 0
    return sum(1 for _ in VAULT_DIR.rglob("*.md"))


def _get_active_vault_dir() -> Path:
    """
    Return vault_free/ for free users, vault/ for Pro users.
    Falls back to vault/ if vault_free/ doesn't exist (dev mode).
    """
    if VAULT_FREE_DIR.exists():
        try:
            from license import is_pro_active, get_machine_id
            # FIX 8 — is_pro_active() now returns a dict, not a bool.
            if is_pro_active(get_machine_id()).get("active"):
                return VAULT_DIR
            return VAULT_FREE_DIR
        except Exception:
            # BUG-013 FIX — fail CLOSED to the free vault when entitlement can't
            # be determined, rather than serving the full Pro vault.
            return VAULT_FREE_DIR
    return VAULT_DIR


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


def _safe_float(v, default: float) -> float:
    """BUG-012 FIX — tolerate non-numeric frontmatter (e.g. `confidence: high`)
    instead of letting float()/int() raise ValueError out of the rglob loop and
    abort the entire index/scoring run."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _coerce_list(v) -> list:
    """Frontmatter tags/triggers should be lists; a bare string would otherwise
    be iterated character-by-character during scoring."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _load_skill_file(path: Path) -> dict | None:
    # BUG-012 FIX — a single malformed skill file must never crash the whole
    # vault load / rebuild_index; wrap parsing and coerce numeric fields safely.
    try:
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        return {
            "id":          meta.get("id") or path.stem,
            "name":        meta.get("name") or path.stem,
            "description": meta.get("description", "") if isinstance(meta.get("description", ""), str) else "",
            "tags":        _coerce_list(meta.get("tags")),
            "triggers":    _coerce_list(meta.get("triggers")),
            "skill_type":  meta.get("type") or meta.get("skill_type", "skill"),
            "confidence":  _safe_float(meta.get("confidence", 0.8), 0.8),
            "uses":        _safe_int(meta.get("uses", 0), 0),
            "lib_id":      meta.get("lib_id", ""),
            "source":      meta.get("source", ""),
            "body":        body,
            "path":        str(path),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Vault loader
# ---------------------------------------------------------------------------

def _load_all_skills(include_instincts: bool = True) -> list[dict]:
    active_vault = _get_active_vault_dir()
    skills = []
    if not active_vault.exists():
        return skills
    for md in active_vault.rglob("*.md"):
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


def _fuzzy_fast(a: str, b: str, threshold: float = 0.82) -> bool:
    """PERF FIX (BUG-033) - difflib with cheap gates. The old code ran a full
    SequenceMatcher.ratio() for every trigger x task-word pair (~700ms/prompt
    on the full vault). Gate on length delta, first char, and difflib's
    upper-bound estimators so the expensive ratio() only runs on plausible
    matches."""
    if abs(len(a) - len(b)) > 3:
        return False
    if a[:1] != b[:1]:
        return False
    sm = SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() <= threshold:
        return False
    if sm.quick_ratio() <= threshold:
        return False
    return sm.ratio() > threshold


def _phrase_match(needle: str, haystack: str, tokens: set) -> bool:
    """WORD-BOUNDARY FIX (BUG-034) - trigger/tag matching was substring
    ("check" matched "checkout", injecting grammar skills into payment tasks).
    Single words must match a whole token; multi-word phrases must sit on word
    boundaries."""
    if " " not in needle:
        return needle in tokens
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
                     haystack) is not None


def _word_overlap(desc: str, t_words: set) -> float:
    d_words = set(re.findall(r'\b\w{4,}\b', desc.lower()))
    if not d_words or not t_words:
        return 0.0
    overlap = len(d_words & t_words) / max(len(d_words), len(t_words))
    return min(overlap * 0.25, 0.25)


class _TaskIndex:
    """PERF FIX (BUG-041) - find_skills() scores every vault skill (up to
    ~1,900 on the Pro tier) against the SAME task string. The old code
    re-derived task_lower/task_words/task_tokens from scratch via regex
    INSIDE _score_skill, once per skill (1,900 redundant re.findall passes
    per prompt), and the fuzzy-trigger fallback did an unbounded
    triggers x task_words nested loop with no way to skip non-candidates
    up front — 80k+ _fuzzy_fast calls on a full-vault prompt, ~330ms wall
    time measured via cProfile (vs. the ~15ms the design intends).
    This precomputes everything task-derived exactly ONCE per find_skills()
    call and buckets task words by first-char+length so the fuzzy fallback
    only ever looks at plausible candidates instead of the whole task."""

    __slots__ = ("task_lower", "task_tokens", "words_len3", "words_len4",
                 "by_first_char", "tokens_by_first_char",
                 "_fuzzy_cache", "_tag_cache")

    def __init__(self, task: str):
        self.task_lower = task.lower()
        self.task_tokens = set(re.findall(r'[a-z0-9]+', self.task_lower))
        self.words_len3 = set(re.findall(r'\b\w{3,}\b', self.task_lower))
        self.words_len4 = {w for w in self.words_len3 if len(w) >= 4}

        by_char: dict[str, list[str]] = {}
        for w in self.words_len3:
            by_char.setdefault(w[0], []).append(w)
        self.by_first_char = by_char

        # Same bucketing for the tag near-match fallback below, which used to
        # loop over ALL task_tokens (len > 3) for every non-exact tag.
        tok_by_char: dict[str, list[str]] = {}
        for w in self.task_tokens:
            if len(w) > 3:
                tok_by_char.setdefault(w[0], []).append(w)
        self.tokens_by_first_char = tok_by_char

        # Many skills in the vault share the same handful of triggers/tags
        # (e.g. "python", "debug"); cache the candidate lookup per string so
        # a 1,900-skill vault doesn't redo the same bucket lookup 1,900 times.
        self._fuzzy_cache: dict[str, list[str]] = {}
        self._tag_cache: dict[str, list[str]] = {}

    def fuzzy_candidates(self, trigger: str) -> list[str]:
        # Mirrors _fuzzy_fast's own gates (same first char, length delta <= 3)
        # so we only ever call SequenceMatcher on words that could plausibly
        # pass, instead of every word in the task.
        cached = self._fuzzy_cache.get(trigger)
        if cached is not None:
            return cached
        bucket = self.by_first_char.get(trigger[:1], ())
        tl = len(trigger)
        result = [w for w in bucket if abs(len(w) - tl) <= 3]
        self._fuzzy_cache[trigger] = result
        return result

    def tag_candidates(self, tag: str) -> list[str]:
        # Prefix match (either direction) requires the same first char, so
        # bucketing by first char is a safe, lossless narrowing — same idea
        # as fuzzy_candidates above, applied to the tag near-match fallback.
        cached = self._tag_cache.get(tag)
        if cached is not None:
            return cached
        result = self.tokens_by_first_char.get(tag[:1], ())
        self._tag_cache[tag] = result
        return result


def _score_skill(skill: dict, tidx: "_TaskIndex") -> tuple[float, list[str]]:
    """
    Score a skill against a task (via its precomputed _TaskIndex).
    Returns (score, matched_reasons) where matched_reasons explains why it fired.
    e.g. reasons = ['"debug"', '"traceback"', '#python', 'desc']
    """
    task_lower  = tidx.task_lower
    task_tokens = tidx.task_tokens
    score      = 0.0
    reasons: list[str] = []

    for trigger in skill.get("triggers") or []:
        t = trigger.lower()
        if _phrase_match(t, task_lower, task_tokens):
            score   += 0.35
            reasons.append(f'"{trigger}"')
        elif " " not in t and any(_fuzzy_fast(t, w) for w in tidx.fuzzy_candidates(t)):
            score   += 0.15
            reasons.append(f'~"{trigger}"')

    for tag in skill.get("tags") or []:
        t = tag.lower()
        if _phrase_match(t, task_lower, task_tokens):
            score   += 0.20
            reasons.append(f'#{tag}')
        elif " " not in t and len(t) > 3 and any(
                (w.startswith(t) or t.startswith(w))
                for w in tidx.tag_candidates(t)):
            score   += 0.08
            reasons.append(f'#{tag}')

    overlap = _word_overlap(skill.get("description", ""), tidx.words_len4)
    score  += overlap
    if overlap > 0.05:
        reasons.append("desc")

    confidence = float(skill.get("confidence", 0.8))
    score     *= (0.7 + 0.3 * confidence)

    uses   = int(skill.get("uses", 0))
    score += min(uses * 0.008, 0.04)

    return round(score, 4), reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_skills(task: str, top_k: int = TOP_K_DEFAULT) -> list[dict]:
    """
    Score all vault skills against a task.
    Returns top_k skills with score >= SCORE_THRESHOLD, highest first.
    Each result includes 'matched': list of trigger/tag/desc reasons that fired.
    Instincts are NOT returned here (use load_instincts() for those).
    """
    # PERF FIX (BUG-033) - for the Pro vault, load from the SQLite index (one
    # query) instead of re-reading and re-parsing all ~1,900 .md files on every
    # prompt. The index is rebuilt at SessionStart and updated by learn_skill().
    # Tier boundary preserved (BUG-013): the DB only indexes vault/ (Pro), so
    # free users always load their own files directly (29 files, fast anyway).
    from_db = _get_active_vault_dir() == VAULT_DIR
    if from_db:
        skills = _cached_light_rows()
        if not skills:
            skills = _load_all_skills(include_instincts=False)
            from_db = False
    else:
        skills = _load_all_skills(include_instincts=False)

    tidx = _TaskIndex(task)
    scored = []
    for sk in skills:
        if sk["skill_type"] == "instinct":
            continue
        s, reasons = _score_skill(sk, tidx)
        if s >= SCORE_THRESHOLD:
            # Copy — `skills` may be the cached light-rows list shared across
            # calls in a long-lived process (MCP server); mutating the
            # cached dicts in place would leak this call's score/matched
            # into the next call's read of the same cached objects.
            sk_out = dict(sk)
            sk_out["score"]   = s
            sk_out["matched"] = reasons  # why this skill fired — shown in sg find
            scored.append(sk_out)

    # Dedup by skill name: ingestion produces many same-named files (some are
    # stale copies of each other), so a single logical skill can score multiple
    # times and both flood the results and waste the top-k injection budget.
    # Keep only the highest-scoring instance per name.
    best_by_name: dict[str, dict] = {}
    for sk in scored:
        key      = (sk.get("name") or sk.get("id") or sk["path"]).strip().lower()
        existing = best_by_name.get(key)
        if existing is None or sk["score"] > existing["score"]:
            best_by_name[key] = sk

    deduped = list(best_by_name.values())
    # BUG-015 FIX — deterministic ordering. Sorting by score alone left ties
    # resolved by rglob() filesystem order (OS-dependent), so identical prompts
    # could inject different skills on different machines. Break ties by name.
    deduped.sort(key=lambda x: (-x["score"], (x.get("name") or x.get("id") or x["path"]).lower()))
    winners = deduped[:top_k]

    # Backfill body for the actual winners only — the DB-light path above
    # loaded everything else without it.
    if from_db and winners:
        bodies = _fetch_bodies([w["path"] for w in winners])
        for w in winners:
            w["body"] = bodies.get(w["path"], w.get("body", ""))

    return winners


INSTINCT_MAX_WORDS = 120   # spec says 80; small buffer, hard cap here


def load_instincts() -> str:
    """Load all instinct files. Returns concatenated string for injection.

    TIER FIX (BUG-035) - reads the ACTIVE vault's instincts/ so free users get
    the free instincts, not the Pro set and not nothing.
    SIZE FIX (BUG-036) - skips any instinct whose body exceeds
    INSTINCT_MAX_WORDS; a mis-filed 2,000-word skill must never ride along on
    every single prompt."""
    instincts_dir = _get_active_vault_dir() / "instincts"
    if not instincts_dir.exists():
        return ""
    parts = []
    for md in sorted(instincts_dir.glob("*.md")):
        sk = _load_skill_file(md)
        if sk:
            if len(sk["body"].split()) > INSTINCT_MAX_WORDS:
                import sys as _sys
                print(f"[SkillGod] instinct too long, skipped: {md.name} "
                      f"(move it to a category vault)", file=_sys.stderr)
                continue
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
        matched    = sk.get("matched") or []
        why_str    = f" - matched: {', '.join(matched[:4])}" if matched else ""
        lines.append(f"### {sk['name']}{score_str}{why_str}")
        lines.append(sk.get("body", "").strip())
        lines.append("")
    return "\n".join(lines)


def build_augmented_prompt(task: str, skills: list[dict] = None,
                            memory_context: str = "") -> str:
    """
    Build the full augmented prompt combining:
    task + instincts + matched skills + relevant memory.

    RESEARCH ADOPTION 1.2 — the injected background context is wrapped in
    explicit XML tags so instruction-tuned models can cleanly separate
    authoritative injected material from the user's own prompt:
      <injected_expert_skills> ... </injected_expert_skills>   (instincts + scored skills)
      <project_historical_memory> ... </project_historical_memory>  (recalled memory)
    This is PURELY a delivery-envelope change: what instincts load, which skills
    score/inject, and which memories are selected are all unchanged — only how
    the final payload is fenced differs. Instincts are grouped inside
    <injected_expert_skills> because they are always-on expert-skill content;
    this is a deliberate, flaggable choice (the two-tag model from the research
    doc), not an accident.
    """
    parts = []

    instincts = load_instincts()
    skill_block = inject_skills("", skills).strip() if skills else ""

    if INSTINCTS_IN_SEPARATE_XML_TAG:
        # ── Variant B: instincts get their OWN <injected_instincts> tag,
        #    scored skills stay in <injected_expert_skills>. Flip the constant
        #    INSTINCTS_IN_SEPARATE_XML_TAG (below the imports) to True for this.
        if instincts:
            parts.append("<injected_instincts>\n"
                         + instincts
                         + "\n</injected_instincts>")
        if skill_block:
            parts.append("<injected_expert_skills>\n"
                         + skill_block
                         + "\n</injected_expert_skills>")
    else:
        # ── Variant A (default): always-on instincts + scored skills share one
        #    <injected_expert_skills> envelope.
        expert_parts = []
        if instincts:
            expert_parts.append(instincts)
        if skill_block:
            expert_parts.append(skill_block)
        if expert_parts:
            parts.append("<injected_expert_skills>\n"
                         + "\n\n".join(expert_parts)
                         + "\n</injected_expert_skills>")

    # Project memory envelope (unaffected by the instinct-tag choice).
    if memory_context:
        parts.append("<project_historical_memory>\n"
                     + memory_context
                     + "\n</project_historical_memory>")

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
    desc = f"Use when asked to {task[:120].lower().rstrip('.')}"

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
    _index_skill_file(dest)   # keep the SQLite index in sync (PERF FIX path)
    return dest


def _index_skill_file(path: Path) -> None:
    """Upsert a single skill file into the SQLite index (best-effort)."""
    sk = _load_skill_file(path)
    if not sk:
        return
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT OR REPLACE INTO skills "
            "(id, path, name, description, tags, triggers, skill_type, "
            "confidence, uses, created_at, body, lib_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sk["id"], sk["path"], sk["name"], sk["description"],
             json.dumps(sk["tags"]), json.dumps(sk["triggers"]),
             sk["skill_type"], sk["confidence"], sk["uses"],
             datetime.now().isoformat(), sk["body"], sk["lib_id"]))
        conn.commit()
        conn.close()
        _invalidate_light_cache()
    except Exception:
        pass  # SessionStart rebuild will catch up


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
    seen_paths: list[str] = []
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
                sk["body"],
                sk["lib_id"],
            )
        )
        seen_paths.append(sk["path"])
        count += 1

    # Prune rows for skill files that no longer exist. INSERT OR REPLACE only
    # upserts; without this, deleting a vault file leaves an orphan index row
    # (phantom skill) that a release built from this index would ship.
    seen = set(seen_paths)
    existing = [r[0] for r in conn.execute("SELECT path FROM skills").fetchall()]
    for p in existing:
        if p not in seen:
            conn.execute("DELETE FROM skills WHERE path = ?", (p,))

    conn.commit()
    conn.close()
    _invalidate_light_cache()
    return count


_DB_LIGHT_COLS = "id, path, name, description, tags, triggers, skill_type, confidence, uses, lib_id"

# PERF FIX (BUG-041) - the MCP server is a long-lived process for the
# duration of a session (unlike the CLI, which is a fresh process per
# invocation), so re-querying + re-json.loads-ing all ~1,900 rows on EVERY
# prompt inside that one process is pure waste once the vault hasn't
# changed. Cache the light rows in-process; invalidate on the only two
# writers (rebuild_index, _index_skill_file). Findings from find_skills()
# are always returned as copies (see find_skills), so callers mutating
# their result never corrupt this cache.
_light_rows_cache: list[dict] | None = None


def _invalidate_light_cache() -> None:
    global _light_rows_cache
    _light_rows_cache = None


def _cached_light_rows() -> list[dict]:
    global _light_rows_cache
    if _light_rows_cache is None:
        _light_rows_cache = _load_from_db(include_body=False)
    return _light_rows_cache


def _load_from_db(include_body: bool = True) -> list[dict]:
    """Load skills from SQLite if vault is empty.

    PERF FIX (BUG-041) - scoring only ever needs the ~3 winning skills' full
    body text (for injection); the other ~1,900 pay for a TEXT column they
    never touch. include_body=False skips it — callers that need body for
    specific skills should use _fetch_bodies() afterward."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cols = _DB_LIGHT_COLS if not include_body else "*"
        rows = conn.execute(f"SELECT {cols} FROM skills").fetchall()
        conn.close()
        result = []
        for r in rows:
            sk = dict(r)
            sk["tags"]     = json.loads(sk.get("tags") or "[]")
            sk["triggers"] = json.loads(sk.get("triggers") or "[]")
            if not include_body:
                sk["body"] = ""
            result.append(sk)
        return result
    except Exception:
        return []


def _fetch_bodies(paths: list[str]) -> dict[str, str]:
    """Fetch body text for a specific set of skill paths (the final top_k
    winners) — the one place find_skills() actually needs full skill content."""
    if not paths or not DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        placeholders = ",".join("?" for _ in paths)
        rows = conn.execute(
            f"SELECT path, body FROM skills WHERE path IN ({placeholders})", paths
        ).fetchall()
        conn.close()
        return {p: b for p, b in rows}
    except Exception:
        return {}


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
    fat_instincts = []   # instincts violating the 80-word body cap
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

        if t == "instinct" and len(sk.get("body", "").split()) > 80:
            fat_instincts.append(sk["name"])

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

    if fat_instincts:
        lines += ["", f"[!] {len(fat_instincts)} instincts exceed the 80-word body cap "
                      f"(move to a category vault):"]
        lines += [f"   - {n}" for n in fat_instincts[:15]]

    if (not bad_desc and not missing_tags and not low_conf
            and not fallback_desc and not fat_instincts):
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
