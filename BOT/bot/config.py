"""Central config + credential loading for the BOT.

Reads BOT/config/.env (a plain KEY=VALUE file, git-ignored) and falls back to the
process environment.  No third-party dependency required.

    from bot.config import settings
    settings.databento_api_key        # str | None
    settings.opra_dir                 # pathlib.Path
    settings.mode                     # "replay" | "paper" | "live" (live is gated)

Going live is intentionally hard: `settings.live_allowed` is False unless BOTH
BOT_MODE=live AND the explicit readiness lock file exists (see BUILD_PLAN.md Phase 8).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# BOT/  (this file is BOT/bot/config.py -> parents[1] == BOT/)
BOT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = BOT_ROOT / "config" / ".env"
LIVE_LOCK_FILE = BOT_ROOT / "config" / "LIVE_APPROVED.lock"  # must be created by hand to ever go live


def _load_env_file(path: Path) -> dict[str, str]:
    """Tiny .env parser: KEY=VALUE per line, # comments, ignores blanks/quotes."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _get(key: str, default: str | None = None) -> str | None:
    # process env wins over the .env file (so CI / shells can override)
    return os.environ.get(key, _ENV.get(key, default))


def read_json(path, default=None):
    """Shared JSON-state reader (review 2026-07-07: six hand-rolled copies across approval/boss/
    evolve/phase78/duel/l2 — one hardened pair now). Missing file -> `default`. A CORRUPT file
    (present but unparseable) also returns the safe default but FIRES A LOUD ALERT (bug hunt W5):
    the old code returned the default SILENTLY for all six consumers, so a torn state file was
    invisible. Missing = clean first run; corrupt = a real fault the operator must see."""
    import json
    from pathlib import Path as _P
    p = _P(path)
    dflt = {} if default is None else default
    if not p.exists():
        return dflt
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        try:
            from bot.alerts import alert
            alert(f"state file CORRUPT: {p.name} ({str(e)[:80]}) — using safe default; inspect the "
                  f"file", level="critical", source="state")
        except Exception:
            pass
        return dflt


def write_json(path, obj) -> None:
    """ATOMIC JSON-state writer: temp file + replace, so a crash mid-write can never leave a
    half-written state file (boss.json / approvals.json / drafts survive power loss)."""
    import json
    from pathlib import Path as _P
    p = _P(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.replace(p)


_ENV = _load_env_file(ENV_FILE)


@dataclass(frozen=True)
class Settings:
    databento_api_key: str | None
    alpaca_key_id: str | None
    alpaca_secret: str | None
    alpaca_paper: bool
    futures_broker: str | None
    opra_dir: Path
    xnas_dir: Path          # QQQ equity MBO (downloaded)
    xnas_spy_dir: Path      # SPY equity MBO — drop the batch here when it arrives
    webhook_token: str | None
    webull_app_key: str | None       # official Webull OpenAPI (developer.webull.com) — market data
    webull_app_secret: str | None
    webull_region: str               # "us" | "hk" | "jp"
    webull_endpoint: str             # api.webull.com (prod) / us-openapi-alb.uat.webullbroker.com (test)
    webull_futures: bool             # US-FUTURES data entitlement (2026-07-07: not yet on this
                                     # account). Flip WEBULL_FUTURES=true in .env the day the
                                     # entitlement lands — providers re-include Webull for
                                     # NQ/ES/GC with ZERO code changes (user: "they just need
                                     # to be ready when I add the API key").
    tradestation_api_key: str | None        # OAuth2 client id (TradeStation developer app)
    tradestation_api_secret: str | None      # OAuth2 client secret
    tradestation_refresh_token: str | None   # long-lived refresh token from the one-time auth-code flow
    tradestation_env: str            # "live" (api.tradestation.com) | "sim" (sim-api.tradestation.com)
    provider_order: str              # CSV data-provider priority, e.g. "alpaca,yahoo,webull" (blank = default)
    mode: str

    def require_tradestation(self) -> tuple[str, str, str]:
        bad = lambda v: (not v) or "PUT_YOUR" in str(v)
        if bad(self.tradestation_api_key) or bad(self.tradestation_api_secret) or bad(self.tradestation_refresh_token):
            raise RuntimeError(
                "TradeStation not configured. Register an app at api.tradestation.com, do the one-time "
                "OAuth (offline_access scope) to get a refresh token, then fill TRADESTATION_API_KEY / "
                "TRADESTATION_API_SECRET / TRADESTATION_REFRESH_TOKEN in BOT/config/.env.")
        return self.tradestation_api_key, self.tradestation_api_secret, self.tradestation_refresh_token

    def require_webull(self) -> tuple[str, str]:
        if (not self.webull_app_key or "PUT_YOUR" in self.webull_app_key
                or not self.webull_app_secret or "PUT_YOUR" in self.webull_app_secret):
            raise RuntimeError(
                "Webull OpenAPI keys are not set. Register at developer.webull.com, then fill "
                "WEBULL_APP_KEY / WEBULL_APP_SECRET in BOT/config/.env.")
        return self.webull_app_key, self.webull_app_secret

    def mbo_dir_for(self, symbol: str) -> Path:
        """Resolve the MBO batch folder by symbol (QQQ vs SPY vs default)."""
        return {"SPY": self.xnas_spy_dir}.get(symbol.upper(), self.xnas_dir)

    @property
    def live_allowed(self) -> bool:
        """Fail-closed live gate: never True unless explicitly opted in AND approved."""
        return self.mode == "live" and LIVE_LOCK_FILE.exists()

    def require_databento(self) -> str:
        if not self.databento_api_key or "PUT_YOUR" in self.databento_api_key:
            raise RuntimeError(
                "DATABENTO_API_KEY is not set. Copy BOT/config/.env.example to "
                "BOT/config/.env and paste your key (Databento Portal -> API keys)."
            )
        return self.databento_api_key

    def require_alpaca(self) -> tuple[str, str]:
        if (not self.alpaca_key_id or "PUT_YOUR" in self.alpaca_key_id
                or not self.alpaca_secret or "PUT_YOUR" in self.alpaca_secret):
            raise RuntimeError(
                "Alpaca keys are not set. Fill ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY "
                "in BOT/config/.env (use your PAPER keys first)."
            )
        return self.alpaca_key_id, self.alpaca_secret


def _bool(v: str | None, default: bool = True) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


settings = Settings(
    databento_api_key=_get("DATABENTO_API_KEY"),
    alpaca_key_id=_get("ALPACA_API_KEY_ID"),
    alpaca_secret=_get("ALPACA_API_SECRET_KEY"),
    alpaca_paper=_bool(_get("ALPACA_PAPER"), True),
    futures_broker=_get("FUTURES_BROKER") or None,
    opra_dir=Path(_get("DATABENTO_OPRA_DIR", "D:/OPRA-20260627-5VQCWWD67U")),
    xnas_dir=Path(_get("DATABENTO_XNAS_DIR", "D:/XNAS-20260627-9JFGFERR4Y")),
    xnas_spy_dir=Path(_get("DATABENTO_XNAS_SPY_DIR", "D:/XNAS-SPY-REPLACE_WHEN_DOWNLOADED")),
    webhook_token=_get("WEBHOOK_TOKEN") or None,
    webull_app_key=_get("WEBULL_APP_KEY") or None,
    webull_app_secret=_get("WEBULL_APP_SECRET") or None,
    webull_region=(_get("WEBULL_REGION", "us") or "us").lower(),
    webull_endpoint=_get("WEBULL_ENDPOINT", "api.webull.com") or "api.webull.com",
    webull_futures=_bool(_get("WEBULL_FUTURES"), False),
    tradestation_api_key=_get("TRADESTATION_API_KEY") or None,
    tradestation_api_secret=_get("TRADESTATION_API_SECRET") or None,
    tradestation_refresh_token=_get("TRADESTATION_REFRESH_TOKEN") or None,
    tradestation_env=(_get("TRADESTATION_ENV", "live") or "live").lower(),
    provider_order=(_get("PROVIDER_ORDER", "") or "").strip(),
    mode=(_get("BOT_MODE", "replay") or "replay").lower(),
)
