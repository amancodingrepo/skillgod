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
            valid       INTEGER NOT NULL,
            plan        TEXT    DEFAULT '',
            checked_at  TEXT    NOT NULL,
            expires_at  TEXT    NOT NULL
        );
    """)
    conn.commit()


def _key_hash(license_key: str) -> str:
    return hashlib.sha256(license_key.encode()).hexdigest()[:32]


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
        "(key_hash, valid, plan, checked_at, expires_at) VALUES (?,?,?,?,?)",
        (
            _key_hash(key),
            1 if result else 0,
            plan,
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
        cache_validation(
            license_key,
            result["valid"],
            plan=result.get("plan", ""),
            ttl_days=DEFAULT_TTL_DAYS,
        )
        return result
    except Exception as e:
        api_error = str(e)

    # 2. Fall back to SQLite cache
    cached = _get_cached(license_key)
    if cached:
        cached["source"] = "cache"
        cached["error"]  = f"Offline — using cached result (expires {cached['expires_at'][:10]})"
        return cached

    # 3. No cache — offline grace (never block the developer)
    return {
        "valid":  True,
        "plan":   "unknown",
        "error":  f"Could not reach SkillGod API ({api_error}). "
                  f"Offline grace active — validate when online.",
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
        "valid":  body.get("valid", False),
        "plan":   body.get("plan", ""),
        "error":  body.get("error", "") if not body.get("valid") else "",
        "source": "api",
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
