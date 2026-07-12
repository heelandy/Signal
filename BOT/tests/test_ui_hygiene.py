"""UI HYGIENE GATE (P1.4 completion, 2026-07-12): backend free-text (errors, notes, reasons)
must pass through esc() before entering innerHTML — the stored-XSS class stays closed. This is a
grep-gate: any new raw sink fails the suite with its exact location."""
from __future__ import annotations

import os
import re

STATIC = os.path.join(os.path.dirname(__file__), "..", "bot", "api", "static")
PAGES = ("dashboard.html", "training.html")
RAW_SINK = re.compile(r"\$\{(?![^}]*esc\()[^}]*\.(error|notes|msg|reason|note|what_it_is)\b[^}]*\}")


def test_no_raw_backend_string_sinks():
    bad = []
    for fn in PAGES:
        src = open(os.path.join(STATIC, fn), encoding="utf-8").read()
        for i, line in enumerate(src.splitlines(), 1):
            for m in RAW_SINK.finditer(line):
                bad.append(f"{fn}:{i}: {m.group(0)[:80]}")
    assert not bad, ("unescaped backend-string sinks (wrap in esc()):\n  " + "\n  ".join(bad[:10]))


def test_esc_helper_and_token_attach_present():
    for fn in PAGES:
        src = open(os.path.join(STATIC, fn), encoding="utf-8").read()
        assert "const esc =" in src, f"{fn}: esc() helper missing"
        assert "X-API-Token" in src, f"{fn}: token auto-attach missing (auth would brick the UI)"
