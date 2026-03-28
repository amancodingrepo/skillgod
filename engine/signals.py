#!/usr/bin/env python3
"""
SkillGod Layer 2 — Local Signal Tracking.

Signals are opt-in (default OFF). All data stays on-device in SQLite.
When SKILLGOD_API is set, flush_signals() sends to the Railway backend.

Kinds:
  accept  — skill fired, no rework detected  → score 1.0
  rework  — skill fired, rework detected      → score max(0, 1 - count*0.25)
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "skillgod.db"

ENABLED_KEY = "signals_enabled"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id    TEXT    NOT NULL,
            skill_name  TEXT    NOT NULL,
            session_id  TEXT    NOT NULL,
            kind        TEXT    NOT NULL CHECK(kind IN ('accept','rework','learned')),
            rework_count INTEGER DEFAULT 0,
            score       REAL    NOT NULL,
            created_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_signals_skill  ON signals(skill_id);
        CREATE INDEX IF NOT EXISTS idx_signals_kind   ON signals(kind);

        CREATE TABLE IF NOT EXISTS kv (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Opt-in control
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """Signals are opt-in. Returns True if user has enabled them."""
    try:
        conn = _get_db()
        row  = conn.execute(
            "SELECT value FROM kv WHERE key=?", (ENABLED_KEY,)
        ).fetchone()
        conn.close()
        return row is not None and row["value"] == "1"
    except Exception:
        return False


def enable() -> None:
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)",
        (ENABLED_KEY, "1")
    )
    conn.commit()
    conn.close()


def disable() -> None:
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)",
        (ENABLED_KEY, "0")
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_no_rework(skill_id: str, skill_name: str, session_id: str) -> None:
    """Record that a skill fired and output was accepted without rework."""
    if not is_enabled():
        return
    conn = _get_db()
    conn.execute(
        "INSERT INTO signals(skill_id,skill_name,session_id,kind,rework_count,score,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (skill_id, skill_name, session_id, "accept", 0, 1.0,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def record_rework(skill_id: str, skill_name: str,
                  rework_count: int, session_id: str) -> None:
    """Record that output required rework after skill was active."""
    if not is_enabled():
        return
    score = max(0.0, round(1.0 - rework_count * 0.25, 4))
    conn  = _get_db()
    conn.execute(
        "INSERT INTO signals(skill_id,skill_name,session_id,kind,rework_count,score,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (skill_id, skill_name, session_id, "rework", rework_count, score,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def record_learned(skill_id: str, skill_name: str, session_id: str) -> None:
    """Record that a new skill was learned/created this session."""
    if not is_enabled():
        return
    conn = _get_db()
    conn.execute(
        "INSERT INTO signals (skill_id, skill_name, session_id, kind, score, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (skill_id, skill_name, session_id, "learned", 1.0,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def signal_stats() -> dict:
    """Overall signal stats for display."""
    if not is_enabled():
        return {"enabled": False}
    try:
        conn  = _get_db()
        total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        accepts = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE kind='accept'"
        ).fetchone()[0]
        reworks = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE kind='rework'"
        ).fetchone()[0]
        distinct_skills = conn.execute(
            "SELECT COUNT(DISTINCT skill_id) FROM signals"
        ).fetchone()[0]
        # Per-kind breakdown for detailed display
        kind_rows = conn.execute(
            "SELECT kind, COUNT(*) as c, AVG(score) as avg_s FROM signals GROUP BY kind"
        ).fetchall()
        conn.close()
        by_kind = {
            r[0]: {"count": r[1], "avg_score": round(r[2], 3)}
            for r in kind_rows
        }
        return {
            "enabled":         True,
            "total":           total,
            "accepts":         accepts,
            "reworks":         reworks,
            "distinct_skills": distinct_skills,
            "accept_rate":     round(accepts / total * 100, 1) if total else 0,
            "by_kind":         by_kind,
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}


def top_performing_skills(limit: int = 20) -> list[dict]:
    """
    Skills ranked by avg_score from signal data.
    Minimum 3 fires to appear (avoids noise).
    """
    if not is_enabled():
        return []
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT skill_name, COUNT(*) as fires, "
            "AVG(score) as avg_score, "
            "SUM(CASE WHEN kind='accept' THEN 1 ELSE 0 END) as accepts, "
            "SUM(CASE WHEN kind='rework' THEN 1 ELSE 0 END) as reworks "
            "FROM signals "
            "GROUP BY skill_name "
            "HAVING fires >= 3 "
            "ORDER BY avg_score DESC, fires DESC "
            "LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["accept_rate"] = (
                round(d["accepts"] / d["fires"] * 100, 1)
                if d["fires"] else 0
            )
            result.append(d)
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Rework detection
# ---------------------------------------------------------------------------

REWORK_WORDS = [
    "actually", "change that", "fix that", "not quite", "redo",
    "that is wrong", "no wait", "instead", "try again", "wrong",
    "that's not right", "incorrect", "nope", "revert",
]

def count_rework_signals(text: str) -> int:
    """Count rework-intent words in user text."""
    t = text.lower()
    return sum(1 for w in REWORK_WORDS if w in t)


# ---------------------------------------------------------------------------
# Future: API flush (activates when SKILLGOD_API env var is set)
# ---------------------------------------------------------------------------

def flush_signals() -> int:
    """
    Send buffered signals to Railway API.
    Noop until SKILLGOD_API env var is configured.
    Returns count of signals flushed.
    """
    api_url = os.environ.get("SKILLGOD_API", "")
    if not api_url:
        return 0  # local-only mode
    # TODO v1.1: batch POST to {api_url}/v1/signals
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "enable":
        enable()
        print("Signal tracking enabled.")
    elif cmd == "disable":
        disable()
        print("Signal tracking disabled.")
    elif cmd == "stats":
        s = signal_stats()
        if not s.get("enabled"):
            print("Signals disabled. Run: python engine/signals.py enable")
        else:
            print(f"Total signals : {s['total']}")
            print(f"Accept rate   : {s['accept_rate']}%")
            print(f"Skills tracked: {s['distinct_skills']}")
    elif cmd == "top":
        top = top_performing_skills()
        if not top:
            print("No signal data yet (min 3 fires per skill).")
        else:
            print("Top performing skills:")
            for s in top:
                print(f"  {s['skill_name']:<35} "
                      f"fires={s['fires']}  "
                      f"accept={s['accept_rate']}%  "
                      f"avg={s['avg_score']:.2f}")
