#!/usr/bin/env python3
"""
SkillGod Coupon System
Coupons grant free Pro vault access without payment.
Stored locally in SQLite. Validated offline.
"""

import sqlite3, secrets
from pathlib import Path
from datetime import datetime, timedelta

ROOT    = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "skillgod.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS coupons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    UNIQUE NOT NULL,
    description TEXT    DEFAULT '',
    max_uses    INTEGER DEFAULT 1,
    uses        INTEGER DEFAULT 0,
    expires_at  TEXT,
    tier        TEXT    DEFAULT 'pro',
    duration_days INTEGER DEFAULT 30,
    created_at  TEXT    NOT NULL,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL,
    machine_id  TEXT    NOT NULL,
    redeemed_at TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL
);
"""

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

# ── CREATE COUPONS ─────────────────────────────────────────

def create_coupon(
    code: str = None,
    description: str = "",
    max_uses: int = 1,
    duration_days: int = 30,
    expires_in_days: int = 90,
    tier: str = "pro"
) -> str:
    """
    Create a coupon code.

    code=None generates a random code like SKILL-X7K2-FREE
    max_uses=0 means unlimited
    duration_days=0 means permanent access
    """
    if not code:
        code = f"SKILL-{secrets.token_hex(2).upper()}-FREE"

    expires_at = None
    if expires_in_days:
        expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO coupons (code, description, max_uses, duration_days, "
        "expires_at, tier, created_at) VALUES (?,?,?,?,?,?,?)",
        (code.upper(), description, max_uses, duration_days,
         expires_at, tier, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return code.upper()


def create_batch(
    prefix: str,
    count: int,
    description: str = "",
    max_uses: int = 1,
    duration_days: int = 30
) -> list:
    """Generate multiple unique codes at once. Used for events/giveaways."""
    codes = []
    for _ in range(count):
        code = f"{prefix}-{secrets.token_hex(3).upper()}"
        create_coupon(
            code=code,
            description=description,
            max_uses=max_uses,
            duration_days=duration_days
        )
        codes.append(code)
    return codes

# ── REDEEM ─────────────────────────────────────────────────

def redeem(code: str, machine_id: str) -> dict:
    """
    Redeem a coupon code on this machine.
    Returns: { success, message, expires_at, tier }
    """
    code = code.upper().strip()
    conn = get_db()

    # Check coupon exists and is active
    coupon = conn.execute(
        "SELECT * FROM coupons WHERE code=? AND active=1", (code,)
    ).fetchone()

    if not coupon:
        conn.close()
        return {"success": False, "message": "Invalid coupon code"}

    # Check not expired
    if coupon["expires_at"]:
        if datetime.now().isoformat() > coupon["expires_at"]:
            conn.close()
            return {"success": False, "message": "Coupon has expired"}

    # Check usage limit
    if coupon["max_uses"] > 0 and coupon["uses"] >= coupon["max_uses"]:
        conn.close()
        return {"success": False, "message": "Coupon has reached its usage limit"}

    # Check this machine hasn't already used it
    already = conn.execute(
        "SELECT id FROM coupon_redemptions WHERE code=? AND machine_id=?",
        (code, machine_id)
    ).fetchone()

    if already:
        conn.close()
        return {"success": False, "message": "Coupon already redeemed on this machine"}

    # Calculate expiry
    if coupon["duration_days"] == 0:
        expires_at = "2099-12-31"  # permanent
        duration_str = "permanent"
    else:
        expires_at = (
            datetime.now() + timedelta(days=coupon["duration_days"])
        ).strftime("%Y-%m-%d")
        duration_str = f"{coupon['duration_days']} days"

    # Record redemption
    conn.execute(
        "INSERT INTO coupon_redemptions (code, machine_id, redeemed_at, expires_at) "
        "VALUES (?,?,?,?)",
        (code, machine_id, datetime.now().isoformat(), expires_at)
    )

    # Increment usage count
    conn.execute(
        "UPDATE coupons SET uses = uses + 1 WHERE code=?", (code,)
    )
    conn.commit()
    conn.close()

    return {
        "success":    True,
        "message":    f"Coupon redeemed — {duration_str} Pro access activated",
        "expires_at": expires_at,
        "tier":       coupon["tier"],
        "duration":   duration_str,
    }


def is_valid_redemption(machine_id: str) -> dict:
    """Check if this machine has an active coupon redemption."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM coupon_redemptions "
        "WHERE machine_id=? AND expires_at >= date('now') "
        "ORDER BY expires_at DESC LIMIT 1",
        (machine_id,)
    ).fetchone()
    conn.close()

    if row:
        return {
            "active":     True,
            "code":       row["code"],
            "expires_at": row["expires_at"],
        }
    return {"active": False}

# ── ADMIN ──────────────────────────────────────────────────

def list_coupons() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT code, description, uses, max_uses, expires_at, "
        "duration_days, active FROM coupons ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate(code: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE coupons SET active=0 WHERE code=?", (code.upper(),)
    )
    conn.commit()
    conn.close()


def coupon_stats() -> dict:
    conn = get_db()
    total    = conn.execute("SELECT COUNT(*) FROM coupons").fetchone()[0]
    active   = conn.execute(
        "SELECT COUNT(*) FROM coupons WHERE active=1"
    ).fetchone()[0]
    redeemed = conn.execute(
        "SELECT COUNT(*) FROM coupon_redemptions"
    ).fetchone()[0]
    active_redemptions = conn.execute(
        "SELECT COUNT(*) FROM coupon_redemptions WHERE expires_at >= date('now')"
    ).fetchone()[0]
    conn.close()
    return {
        "total_coupons":       total,
        "active_coupons":      active,
        "total_redemptions":   redeemed,
        "active_redemptions":  active_redemptions,
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "create":
        code = create_coupon(
            description=sys.argv[2] if len(sys.argv) > 2 else "manual",
            max_uses=int(sys.argv[3]) if len(sys.argv) > 3 else 1,
            duration_days=int(sys.argv[4]) if len(sys.argv) > 4 else 30,
        )
        print(f"Created: {code}")

    elif cmd == "batch":
        prefix   = sys.argv[2] if len(sys.argv) > 2 else "BETA"
        count    = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        desc     = sys.argv[4] if len(sys.argv) > 4 else "batch"
        codes    = create_batch(prefix, count, desc)
        print(f"Created {len(codes)} codes:")
        for c in codes: print(f"  {c}")

    elif cmd == "list":
        coupons = list_coupons()
        print(f"{'Code':<25} {'Uses':<10} {'Max':<6} {'Expires':<15} {'Active'}")
        for c in coupons:
            print(f"  {c['code']:<23} {c['uses']:<10} "
                  f"{c['max_uses'] or 'unlimited':<6} "
                  f"{c['expires_at'] or 'never':<15} "
                  f"{'yes' if c['active'] else 'no'}")

    elif cmd == "stats":
        s = coupon_stats()
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif cmd == "deactivate":
        deactivate(sys.argv[2])
        print(f"Deactivated: {sys.argv[2]}")
