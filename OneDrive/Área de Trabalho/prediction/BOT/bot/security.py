"""Security / IAM helpers (SEC-001 / SDNA-001) — token verification + secret redaction.

Signal engine is local + read-mostly, so the surface is small: the webhook token, the optional API
token, and never leaking secrets to logs/UI. This centralises token checks + a redactor.
"""
from __future__ import annotations

import hmac
import re

from bot.config import settings

# patterns that look like secrets (Alpaca keys, db- keys, bearer tokens, long hex)
_SECRET_RX = re.compile(r"(PK[A-Z0-9]{16,}|db-[A-Za-z0-9]{20,}|[A-Za-z0-9/+]{32,}|bearer\s+\S+)", re.I)


def verify_token(token: str | None) -> bool:
    """Constant-time check against the webhook/API shared secret."""
    if not settings.webhook_token or not token:
        return False
    return hmac.compare_digest(str(token), str(settings.webhook_token))


def mask(secret: str | None) -> str:
    if not secret:
        return "—"
    s = str(secret)
    return s[:4] + "…" + s[-3:] if len(s) > 8 else "•••"


def redact(text: str) -> str:
    """Replace anything that looks like a secret before it hits a log or the UI."""
    return _SECRET_RX.sub(lambda m: mask(m.group(0)), str(text))


def keys_status() -> dict:
    """Non-secret view of which credentials are configured (for the dashboard)."""
    db = settings.databento_api_key
    return {
        "alpaca": "set (" + mask(settings.alpaca_key_id) + ", paper)" if (settings.alpaca_key_id and "PUT_YOUR" not in (settings.alpaca_key_id or "PUT")) else "not set",
        "databento": "set" if (db and "PUT_YOUR" not in db) else "not set",
        "webhook_token": "set" if settings.webhook_token else "not set",
    }


if __name__ == "__main__":
    assert verify_token(settings.webhook_token) and not verify_token("wrong")
    log = "submitting with PKKYBTE32O4LLCGZUQ7JI2FVWC and db-abcdefghijklmnopqrstuvwxyz12"
    print("redacted:", redact(log))
    print("mask:", mask("PKKYBTE32O4LLCGZUQ7JI2FVWC"))
    print("keys:", keys_status())
    assert "PKKYBTE32O4LLCGZUQ7JI2FVWC" not in redact(log)
    print("security OK")
