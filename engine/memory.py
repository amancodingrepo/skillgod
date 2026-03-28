#!/usr/bin/env python3
"""
SkillGod Memory Layer
Architecture from claude-mem — SQLite local, no cloud, no server.

Stores: decisions, patterns, errors, context — per project.
Injected at SessionStart and PreToolUse.
Never touches the vault. Completely separate concern.
"""

import sqlite3, json, re
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


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
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

def get_recent(project: str = "default", limit: int = 10) -> list[dict]:
    """Get most recent memories for a project."""
    conn = get_db()
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
    """Get memories relevant to a task using keyword matching."""
    task_words = set(re.findall(r'\b\w{4,}\b', task.lower()))
    all_mem    = get_recent(project, limit=50)
    scored     = []
    for m in all_mem:
        mem_words = set(re.findall(r'\b\w{4,}\b',
                                   f"{m['summary']} {m['detail']}".lower()))
        overlap   = len(task_words & mem_words) / max(len(task_words), 1)
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


def get_memory_index(project: str = "default") -> list[dict]:
    """
    Return a lightweight index of memories for the project.
    Each entry: { id, kind, summary, created_at }
    Used for progressive disclosure in Obsidian / CLI.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT id, kind, summary, created_at FROM memory "
        "WHERE project=? ORDER BY created_at DESC",
        (project,)
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