"""
Gmail OAuth + send service.
Tokens stored encrypted in SQLite (gmail_tokens table).
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from app.config import settings
from app import database as db

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "openid", "email"]
AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL  = "https://oauth2.googleapis.com/token"
INFO_URL   = "https://www.googleapis.com/oauth2/v2/userinfo"


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret_key.encode()).digest())
    return Fernet(key)


def _sign(payload_b64: str) -> str:
    digest = hmac.new(settings.app_secret_key.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def create_state(telegram_id: int) -> str:
    payload = json.dumps({"tid": telegram_id, "exp": int(time.time()) + 900})
    b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{b64}.{_sign(b64)}"


def verify_state(state: str) -> int:
    b64, sig = state.split(".", 1)
    assert hmac.compare_digest(sig, _sign(b64)), "Bad signature"
    padded = b64 + "=" * (-len(b64) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded))
    assert data["exp"] > int(time.time()), "State expired"
    return int(data["tid"])


def get_auth_url(telegram_id: int) -> str:
    if not settings.gmail_client_id:
        raise ValueError("GMAIL_CLIENT_ID not configured")
    return f"{AUTH_URL}?{urlencode({'client_id': settings.gmail_client_id, 'redirect_uri': settings.oauth_redirect_url, 'response_type': 'code', 'scope': ' '.join(SCOPES), 'access_type': 'offline', 'prompt': 'consent', 'state': create_state(telegram_id)})}"


async def complete_oauth(code: str, state: str) -> tuple[int, str]:
    telegram_id = verify_state(state)
    async with httpx.AsyncClient(timeout=30) as client:
        tr = await client.post(TOKEN_URL, data={
            "code": code, "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "redirect_uri": settings.oauth_redirect_url,
            "grant_type": "authorization_code",
        })
        tr.raise_for_status()
        td = tr.json()
        access_token = td["access_token"]
        refresh_token = td.get("refresh_token", "")

        ir = await client.get(INFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        email = ir.json().get("email", "unknown") if ir.status_code < 400 else "unknown"

    enc = _fernet().encrypt(refresh_token.encode()).decode()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO gmail_tokens(telegram_id,sender_email,refresh_token_enc) VALUES(?,?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET sender_email=excluded.sender_email, refresh_token_enc=excluded.refresh_token_enc",
            (telegram_id, email, enc),
        )
    return telegram_id, email


def get_status(telegram_id: int) -> tuple[bool, Optional[str]]:
    with db.get_conn() as conn:
        row = conn.execute("SELECT sender_email FROM gmail_tokens WHERE telegram_id=?", (telegram_id,)).fetchone()
    return (True, row["sender_email"]) if row else (False, None)


def disconnect(telegram_id: int) -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM gmail_tokens WHERE telegram_id=?", (telegram_id,))


def send_email(
    telegram_id: int,
    to_email: str,
    subject: str,
    body: str,
    attachment_bytes: bytes | None = None,
    attachment_name: str = "resume.pdf",
) -> tuple[bool, str]:
    """Returns (success, message_id_or_error)."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT sender_email,refresh_token_enc FROM gmail_tokens WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not row:
        return False, "Gmail not connected"

    refresh_token = _fernet().decrypt(row["refresh_token_enc"].encode()).decode()
    sender = row["sender_email"]

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None, refresh_token=refresh_token,
        token_uri=TOKEN_URL, client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret, scopes=SCOPES,
    )
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

    if attachment_bytes:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain"))
        att = MIMEApplication(attachment_bytes, _subtype="pdf")
        att.add_header("Content-Disposition", "attachment", filename=attachment_name)
        msg.attach(att)
    else:
        msg = MIMEText(body)

    msg["to"] = to_email
    msg["from"] = sender
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return True, sent.get("id", "")
