#!/usr/bin/env python3
"""
SkillGod Memory Layer
Architecture from claude-mem — SQLite local, no cloud, no server.

Stores: decisions, patterns, errors, context — per project.
Injected at SessionStart and PreToolUse.
Never touches the vault. Completely separate concern.
"""

import sqlite3, json, re, subprocess
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "db" / "skillgod.db"

MEMORY_KINDS = {"decision", "pattern", "error", "context"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT    NOT NULL DEFAULT 'default',
    kind        TEXT    NOT NULL DEFAULT 'context',
    summary     TEXT    NOT NULL,
    detail      TEXT    DEFAULT '',
    session_id  TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL,
    importance  REAL    DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    project     TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    ended_at    TEXT,
    task_count  INTEGER DEFAULT 0,
    summary     TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skills (
    id          TEXT    PRIMARY KEY,
    path        TEXT    UNIQUE,
    name        TEXT,
    description TEXT,
    tags        TEXT,
    triggers    TEXT,
    skill_type  TEXT    DEFAULT 'skill',
    confidence  REAL    DEFAULT 0.8,
    uses        INTEGER DEFAULT 0,
    created_at  TEXT,
    body        TEXT,
    lib_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_project   ON memory(project);
CREATE INDEX IF NOT EXISTS idx_memory_kind      ON memory(kind);
CREATE INDEX IF NOT EXISTS idx_memory_created   ON memory(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_skills_type      ON skills(skill_type);
"""

# Default importance floor for what `sg timeline` shows and what the injection
# recall path surfaces. Everything is CAPTURED regardless; this only filters
# reads. Kept at 0.6 so genuine decisions (>=0.85) show and conventional-commit
# noise (<=0.15) is hidden by default.
TIMELINE_MIN_IMPORTANCE = 0.6
INJECT_MIN_IMPORTANCE   = 0.6


# ─────────────────────────────────────────────────────────────────────────
# Decision-importance classifier  (Task 1 — root-cause fix)
#
# Replaces the old binary keep/discard keyword gate (which rejected explicit
# "decision:" / "instead of" / "switching to" commits and kept incidental
# noise). Design: CAPTURE EVERYTHING, score 0.0–1.0 at write time, filter at
# read time. Silent loss is the worst failure mode for a memory product.
# The subject line (first line) is weighted far above the body.
# ─────────────────────────────────────────────────────────────────────────

# Slam-dunk decision markers — an explicit architectural choice. (regex, name)
_DECISION_MARKERS = [
    (r"\bdecision\s*[:\-]", "decision:"),
    (r"\bwe\s+decided\b",              "we decided"),
    (r"\bdecided\b",                   "decided"),
    (r"\bdecide[sd]?\s+to\b",          "decide to"),
    (r"\bchose\b",                     "chose"),
    (r"\bchoos(?:e|ing)\b",            "choosing"),
    (r"\bswitch(?:ing|ed)?\s+to\b",    "switching to"),
    (r"\bswitch(?:ing|ed)?\s+from\b",  "switching from"),
    (r"\binstead\s+of\b",              "instead of"),
    (r"\bmigrat(?:e|es|ing|ed)\s+to\b","migrating to"),
    (r"\badopt(?:s|ing|ed)?\b",        "adopting"),
    (r"\bwe\s+will\s+use\b",           "we will use"),
    (r"\bwe\s+will\b",                 "we will"),
    (r"\bgoing\s+with\b",              "going with"),
    (r"\bin\s+favou?r\s+of\b",         "in favor of"),
    (r"\btrade[\s\-]?off\b",           "tradeoff"),
    (r"\brevert(?:ed|ing)?\b[^\n]*\bbecause\b", "revert because"),
    (r"\bstandardiz(?:e|es|ing|ed)\s+on\b",     "standardize on"),
    (r"\balways\s+use\b",              "always use"),
    (r"\bnever\s+use\b",               "never use"),
]

# Pure-noise conventional-commit prefixes / markers.
_NOISE_MARKERS = [
    (r"^\s*chore\s*[:\(]",  "chore:"),
    (r"^\s*build\s*[:\(]",  "build:"),
    (r"^\s*ci\s*[:\(]",     "ci:"),
    (r"^\s*style\s*[:\(]",  "style:"),
    (r"^\s*merge\b",        "merge"),
    (r"^\s*wip\b",          "wip"),
    (r"\bbump\b",           "bump"),
    (r"\bfix\s+typo\b",     "fix typo"),
    (r"\bformatting\b",     "formatting"),
    (r"\blint(?:ing)?\b",   "lint"),
]

_DOCS_PREFIX    = re.compile(r"^\s*docs\s*[:\(]", re.IGNORECASE)
_VERSION_BUMP   = re.compile(r"^\s*(?:bump\b|release\b|v?\d+\.\d+\.\d+\s*$)", re.IGNORECASE)


def score_importance(message: str) -> tuple[float, list[str]]:
    """Score a commit/decision message 0.0–1.0, returning (importance, matched).

    Never discards — the caller captures every message; this only ranks. Case-
    insensitive; the subject line (first line) is weighted above the body. Never
    raises on any input (including empty or non-ASCII)."""
    msg = (message or "").strip()
    if not msg:
        return 0.05, ["empty"]
    lines = msg.splitlines()
    subject = lines[0] if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""

    subj_hits, body_hits = [], []
    for pat, name in _DECISION_MARKERS:
        if re.search(pat, subject, re.IGNORECASE):
            subj_hits.append(name)
        elif re.search(pat, body, re.IGNORECASE):
            body_hits.append(name)

    is_docs = _DOCS_PREFIX.match(subject) is not None

    # A decision stated right in the subject line — highest confidence, and it
    # overrides a docs: / noise prefix (intent beats prefix).
    if subj_hits:
        imp = 0.95 if len(subj_hits) >= 2 else 0.9
        if is_docs:
            imp = max(0.7, imp - 0.1)  # docs+slam-dunk in subject → high, >=0.7
        return round(imp, 2), subj_hits + body_hits

    # docs: prefix without a subject-line decision → capped low regardless of
    # body (a design-doc mentioning "chose" is documentation, not a decision).
    if is_docs:
        return (0.4, body_hits + ["docs:"]) if body_hits else (0.3, ["docs:"])

    # Decision language only in the body → strong but not slam-dunk.
    if body_hits:
        return round(min(0.85, 0.5 + 0.15 * len(body_hits)), 2), body_hits

    # Pure noise prefixes / version bumps.
    noise = [name for pat, name in _NOISE_MARKERS
             if re.search(pat, subject, re.IGNORECASE) or re.search(pat, msg, re.IGNORECASE)]
    if noise:
        return 0.1, noise
    if _VERSION_BUMP.match(subject):
        return 0.1, ["version-bump"]

    # Ordinary commit — mid baseline (shown with --all, hidden by default).
    return 0.35, []


def _tune_sqlite(conn: sqlite3.Connection) -> None:
    """Make the shared DB safe under concurrent access.

    Several processes hit this single file at once: one hook process per Claude
    session (and the user may run Claude in multiple repos), the background git
    watcher, and the MCP server. SQLite's default rollback-journal mode plus a
    zero busy-timeout means any concurrent write fails INSTANTLY with "database
    is locked" — and the memory-capture path swallows that, so decisions are
    silently dropped and `sg timeline` shows nothing. WAL lets readers run
    concurrently with a single writer; busy_timeout makes a brief lock wait and
    retry instead of erroring. journal_mode=WAL persists in the file header, so
    setting it once upgrades every future connection.
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    _tune_sqlite(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ─────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────

def save(summary: str, detail: str = "", kind: str = "context",
         project: str = "default", session_id: str = "",
         importance: float = 0.5) -> int:
    """Save a memory item. Returns row id."""
    if kind not in MEMORY_KINDS:
        kind = "context"
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO memory (project, kind, summary, detail, session_id, "
        "created_at, importance) VALUES (?,?,?,?,?,?,?)",
        (project, kind, summary[:500], detail[:2000], session_id,
         datetime.now().isoformat(), importance)
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def save_decision(summary: str, detail: str = "",
                  project: str = "default") -> int:
    return save(summary, detail, kind="decision",
                project=project, importance=0.9)


def save_pattern(summary: str, detail: str = "",
                 project: str = "default") -> int:
    return save(summary, detail, kind="pattern",
                project=project, importance=0.8)


def save_error(summary: str, detail: str = "",
               project: str = "default") -> int:
    return save(summary, detail, kind="error",
                project=project, importance=0.7)


# ─────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────

def get_recent(project: str = "default", limit: int = 10,
               session_id: str | None = None) -> list[dict]:
    """Get most recent memories for a project. When session_id is given,
    return only rows captured under that session — session_end.py uses this so
    a session summary reflects THIS session's work, not the whole project's
    history (which made every empty session in an old project re-summarize
    stale decisions into a fresh noise row)."""
    conn = get_db()
    if session_id:
        rows = conn.execute(
            "SELECT kind, summary, detail, created_at, importance "
            "FROM memory WHERE project=? AND session_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project, session_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT kind, summary, detail, created_at, importance "
            "FROM memory WHERE project=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_relevant(task: str, project: str = "default",
                 limit: int = 5) -> list[dict]:
    """Get memories relevant to a task using keyword matching.

    Filters by importance at read time (Task 1): now that the watcher captures
    EVERY commit (including low-importance noise at ~0.1), the injection path
    only surfaces rows at INJECT_MIN_IMPORTANCE or above — genuine decisions
    (>=0.85) and session summaries (0.6), never conventional-commit noise. This
    preserves the pre-fix injection volume (only decisions ever injected)."""
    task_words = set(re.findall(r'\b\w{4,}\b', task.lower()))
    all_mem    = [m for m in get_recent(project, limit=100)
                  if m.get("importance", 0.0) >= INJECT_MIN_IMPORTANCE]
    scored     = []
    for m in all_mem:
        mem_words = set(re.findall(r'\b\w{4,}\b',
                                   f"{m['summary']} {m['detail']}".lower()))
        # BUG-040 FIX — require at least one shared word (prefix-tolerant, so
        # "authentication" still matches a memory that says "auth"). Importance
        # alone (0.9 * 0.4 = 0.36 > threshold) previously let completely
        # unrelated memories ride along on every prompt.
        hits = sum(
            1 for tw in task_words
            if tw in mem_words
            or any(tw.startswith(mw) or mw.startswith(tw)
                   for mw in mem_words)
        )
        if hits == 0:
            continue
        overlap   = hits / max(len(task_words), 1)
        score     = overlap * 0.6 + m["importance"] * 0.4
        scored.append((score, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit] if _ > 0.1]


def format_for_injection(memories: list[dict]) -> str:
    """Format memory items for prompt injection."""
    if not memories:
        return ""
    lines = []
    for m in memories:
        date = m["created_at"][:10]
        lines.append(f"  [{m['kind']}] {date}: {m['summary']}")
    return "**Relevant project memory:**\n" + "\n".join(lines)


# ─────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────

def start_session(session_id: str, project: str = "default") -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, project, started_at) VALUES (?,?,?)",
        (session_id, project, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def end_session(session_id: str, summary: str = "") -> None:
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET ended_at=?, summary=? WHERE id=?",
        (datetime.now().isoformat(), summary, session_id)
    )
    conn.commit()
    conn.close()


def increment_task_count(session_id: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET task_count = task_count + 1 WHERE id=?",
        (session_id,)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────

def stats(project: str = None) -> dict:
    conn = get_db()
    if project:
        total = conn.execute(
            "SELECT COUNT(*) FROM memory WHERE project=?", (project,)
        ).fetchone()[0]
        by_kind = {}
        for row in conn.execute(
            "SELECT kind, COUNT(*) as c FROM memory WHERE project=? GROUP BY kind",
            (project,)
        ).fetchall():
            by_kind[row["kind"]] = row["c"]
    else:
        total = conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        by_kind = {}
        for row in conn.execute(
            "SELECT kind, COUNT(*) as c FROM memory GROUP BY kind"
        ).fetchall():
            by_kind[row["kind"]] = row["c"]

    projects = [r[0] for r in conn.execute(
        "SELECT DISTINCT project FROM memory"
    ).fetchall()]
    conn.close()
    return {"total": total, "by_kind": by_kind, "projects": projects}


def compress_observation(task: str, output: str) -> str:
    """
    Compress a (task, output) pair into a memory summary string.
    Extracts the most decision-relevant sentence from the output.
    Used by PostToolUse to auto-capture decisions into memory.
    """
    sentences = re.split(r'[.!?\n]+', output)
    SIGNALS = ["decided", "chose", "always", "never", "pattern", "approach",
               "fixed", "resolved", "convention", "we will", "standard"]
    for sent in sentences:
        s = sent.strip()
        if len(s) > 30 and any(sig in s.lower() for sig in SIGNALS):
            return s[:200]
    # Fall back to first non-trivial sentence
    for sent in sentences:
        s = sent.strip()
        if len(s) > 30:
            return s[:200]
    return output[:120]


def derive_project_id(cwd: str = "") -> str:
    """
    BUG-016 FIX — a stable, collision-resistant project identifier.

    Memory was keyed on `Path.cwd().name` (the bare folder name), so two
    unrelated projects both called "backend" shared one memory bucket, and
    renaming a folder orphaned its memory. This prefers the git remote URL
    (normalised to host/owner/repo — identical across clones/renames, unique
    across projects) and falls back to `<foldername>-<hash8(abspath)>` when
    there's no remote, so local-only projects with the same folder name still
    get distinct buckets. Returns a filesystem/DB-safe slug.
    """
    import hashlib as _hl
    base = Path(cwd) if cwd else Path.cwd()
    remote = ""
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(base), "config", "--get", "remote.origin.url"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        ).strip()
    except Exception:
        remote = ""

    if remote:
        # Normalise git@host:owner/repo.git and https://host/owner/repo.git
        norm = remote.lower()
        norm = re.sub(r"^\w+://", "", norm)
        norm = re.sub(r"^git@", "", norm).replace(":", "/", 1)
        norm = re.sub(r"\.git$", "", norm)
        norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
        return norm or base.name

    # No remote — disambiguate same-named local folders by absolute path hash.
    try:
        abspath = str(base.resolve())
    except Exception:
        abspath = str(base)
    digest = _hl.sha256(abspath.encode("utf-8")).hexdigest()[:8]
    folder = re.sub(r"[^A-Za-z0-9]+", "-", base.name).strip("-") or "project"
    return f"{folder}-{digest}"


def get_git_context() -> dict:
    """
    Return git context for the current working directory.
    Used to tag memories to the branch/commit they were captured on.
    Returns empty dict if not in a git repo.
    """
    ctx = {}
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace"
        ).strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace"
        ).strip()
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace"
        ).strip()
        ctx = {"branch": branch, "commit": commit, "last_commit_msg": msg}
    except Exception:
        pass
    return ctx


def save_with_git(summary: str, detail: str = "", kind: str = "context",
                  project: str = "default", importance: float = 0.5,
                  session_id: str = "") -> int:
    """Save a memory item with git context appended to detail."""
    git = get_git_context()
    if git:
        git_tag = f"[branch:{git['branch']} commit:{git['commit']}]"
        detail  = f"{detail} {git_tag}".strip()
    return save(summary, detail, kind=kind, project=project,
                session_id=session_id, importance=importance)


def get_timeline(project: str = "default", limit: int = 30,
                 min_importance: float = TIMELINE_MIN_IMPORTANCE) -> list[dict]:
    """
    Chronological memory timeline, newest first.
    Each entry: { kind, summary, detail, created_at, importance }. Powers
    `sg timeline`.

    Filters by importance (Task 1): default shows importance >= 0.6 (real
    decisions); pass min_importance=0.0 for `sg timeline --all`. Also returns a
    count of rows hidden below the threshold so the CLI can say "N low-importance
    entries hidden".

    BUG FIX — used to select only (kind, summary, created_at). The git
    branch/commit tag save_with_git() writes lives in `detail`, so `detail` is
    selected here too.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT kind, summary, detail, created_at, importance FROM memory "
        "WHERE project=? AND importance >= ? ORDER BY created_at DESC LIMIT ?",
        (project, min_importance, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def timeline_counts(project: str = "default",
                    min_importance: float = TIMELINE_MIN_IMPORTANCE) -> dict:
    """Row counts for `sg timeline`'s empty/partial-state messaging: total rows
    for the project and how many are hidden below the importance threshold."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM memory WHERE project=?",
                         (project,)).fetchone()[0]
    hidden = conn.execute(
        "SELECT COUNT(*) FROM memory WHERE project=? AND importance < ?",
        (project, min_importance)).fetchone()[0]
    conn.close()
    return {"total": total, "hidden": hidden, "shown": total - hidden}


def get_memory_index(project: str = "default", limit: int = 1000) -> list[dict]:
    """
    Return a lightweight index of memories for the project.
    Each entry: { id, kind, summary, created_at }
    Used for progressive disclosure in Obsidian / CLI.

    BUG-019 FIX — bounded by `limit` (newest first) so a long-lived project with
    tens of thousands of rows doesn't return the entire table on every call.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT id, kind, summary, created_at FROM memory "
        "WHERE project=? ORDER BY created_at DESC LIMIT ?",
        (project, limit)
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "kind": r["kind"],
             "summary": r["summary"], "created_at": r["created_at"]}
            for r in rows]


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        s = stats()
        print(f"Total memories: {s['total']}")
        print(f"Projects: {', '.join(s['projects']) or 'none'}")
        for k, c in s["by_kind"].items():
            print(f"  {k}: {c}")

    elif cmd == "add":
        project = sys.argv[2] if len(sys.argv) > 2 else "default"
        summary = input("Summary: ")
        kind    = input("Kind (decision/pattern/error/context): ") or "context"
        detail  = input("Detail (optional): ")
        row_id  = save(summary, detail, kind=kind, project=project)
        print(f"Saved memory #{row_id}")

    elif cmd == "show":
        project = sys.argv[2] if len(sys.argv) > 2 else "default"
        mems = get_recent(project, limit=20)
        if not mems:
            print(f"No memories for project: {project}")
        for m in mems:
            print(f"  [{m['kind']:10}] {m['created_at'][:10]}  {m['summary']}")