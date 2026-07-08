"""HEALTH ALERTING CHANNEL (phase-7 item, user 2026-07-07). Dashboard-only alerts meant nobody
hears the server die at 3am — this pushes them OUT.

Channels (all optional, all env-ready — the provider pattern: paste a URL, it works):
  ALERT_WEBHOOK_URL   any JSON webhook — Discord ("content"), Slack ("text") and ntfy.sh-style
                      endpoints are auto-detected by URL; generic endpoints get {"text": ...}.
  file feed           BOT/data/alerts.jsonl always (the dashboard + post-mortems read this).
  audit               every alert also lands in the audit trail.

    from bot.alerts import alert
    alert("scan loop dead 15m", level="critical")

Levels: info · warn · critical. Throttled: the same (level, first 60 chars) fires at most once
per THROTTLE_MIN minutes so a flapping check can't spam the channel."""
from __future__ import annotations

import json
import time
from pathlib import Path

from bot.config import BOT_ROOT, _get

FEED = BOT_ROOT / "data" / "alerts.jsonl"
THROTTLE_MIN = 30
_last: dict = {}


def _post_webhook(msg: str, level: str) -> bool:
    url = (_get("ALERT_WEBHOOK_URL") or "").strip()
    if not url or "PUT_YOUR" in url:
        return False
    try:
        import requests
        text = f"[{level.upper()}] HIGHSTRIKE — {msg}"
        if "discord" in url:
            body = {"content": text[:1900]}
        elif "slack" in url or "hooks." in url:
            body = {"text": text}
        elif "ntfy" in url:
            requests.post(url, data=text.encode(), timeout=5)
            return True
        else:
            body = {"text": text}
        requests.post(url, json=body, timeout=5)
        return True
    except Exception:
        return False


def alert(msg: str, level: str = "warn", source: str = "bot") -> dict:
    key = (level, msg[:60])
    now = time.time()
    if now - _last.get(key, 0) < THROTTLE_MIN * 60:
        return {"throttled": True}
    _last[key] = now
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
           "level": level, "source": source, "msg": msg}
    try:
        FEED.parent.mkdir(parents=True, exist_ok=True)
        with FEED.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    rec["pushed"] = _post_webhook(msg, level)
    try:
        from bot.audit import log as _audit
        _audit("alert", level=level, source=source, msg=msg[:200], pushed=rec["pushed"])
    except Exception:
        pass
    return rec


def recent(n: int = 30) -> list[dict]:
    try:
        lines = FEED.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines][::-1]
    except Exception:
        return []


if __name__ == "__main__":   # self-test: feed write + throttle (no webhook without a URL)
    r1 = alert("self-test alert", "info", "selftest")
    r2 = alert("self-test alert", "info", "selftest")
    assert not r1.get("throttled") and r2.get("throttled"), (r1, r2)
    assert recent(3) and recent(3)[0]["msg"] == "self-test alert"
    print(f"alerts OK — feed {FEED.name}, webhook {'SET' if r1.get('pushed') else 'not set (env-ready)'}")
