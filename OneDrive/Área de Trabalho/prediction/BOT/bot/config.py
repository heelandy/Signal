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
    mode: str

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
    mode=(_get("BOT_MODE", "replay") or "replay").lower(),
)
