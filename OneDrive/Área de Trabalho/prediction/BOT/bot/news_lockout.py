"""News / event lockout — block new entries around scheduled high-impact releases.

A thin, fail-closed gate the risk layer consults (Evidence "no immediate high-impact event risk").
Feed it event windows (FOMC/CPI/NFP/earnings) and it answers whether a timestamp is inside a
blackout. Designed to plug into the existing macro catalyst engine later as the event source.

    from bot.news_lockout import NewsLockout
    nl = NewsLockout([("2026-06-18T18:00:00Z", 30, 15)])   # (event_utc, mins_before, mins_after)
    nl.blocked("2026-06-18T17:50:00Z")   # -> True
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd


class NewsLockout:
    def __init__(self, events: list[tuple[str, int, int]] | None = None):
        # each event: (utc_iso, minutes_before, minutes_after)
        self.windows = []
        for ts, before, after in (events or []):
            t = pd.Timestamp(ts)
            if t.tz is None:
                t = t.tz_localize("UTC")
            self.windows.append((t - timedelta(minutes=before), t + timedelta(minutes=after)))

    def blocked(self, when: str) -> bool:
        t = pd.Timestamp(when)
        if t.tz is None:
            t = t.tz_localize("UTC")
        return any(lo <= t <= hi for lo, hi in self.windows)

    def reason(self, when: str) -> str | None:
        return "news_blackout" if self.blocked(when) else None


if __name__ == "__main__":
    nl = NewsLockout([("2026-06-18T18:00:00Z", 30, 15)])
    assert nl.blocked("2026-06-18T17:50:00Z")          # 10 min before FOMC
    assert nl.blocked("2026-06-18T18:10:00Z")          # 10 min after
    assert not nl.blocked("2026-06-18T16:00:00Z")      # 2h before -> clear
    assert not nl.blocked("2026-06-18T19:00:00Z")      # 1h after  -> clear
    print("news lockout OK (blocks the +/- window around the release)")
