"""
SkillGod API — Railway deployment.

Handles:
  - Razorpay webhook  →  generate license key  →  email to customer
  - License key validation for `sg sync --key`
  - Signal aggregation (v1.1)

Environment variables (set in Railway dashboard):
  RAZORPAY_KEY_ID
  RAZORPAY_KEY_SECRET
  RAZORPAY_WEBHOOK_SECRET
  SMTP_HOST          (e.g. smtp.gmail.com)
  SMTP_PORT          (587)
  SMTP_USER          (hello@skillgod.dev)
  SMTP_PASS
  DATABASE_URL       (Railway injects this automatically)
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
from fastapi import FastAPI, HTTPException, Request
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
    """Create tables if they don't exist. Called at startup."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                key                     TEXT PRIMARY KEY,
                razorpay_subscription_id TEXT,
                razorpay_payment_id      TEXT,
                email                   TEXT NOT NULL,
                plan                    TEXT NOT NULL DEFAULT 'pro',
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active                  BOOLEAN NOT NULL DEFAULT TRUE,
                machine_id              TEXT DEFAULT ''
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[startup] schema warning: {e}")


@app.on_event("startup")
def startup():
    _ensure_schema()


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
# Signals (future — activate when Railway Postgres has enough data)
# ---------------------------------------------------------------------------

class SignalPayload(BaseModel):
    signals:    list[dict[str, Any]] = []
    machine_id: str = ""


@app.post("/v1/signals")
def receive_signals(payload: SignalPayload):
    # v1.2: store in postgres for aggregate analytics
    return {"received": len(payload.signals)}
