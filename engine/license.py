#!/usr/bin/env python3
"""
SkillGod License Validation
============================
LemonSqueezy license key validation with SQLite offline cache.

Public API:
    get_machine_id() -> str
    validate_key(license_key, machine_id) -> bool
    cache_validation(key, result, ttl_days=30)
    check_license(license_key) -> dict   ← main entry point for sync.go

Offline grace: validation result cached in SQLite for ttl_days (default 30).
The 30-day clock resets each time validation succeeds while online.
Never breaks a dev's workflow.
"""

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

ROOT    = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "skillgod.db"

# SkillGod API (Railway backend)
# Override with SKILLGOD_API env var for local testing
SKILLGOD_API_URL = os.environ.get(
    "SKILLGOD_API",
    "https://api.skillgod.dev"
).rstrip("/")

# Cache TTL
DEFAULT_TTL_DAYS = 30


# ---------------------------------------------------------------------------
# Machine ID
# ---------------------------------------------------------------------------

def get_machine_id() -> str:
    """
    Returns a stable, hardware-based machine identifier.

    Windows : wmic csproduct get UUID
    macOS   : ioreg -rd1 -c IOPlatformExpertDevice | grep UUID
    Linux   : /etc/machine-id or /var/lib/dbus/machine-id

    Falls back to a hostname+platform hash if the above fail.
    """
    raw = _raw_machine_id()
    # Always return a 32-char hex digest — consistent, never exposes raw UUID
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _raw_machine_id() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.check_output(
                ["wmic", "csproduct", "get", "UUID"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode(errors="replace")
            # Output: "UUID\nXXXX-XXXX-...\n"
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if len(lines) >= 2:
                return lines[1]

        elif system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode(errors="replace")
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[-2]

        else:  # Linux / other
            for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                p = Path(path)
                if p.exists():
                    mid = p.read_text().strip()
                    if mid:
                        return mid

    except Exception:
        pass

    # Fallback — not perfect but deterministic per machine
    import socket
    return f"{socket.gethostname()}-{platform.node()}-{platform.machine()}"


# ---------------------------------------------------------------------------
# SQLite cache helpers
# ---------------------------------------------------------------------------

def _ensure_license_table(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS license_cache (
            key_hash    TEXT PRIMARY KEY,
            key         TEXT    DEFAULT '',
            valid       INTEGER NOT NULL,
            plan        TEXT    DEFAULT '',
            checked_at  TEXT    NOT NULL,
            cached_at   TEXT    DEFAULT '',
            expires_at  TEXT    NOT NULL
        );
    """)
    # Migrate older caches that predate the key/cached_at columns.
    for col, ddl in (("key", "ALTER TABLE license_cache ADD COLUMN key TEXT DEFAULT ''"),
                     ("cached_at", "ALTER TABLE license_cache ADD COLUMN cached_at TEXT DEFAULT ''")):
        try:
            conn.execute(ddl)
        except Exception:
            pass  # column already exists
    conn.commit()


def _key_hash(license_key: str) -> str:
    return hashlib.sha256(license_key.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# FIX 8 — local kv store (license_status, valid_until, server_session_token)
# ---------------------------------------------------------------------------

def get_local_db_path() -> str:
    """Absolute path to the local SQLite DB used for cache + kv state."""
    return str(DB_PATH)


def _ensure_kv_table(conn: sqlite3.Connection):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()


def get_kv(key: str) -> str | None:
    """Read a value from the local kv store. None if missing/unreadable."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        _ensure_kv_table(conn)
        row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def set_kv(key: str, value: str):
    """Write a value to the local kv store (upsert)."""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        _ensure_kv_table(conn)
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[license] set_kv failed: {e}")


def cache_validation(key: str, result: bool,
                     plan: str = "", ttl_days: int = DEFAULT_TTL_DAYS):
    """
    Store a validation result in SQLite.
    Overwrites any previous entry for this key.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_license_table(conn)
    now     = datetime.utcnow()
    expires = now + timedelta(days=ttl_days)
    conn.execute(
        "INSERT OR REPLACE INTO license_cache "
        "(key_hash, key, valid, plan, checked_at, cached_at, expires_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            _key_hash(key),
            key if result else "",   # only retain the raw key for valid licenses
            1 if result else 0,
            plan,
            now.isoformat(),
            now.isoformat(),
            expires.isoformat(),
        )
    )
    conn.commit()
    conn.close()


def _get_cached(key: str) -> dict | None:
    """
    Return cached validation if it exists and has not expired.
    Returns None if not cached or expired.
    """
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        _ensure_license_table(conn)
        row = conn.execute(
            "SELECT * FROM license_cache WHERE key_hash = ?",
            (_key_hash(key),)
        ).fetchone()
        conn.close()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > expires:
            return None   # expired — needs re-check
        return {
            "valid":      bool(row["valid"]),
            "plan":       row["plan"],
            "checked_at": row["checked_at"],
            "expires_at": row["expires_at"],
            "source":     "cache",
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SkillGod API validation
# ---------------------------------------------------------------------------

def validate_key(license_key: str, machine_id: str) -> dict:
    """
    Validate a license key against the LemonSqueezy API.

    Returns:
        {
            "valid":     bool,
            "plan":      str,   e.g. "pro" / "team" / ""
            "error":     str,   empty string if valid
            "source":    str,   "api" | "cache" | "offline"
        }

    If the API call fails (network error), falls back to cached result.
    If no cache, returns offline grace (valid=True, source="offline")
    so the dev's workflow is never blocked.
    """
    # 1. Try live API first
    try:
        result = _call_skillgod_api(license_key, machine_id)
        # FIX 8 — recheck daily (ttl_days=1) instead of riding a 30-day cache,
        # so an expired/cancelled subscription is caught within a day even if
        # the user stays online. Offline grace still comes from the cache row.
        cache_validation(
            license_key,
            result["valid"],
            plan=result.get("plan", ""),
            ttl_days=1,
        )
        # Persist hard-expiry + tier + decryption-token state to the kv store.
        if result["valid"]:
            set_kv("license_status", "pro")
            if result.get("valid_until"):
                set_kv("valid_until", str(result["valid_until"]))
            if result.get("server_session_token"):
                set_kv("server_session_token", result["server_session_token"])
        else:
            set_kv("license_status", "free")
        return result
    except Exception as e:
        api_error = str(e)

    # 2. Fall back to SQLite cache
    cached = _get_cached(license_key)
    if cached:
        cached["source"] = "cache"
        cached["error"]  = f"Offline — using cached result (expires {cached['expires_at'][:10]})"
        return cached

    # 3. No cache AND API unreachable.
    #    Offline grace only ever applies to a key that validated successfully at
    #    least once (handled in step 2). With no prior successful validation we
    #    must FAIL CLOSED — otherwise anyone could unlock Pro simply by blocking
    #    the API on first run. A legitimate Pro user always has a cache by now.
    return {
        "valid":  False,
        "plan":   "",
        "error":  f"Could not verify license ({api_error}) and no prior validation "
                  f"on this machine. Connect once to activate Pro.",
        "source": "offline",
    }


def _call_skillgod_api(license_key: str, machine_id: str) -> dict:
    """
    POST to SkillGod Railway API /v1/license/validate.
    """
    import urllib.parse
    payload = json.dumps({
        "key":        license_key,
        "machine_id": machine_id,
    }).encode()

    url = f"{SKILLGOD_API_URL}/v1/license/validate"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Accept":       "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.fp else {}
        raise RuntimeError(f"SkillGod API {e.code}: {body.get('detail', str(e))}")

    return {
        "valid":      body.get("valid", False),
        "plan":       body.get("plan", ""),
        "error":      body.get("error", "") if not body.get("valid") else "",
        # FIX 8 — carry the subscription expiry (current_end, NOT cancel_at) and
        # the rotating server session token so the CLI can enforce hard expiry
        # and derive the vault decryption key. Both may be absent on older
        # server builds; callers treat missing valid_until as "no hard ceiling".
        "valid_until":           body.get("valid_until", "") or body.get("expires", ""),
        "server_session_token":  body.get("server_session_token", ""),
        "source":     "api",
    }


# ---------------------------------------------------------------------------
# Main entry point (used by sync.go via runPython)
# ---------------------------------------------------------------------------

def check_license(license_key: str) -> dict:
    """
    Main entry point called by sg sync --key.

    Returns dict with keys: valid, plan, error, source
    Prints human-readable status to stdout.
    """
    machine_id = get_machine_id()
    result     = validate_key(license_key, machine_id)

    if result["valid"]:
        plan = result.get("plan", "pro") or "pro"
        src  = result["source"]
        print(f"LICENSE_VALID:{plan}:{src}")
    else:
        err = result.get("error", "Invalid key")
        print(f"LICENSE_INVALID:{err}")

    return result


# ---------------------------------------------------------------------------
# Pro access check (license OR coupon)
# ---------------------------------------------------------------------------

def get_install_id() -> str:
    """
    Stable anonymous install identifier (persisted). Used for server-side
    tracking and referral lookups. Generated once, never reveals hardware.
    """
    path = DB_PATH.parent / "install_id"
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        import uuid
        new_id = uuid.uuid4().hex
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
        return new_id
    except Exception:
        # Deterministic fallback so callers always get something stable.
        return "inst-" + get_machine_id()[:24]


def save_key(license_key: str) -> None:
    """Persist the license key to the local kv store."""
    set_kv("license_key", license_key)


def get_cached_key() -> str:
    """Return the stored license key (kv first, then valid cache), or empty string."""
    kv_key = get_kv("license_key")
    if kv_key:
        return kv_key
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        _ensure_license_table(conn)
        row = conn.execute(
            "SELECT key FROM license_cache WHERE valid=1 AND key != '' "
            "AND expires_at > ? ORDER BY cached_at DESC LIMIT 1",
            (datetime.utcnow().isoformat(),)
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def check_cache(key: str) -> dict | None:
    """Public wrapper over the private _get_cached() validation-cache lookup."""
    return _get_cached(key)


def is_pro_active(machine_id: str = "") -> dict:
    """
    FIX 8 — strict Pro-access check. Returns a dict (was a bare bool):

        {"active": True,  "plan": "pro", "days_left": N}
        {"active": True,  "plan": "pro", "days_left": N, "warning": "expires_soon"}
        {"active": False, "reason": "expired"|"no_license"|"offline_no_cache"}

    Hard expiry: even if a cache row still looks valid, once valid_until has
    passed we treat Pro as expired immediately and never serve it again without
    a fresh online check. Coupon redemptions are honoured as a fallback.

    machine_id is optional; when omitted it is resolved via get_machine_id().
    Never raises — any unexpected error fails closed to free tier.
    """
    try:
        if not machine_id:
            machine_id = get_machine_id()
        return _is_pro_active_impl(machine_id)
    except Exception:
        return {"active": False, "reason": "error"}


def _is_pro_active_impl(machine_id: str) -> dict:
    """Internal Pro-access resolver (see is_pro_active)."""
    # Step 1 — hard-expiry ceiling from the kv store. If we have recorded a
    # valid_until and it's in the past, downgrade now regardless of cache TTL.
    vu = get_kv("valid_until")
    if vu:
        try:
            if datetime.fromisoformat(vu.replace("Z", "")) < datetime.utcnow():
                set_kv("license_status", "free")
                return {"active": False, "reason": "expired"}
        except Exception:
            pass

    # Step 2 — paid license via cached key (daily online recheck inside).
    cached_key = get_cached_key()
    if cached_key:
        result = validate_key(cached_key, machine_id)
        if result.get("valid"):
            plan = result.get("plan", "pro") or "pro"
            out  = {"active": True, "plan": plan, "days_left": None}
            vu2  = result.get("valid_until") or get_kv("valid_until")
            if vu2:
                try:
                    days_left = (datetime.fromisoformat(str(vu2).replace("Z", ""))
                                 - datetime.utcnow()).days
                    out["days_left"] = days_left
                    if 0 < days_left <= 7:
                        out["warning"] = "expires_soon"
                except Exception:
                    pass
            set_kv("license_status", "pro")
            return out
        # Cached key exists but no longer valid (and we couldn't reach the API
        # with a usable cache) — fall through to coupon, then fail closed.
        if result.get("source") == "offline":
            return {"active": False, "reason": "offline_no_cache"}

    # Step 3 — coupon redemption fallback.
    try:
        from coupons import is_valid_redemption
        coupon = is_valid_redemption(machine_id)
        if coupon.get("active", False):
            set_kv("license_status", "pro")
            return {"active": True, "plan": "pro", "days_left": None}
    except Exception:
        pass

    set_kv("license_status", "free")
    return {"active": False, "reason": "no_license"}


def downgrade_to_free() -> bool:
    """
    FIX 8 — called when the license is detected as expired. Removes Pro skills
    from the local SQLite skill index (keeps instincts + vault_free skills) and
    marks license_status='free' in the kv store. Does NOT delete the encrypted
    .sg files on disk — a later renewal just re-indexes them.
    """
    db_path = get_local_db_path()
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                DELETE FROM skills
                WHERE source_path NOT LIKE '%vault_free%'
                  AND type != 'instinct'
            """)
        except Exception:
            # skills table may not exist yet on a fresh install — non-fatal.
            pass
        _ensure_kv_table(conn)
        conn.execute(
            "INSERT INTO kv (key, value) VALUES ('license_status', 'free') "
            "ON CONFLICT(key) DO UPDATE SET value = 'free'"
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[license] downgrade_to_free error: {e}")
        return False


def downgrade() -> None:
    """Mark the local license cache as free tier (clears Pro state)."""
    try:
        downgrade_to_free()
    except Exception as e:
        print(f"[license] downgrade error: {e}")


def reactivate_pro(machine_id: str = "", new_valid_until: str = "") -> bool:
    """
    FIX 8 — called when validate_online() succeeds again after a free-tier
    downgrade (user renewed). Flips kv back to 'pro' and rebuilds the full Pro
    skill index from the encrypted vault. The .sg files are still on disk; they
    just need the new server_session_token (already cached) to decrypt.
    """
    try:
        set_kv("license_status", "pro")
        if new_valid_until:
            set_kv("valid_until", new_valid_until)
        try:
            from skills import rebuild_index
            rebuild_index()
        except Exception as e:
            print(f"[license] reactivate_pro rebuild_index warning: {e}")
        return True
    except Exception as e:
        print(f"[license] reactivate_pro error: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import urllib.parse   # ensure imported for CLI use too

    cmd = sys.argv[1] if len(sys.argv) > 1 else "machine-id"

    if cmd == "machine-id":
        mid = get_machine_id()
        print(f"Machine ID : {mid}")
        print(f"Raw ID     : {_raw_machine_id()}")

    elif cmd == "validate" and len(sys.argv) >= 3:
        key    = sys.argv[2]
        mid    = get_machine_id()
        result = check_license(key)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "cache-status" and len(sys.argv) >= 3:
        key    = sys.argv[2]
        cached = _get_cached(key)
        if cached:
            print(json.dumps(cached, indent=2))
        else:
            print("No cached entry (or expired)")

    else:
        print("Usage:")
        print("  python engine/license.py machine-id")
        print("  python engine/license.py validate <LICENSE_KEY>")
        print("  python engine/license.py cache-status <LICENSE_KEY>")
