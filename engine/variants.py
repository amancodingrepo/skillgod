#!/usr/bin/env python3
"""
SkillGod Layer 2 — Variants & Promotion Queue.

Scans vault/meta/ for auto-learned skills eligible for promotion.
Maintains a local SQLite promotion queue for human review.

Promotion criteria:
  - confidence >= 0.70
  - description starts with "Use when"
  - not already in queue or already promoted/rejected

Usage:
  from variants import scan_meta_for_variants, get_promotion_queue
  from variants import approve_promotion, reject_promotion
"""

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT      = Path(__file__).parent.parent
VAULT     = ROOT / "vault"
META_DIR  = VAULT / "meta"
DB_PATH   = ROOT / "db" / "skillgod.db"

MIN_CONFIDENCE      = 0.70
FALLBACK_MARKER     = "use when working with"  # generic fallback — not good enough
PROMOTION_STATUSES  = ("pending", "approved", "rejected")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS promotion_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name  TEXT    NOT NULL,
            skill_path  TEXT    NOT NULL UNIQUE,
            category    TEXT    NOT NULL DEFAULT 'meta',
            confidence  REAL    NOT NULL DEFAULT 0.70,
            fires       INTEGER DEFAULT 0,
            accept_rate REAL    DEFAULT 0.0,
            description TEXT,
            status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','approved','rejected')),
            created_at  TEXT    NOT NULL,
            reviewed_at TEXT
        );
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Frontmatter helper
# ---------------------------------------------------------------------------

def _parse_meta(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def _is_promotable(meta: dict) -> bool:
    """Check all promotion criteria."""
    # Confidence gate
    try:
        conf = float(meta.get("confidence", 0))
    except (ValueError, TypeError):
        return False
    if conf < MIN_CONFIDENCE:
        return False

    # Description must start with "Use when" but NOT be the generic fallback
    desc = meta.get("description", "").strip().lower()
    if not desc.startswith("use when"):
        return False
    if desc.startswith(FALLBACK_MARKER):
        return False

    return True


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_meta_for_variants() -> list[dict]:
    """
    Scan vault/meta/ for skills eligible for promotion.
    Returns list of candidate dicts (not yet in queue or already decided).
    """
    if not META_DIR.exists():
        return []

    conn = _get_db()
    already_queued = {
        r["skill_path"]
        for r in conn.execute("SELECT skill_path FROM promotion_queue").fetchall()
    }
    conn.close()

    candidates = []
    for md in sorted(META_DIR.glob("*.md")):
        if str(md) in already_queued:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        meta = _parse_meta(text)
        if not _is_promotable(meta):
            continue

        candidates.append({
            "name":        meta.get("name") or md.stem,
            "path":        str(md),
            "confidence":  float(meta.get("confidence", 0.70)),
            "description": meta.get("description", ""),
            "content":     text,
        })

    return candidates


def add_to_promotion_queue(skill_name: str, category: str,
                            content: str, skill_path: str = "",
                            confidence: float = 0.70,
                            description: str = "") -> int:
    """
    Add a skill to the promotion queue.
    Returns the new queue id.
    """
    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO promotion_queue"
            "(skill_name, skill_path, category, confidence, description, "
            " status, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (skill_name, skill_path, category, confidence, description,
             "pending", datetime.now().isoformat())
        )
        conn.commit()
        row_id = cur.lastrowid or 0
    except Exception:
        row_id = 0
    conn.close()
    return row_id


def auto_enqueue_candidates() -> int:
    """Scan meta and add all eligible skills to queue. Returns count added."""
    candidates = scan_meta_for_variants()
    added = 0
    for c in candidates:
        row_id = add_to_promotion_queue(
            skill_name  = c["name"],
            category    = "meta",
            content     = c["content"],
            skill_path  = c["path"],
            confidence  = c["confidence"],
            description = c["description"],
        )
        if row_id:
            added += 1
    return added


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------

def get_promotion_queue(status: str = "pending") -> list[dict]:
    """Return queue items filtered by status."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM promotion_queue WHERE status=? ORDER BY confidence DESC, id ASC",
        (status,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_promotion(queue_id: int, target_category: str = "") -> bool:
    """
    Approve a queued skill for promotion.
    Copies file from vault/meta/ to vault/<target_category>/.
    Returns True on success.
    """
    conn = _get_db()
    row  = conn.execute(
        "SELECT * FROM promotion_queue WHERE id=? AND status='pending'",
        (queue_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False

    row = dict(row)
    category = target_category or row["category"]
    if category == "meta":
        category = "coding"  # default promotion target

    src  = Path(row["skill_path"])
    dest_dir = VAULT / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    try:
        shutil.copy2(src, dest)
    except Exception:
        conn.close()
        return False

    conn.execute(
        "UPDATE promotion_queue SET status='approved', reviewed_at=? WHERE id=?",
        (datetime.now().isoformat(), queue_id)
    )
    conn.commit()
    conn.close()
    return True


def reject_promotion(queue_id: int) -> bool:
    """Reject a queued skill (stays in meta, marked rejected)."""
    conn = _get_db()
    cur  = conn.execute(
        "UPDATE promotion_queue SET status='rejected', reviewed_at=? WHERE id=? AND status='pending'",
        (datetime.now().isoformat(), queue_id)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def queue_stats() -> dict:
    """Summary counts for all queue statuses."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM promotion_queue GROUP BY status"
    ).fetchall()
    conn.close()
    result = {"pending": 0, "approved": 0, "rejected": 0}
    for r in rows:
        result[r["status"]] = r["n"]
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        candidates = scan_meta_for_variants()
        added = auto_enqueue_candidates()
        print(f"Found {len(candidates)} candidates → {added} added to queue")
        queue = get_promotion_queue()
        if queue:
            print(f"\nPending ({len(queue)}):")
            for item in queue:
                print(f"  [{item['id']}] {item['skill_name']:<40}"
                      f" conf={item['confidence']:.2f}")
        else:
            print("Queue is empty.")

    elif cmd == "approve" and len(sys.argv) > 2:
        qid = int(sys.argv[2])
        cat = sys.argv[3] if len(sys.argv) > 3 else ""
        ok  = approve_promotion(qid, cat)
        print(f"Approved #{qid}: {'OK' if ok else 'FAILED'}")

    elif cmd == "reject" and len(sys.argv) > 2:
        qid = int(sys.argv[2])
        ok  = reject_promotion(qid)
        print(f"Rejected #{qid}: {'OK' if ok else 'FAILED'}")

    elif cmd == "stats":
        s = queue_stats()
        print(f"Queue — pending:{s['pending']} approved:{s['approved']} rejected:{s['rejected']}")
