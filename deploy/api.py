"""
SkillGod API — Railway deployment.

Handles:
  - Razorpay webhook  →  generate license key  →  email to customer
  - License key validation for `sg sync --key`
  - User tracking (signups, installs, syncs, referrals)
  - Admin dashboard endpoint

Environment variables (set in Railway dashboard):
  RAZORPAY_KEY_ID
  RAZORPAY_KEY_SECRET
  RAZORPAY_WEBHOOK_SECRET
  SMTP_HOST          (e.g. smtp.gmail.com)
  SMTP_PORT          (587)
  SMTP_USER          (hello@skillgod.dev)
  SMTP_PASS
  DATABASE_URL       (Railway injects this automatically)
  ADMIN_KEY          (any secret string — protects /admin/* endpoints)
"""

import hashlib
import hmac
import json
import os
import secrets
import smtplib
import string
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Request, Header
from pydantic import BaseModel

app = FastAPI(
    title="SkillGod API",
    version="1.1.0",
    description="License management and signal aggregation for SkillGod Pro",
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def _ensure_schema():
    """Create all tables. Called at startup — safe to run multiple times."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute("""
            -- Core license table
            CREATE TABLE IF NOT EXISTS licenses (
                key                      TEXT PRIMARY KEY,
                razorpay_subscription_id TEXT,
                razorpay_payment_id      TEXT,
                email                    TEXT NOT NULL,
                plan                     TEXT NOT NULL DEFAULT 'pro',
                created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active                   BOOLEAN NOT NULL DEFAULT TRUE,
                machine_id               TEXT DEFAULT ''
            );

            -- User profiles (one row per email)
            CREATE TABLE IF NOT EXISTS users (
                email          TEXT PRIMARY KEY,
                plan           TEXT NOT NULL DEFAULT 'free',
                status         TEXT NOT NULL DEFAULT 'active',
                referral_code  TEXT UNIQUE,
                referred_by    TEXT,
                first_seen     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_active    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                install_count  INTEGER NOT NULL DEFAULT 0,
                sync_count     INTEGER NOT NULL DEFAULT 0,
                paid_at        TIMESTAMPTZ,
                cancelled_at   TIMESTAMPTZ
            );

            -- Usage events: installs, syncs, skill_used, etc.
            CREATE TABLE IF NOT EXISTS events (
                id          SERIAL PRIMARY KEY,
                email       TEXT,
                machine_id  TEXT,
                event_type  TEXT NOT NULL,
                plan        TEXT DEFAULT '',
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS events_email_idx      ON events(email);
            CREATE INDEX IF NOT EXISTS events_type_idx       ON events(event_type);
            CREATE INDEX IF NOT EXISTS events_created_at_idx ON events(created_at DESC);

            -- Referral tracking
            CREATE TABLE IF NOT EXISTS referrals (
                id              SERIAL PRIMARY KEY,
                referrer_email  TEXT NOT NULL,
                referee_email   TEXT NOT NULL UNIQUE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                converted       BOOLEAN NOT NULL DEFAULT FALSE,
                converted_at    TIMESTAMPTZ,
                reward_given    BOOLEAN NOT NULL DEFAULT FALSE,
                reward_given_at TIMESTAMPTZ
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[startup] schema ready")
    except Exception as e:
        print(f"[startup] schema warning: {e}")


@app.on_event("startup")
def startup():
    _ensure_schema()


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def _upsert_user(email: str, plan: str = "free",
                 referred_by: str = "", paid: bool = False):
    """Create or update a user row. Safe to call repeatedly."""
    conn = _get_db()
    cur  = conn.cursor()
    # Generate a unique referral code for new users
    code = "SG" + secrets.token_urlsafe(6).upper()[:8]
    now  = "NOW()"
    cur.execute(
        """
        INSERT INTO users (email, plan, referral_code, referred_by, first_seen, last_active, paid_at)
        VALUES (%s, %s, %s, NULLIF(%s,''), NOW(), NOW(), %s)
        ON CONFLICT (email) DO UPDATE SET
            plan        = EXCLUDED.plan,
            last_active = NOW(),
            paid_at     = COALESCE(users.paid_at, EXCLUDED.paid_at)
        """,
        (email, plan, code, referred_by, "NOW()" if paid else None)
    )
    conn.commit()
    cur.close()
    conn.close()


def _track_event(email: str, event_type: str, machine_id: str = "",
                 plan: str = "", metadata: dict = None):
    """Append a usage event. Fire-and-forget, never raises."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO events (email, machine_id, event_type, plan, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (email or None, machine_id or None, event_type, plan,
             json.dumps(metadata or {}))
        )
        # Increment counters on users table
        if email and event_type == "install":
            cur.execute(
                "UPDATE users SET install_count = install_count + 1, last_active = NOW() WHERE email = %s",
                (email,)
            )
        elif email and event_type == "sync":
            cur.execute(
                "UPDATE users SET sync_count = sync_count + 1, last_active = NOW() WHERE email = %s",
                (email,)
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[track_event] {e}")


def _handle_referral(referee_email: str, referrer_code: str):
    """
    Record referral when a new user signs up with a referral code.
    Looks up referrer by referral_code, inserts into referrals table.
    """
    if not referrer_code:
        return
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute("SELECT email FROM users WHERE referral_code = %s", (referrer_code,))
        row = cur.fetchone()
        if row:
            referrer_email = row["email"]
            cur.execute(
                """
                INSERT INTO referrals (referrer_email, referee_email, created_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (referee_email) DO NOTHING
                """,
                (referrer_email, referee_email)
            )
            conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[referral] {e}")


def _convert_referral(referee_email: str):
    """
    Called when a referred user converts to paid.
    Marks referral converted, flags reward_given = False (you send reward manually or via email).
    """
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE referrals SET converted = TRUE, converted_at = NOW()
            WHERE referee_email = %s AND converted = FALSE
            """,
            (referee_email,)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[referral convert] {e}")


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

def _check_admin(x_admin_key: str):
    """Raise 403 if admin key is wrong."""
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def _generate_key() -> str:
    """Generate a license key in SG-XXXX-XXXX-XXXX-XXXX format."""
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
    return "SG-" + "-".join(parts)


def _store_key(key: str, email: str, plan: str,
               subscription_id: str = "", payment_id: str = ""):
    conn = _get_db()
    cur  = conn.cursor()
    cur.execute(
        """
        INSERT INTO licenses (key, razorpay_subscription_id, razorpay_payment_id,
                              email, plan, created_at, active)
        VALUES (%s, %s, %s, %s, %s, NOW(), TRUE)
        ON CONFLICT (key) DO NOTHING
        """,
        (key, subscription_id, payment_id, email, plan)
    )
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_key_email(to_email: str, license_key: str, plan: str):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER", "hello@skillgod.dev")
    pw   = os.environ.get("SMTP_PASS", "")

    subject = "Your SkillGod license key"
    body_text = f"""
Welcome to SkillGod Pro!

Your license key:

  {license_key}

Activate it with:

  sg sync --key {license_key}

This downloads the full vault ({plan} plan) and activates all 1,944 skills.

Keep this key safe — it is tied to your subscription.
If you have any issues, reply to this email.

— SkillGod
https://skillgod.dev
"""
    body_html = f"""
<div style="font-family:monospace;max-width:560px;margin:0 auto;padding:32px">
  <h2 style="font-family:sans-serif">Your SkillGod license key</h2>
  <div style="background:#f5f2eb;border:2px solid #1a1814;padding:20px;margin:24px 0;text-align:center">
    <code style="font-size:22px;font-weight:bold;letter-spacing:3px">{license_key}</code>
  </div>
  <p style="font-family:sans-serif">Activate with:</p>
  <pre style="background:#11110f;color:#f5c842;padding:16px;border-radius:4px">sg sync --key {license_key}</pre>
  <p style="font-family:sans-serif;color:#8a8680;font-size:13px">
    This downloads the full vault and activates your {plan} plan.<br>
    Keep this key safe — it is tied to your subscription.
  </p>
  <hr style="border:none;border-top:1px solid #d4cfc5;margin:24px 0">
  <p style="font-family:sans-serif;font-size:12px;color:#8a8680">
    Reply to this email for support · <a href="https://skillgod.dev">skillgod.dev</a>
  </p>
</div>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(host, port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, pw)
            smtp.sendmail(user, to_email, msg.as_string())
        print(f"[email] sent key to {to_email[:4]}***")
    except Exception as e:
        print(f"[email] ERROR: {e}")
        raise


# ---------------------------------------------------------------------------
# Razorpay webhook verification
# ---------------------------------------------------------------------------

def _verify_razorpay_signature(body: bytes, signature: str) -> bool:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        return False
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/v1/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """
    Handles Razorpay payment/subscription events.
    Fires when:
      - payment.captured    (one-time or first subscription payment)
      - subscription.charged (recurring renewal)
    """
    body      = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not _verify_razorpay_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("event", "")
    payload    = event.get("payload", {})

    # One-time payment captured
    if event_type == "payment.captured":
        payment = payload.get("payment", {}).get("entity", {})
        email   = payment.get("email", "")
        plan    = "early_adopter" if payment.get("amount", 0) <= 70000 else "pro"
        sub_id  = payment.get("subscription_id", "")
        pay_id  = payment.get("id", "")

        if email:
            key = _generate_key()
            _store_key(key, email, plan, sub_id, pay_id)
            _send_key_email(email, key, plan)
            _upsert_user(email, plan=plan, paid=True)
            _convert_referral(email)
            _track_event(email, "payment_captured", plan=plan,
                         metadata={"payment_id": pay_id, "subscription_id": sub_id})
            print(f"[webhook] key issued for {email[:4]}*** plan={plan}")

    # Subscription renewal — keep existing key active (no new key)
    elif event_type == "subscription.charged":
        sub   = payload.get("subscription", {}).get("entity", {})
        sub_id = sub.get("id", "")
        if sub_id:
            conn = _get_db()
            cur  = conn.cursor()
            cur.execute(
                "UPDATE licenses SET active = TRUE WHERE razorpay_subscription_id = %s",
                (sub_id,)
            )
            conn.commit()
            cur.close()
            conn.close()

    # Subscription cancelled
    elif event_type in ("subscription.cancelled", "subscription.halted"):
        sub    = payload.get("subscription", {}).get("entity", {})
        sub_id = sub.get("id", "")
        if sub_id:
            conn = _get_db()
            cur  = conn.cursor()
            cur.execute(
                "UPDATE licenses SET active = FALSE WHERE razorpay_subscription_id = %s",
                (sub_id,)
            )
            conn.commit()
            cur.close()
            conn.close()

    return {"received": True}


# ---------------------------------------------------------------------------
# License validation (called by engine/license.py via sg sync --key)
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    key:        str
    machine_id: str = ""


@app.post("/v1/license/validate")
def validate_license(req: ValidateRequest):
    """
    Validates a SkillGod license key.
    Returns: { valid, plan, error }
    """
    if not req.key or not req.key.startswith("SG-"):
        return {"valid": False, "plan": "", "error": "Invalid key format"}

    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            "SELECT plan, active, email FROM licenses WHERE key = %s",
            (req.key,)
        )
        row = cur.fetchone()

        # Optionally record machine_id on first validation
        if row and req.machine_id:
            cur.execute(
                "UPDATE licenses SET machine_id = %s WHERE key = %s AND machine_id = ''",
                (req.machine_id, req.key)
            )
            conn.commit()

        cur.close()
        conn.close()

        if not row:
            return {"valid": False, "plan": "", "error": "Key not found"}
        if not row["active"]:
            return {"valid": False, "plan": row["plan"], "error": "Subscription cancelled"}
        return {"valid": True, "plan": row["plan"], "error": ""}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.1.0"}


# ---------------------------------------------------------------------------
# Tracking — called by sg init and sg sync
# ---------------------------------------------------------------------------

class TrackPayload(BaseModel):
    event:      str        # install | sync | skill_used | session_start
    machine_id: str = ""
    email:      str = ""
    plan:       str = ""
    referral:   str = ""   # referral code used at install time
    metadata:   dict = {}


@app.post("/v1/track")
def track(payload: TrackPayload):
    """
    Anonymous-friendly event tracking.
    - install: fired by `sg init` (no email required)
    - sync:    fired by `sg sync --key` (has email from license lookup)
    """
    if payload.email:
        _upsert_user(payload.email, plan=payload.plan or "free",
                     referred_by=payload.referral)
        if payload.referral:
            _handle_referral(payload.email, payload.referral)

    _track_event(
        email=payload.email,
        event_type=payload.event,
        machine_id=payload.machine_id,
        plan=payload.plan,
        metadata=payload.metadata,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin endpoints (protected by ADMIN_KEY header)
# ---------------------------------------------------------------------------

@app.get("/admin/stats")
def admin_stats(x_admin_key: str = Header(default="")):
    """
    High-level dashboard numbers.
    Call with: curl -H 'x-admin-key: YOUR_KEY' https://api.skillgod.dev/admin/stats
    """
    _check_admin(x_admin_key)
    conn = _get_db()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS n FROM users WHERE plan != 'free'")
    paid_users = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM users WHERE plan = 'free'")
    free_users = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM users WHERE plan = 'early_adopter'")
    early_adopters = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM licenses WHERE active = TRUE")
    active_licenses = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM referrals WHERE converted = TRUE")
    converted_referrals = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM referrals WHERE reward_given = FALSE AND converted = TRUE")
    pending_rewards = cur.fetchone()["n"]

    cur.execute("""
        SELECT event_type, COUNT(*) AS n
        FROM events
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY event_type
        ORDER BY n DESC
    """)
    events_7d = {r["event_type"]: r["n"] for r in cur.fetchall()}

    cur.execute("""
        SELECT DATE(created_at) AS day, COUNT(*) AS installs
        FROM events WHERE event_type = 'install'
        AND created_at > NOW() - INTERVAL '14 days'
        GROUP BY day ORDER BY day DESC
    """)
    installs_by_day = [{"day": str(r["day"]), "installs": r["installs"]}
                       for r in cur.fetchall()]

    cur.close()
    conn.close()

    mrr_7 = early_adopters * 7
    mrr_10 = (paid_users - early_adopters) * 10

    return {
        "users": {
            "total":          total_users,
            "paid":           paid_users,
            "free":           free_users,
            "early_adopters": early_adopters,
        },
        "revenue": {
            "active_licenses":    active_licenses,
            "mrr_estimate_usd":   mrr_7 + mrr_10,
            "early_adopter_slots_left": max(0, 200 - early_adopters),
        },
        "referrals": {
            "converted":      converted_referrals,
            "pending_rewards": pending_rewards,
        },
        "activity_7d":   events_7d,
        "installs_14d":  installs_by_day,
    }


@app.get("/admin/users")
def admin_users(
    limit: int = 50,
    offset: int = 0,
    plan: str = "",
    x_admin_key: str = Header(default=""),
):
    """List all users. Filter by plan= (free/pro/early_adopter)."""
    _check_admin(x_admin_key)
    conn = _get_db()
    cur  = conn.cursor()

    if plan:
        cur.execute(
            """
            SELECT email, plan, status, referral_code, referred_by,
                   first_seen, last_active, install_count, sync_count, paid_at
            FROM users WHERE plan = %s
            ORDER BY first_seen DESC LIMIT %s OFFSET %s
            """,
            (plan, limit, offset)
        )
    else:
        cur.execute(
            """
            SELECT email, plan, status, referral_code, referred_by,
                   first_seen, last_active, install_count, sync_count, paid_at
            FROM users ORDER BY first_seen DESC LIMIT %s OFFSET %s
            """,
            (limit, offset)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"users": [dict(r) for r in rows], "count": len(rows)}


@app.get("/admin/referrals")
def admin_referrals(
    unconverted_only: bool = False,
    x_admin_key: str = Header(default=""),
):
    """List referrals. Use unconverted_only=true to see pending conversions."""
    _check_admin(x_admin_key)
    conn = _get_db()
    cur  = conn.cursor()
    if unconverted_only:
        cur.execute(
            "SELECT * FROM referrals WHERE converted = FALSE ORDER BY created_at DESC"
        )
    else:
        cur.execute("SELECT * FROM referrals ORDER BY created_at DESC LIMIT 200")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"referrals": [dict(r) for r in rows]}


@app.post("/admin/reward/{referral_id}")
def mark_reward_given(
    referral_id: int,
    x_admin_key: str = Header(default=""),
):
    """Mark a referral reward as given (1 free month sent)."""
    _check_admin(x_admin_key)
    conn = _get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE referrals SET reward_given = TRUE, reward_given_at = NOW() WHERE id = %s",
        (referral_id,)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SignalPayload(BaseModel):
    signals:    list[dict[str, Any]] = []
    machine_id: str = ""


@app.post("/v1/signals")
def receive_signals(payload: SignalPayload):
    return {"received": len(payload.signals)}
