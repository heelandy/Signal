"""HIGHSTRIKE contract registry — THE single source of trading economics (remediation Phase 3).

Every simulator / validator / report imports symbol economics from here; per-file constant tuples
are banned (grep-enforced by BOT/tests/test_contract_economics.py — the audit found ALL futures
priced as MNQ: NQ costs overstated ~10x in R, ES ~25x, GC on the wrong tick).

Values are per CONTRACT per SIDE. Commissions are all-in estimates (broker + exchange + NFA);
they get calibrated against measured paper fills (remediation Phases 5/8) — update HERE, nowhere
else, and note the date.

Options (0DTE/7DTE paths): per-contract commission + regulatory fees registered below so the
studies can adopt them at their next reset. The SEALED forward journals (7DTE condor et al.) keep
their in-flight cost model until that reset — changing a sealed study's economics mid-stream
would break clean-record comparability.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    sym: str
    point_value: float          # $ per 1.0 price point per contract
    tick: float                 # minimum increment, in price points
    commission: float           # $ per contract per side, all-in
    slip_ticks: int             # assumed slippage per side, in ticks
    kind: str = "future"        # "future" | "equity"


_EQUITY_SYMS = ("SPY", "QQQ", "NVDA", "TSLA", "AVGO", "ORCL", "AAPL", "MSFT", "AMZN", "META",
                "GOOGL", "DIA", "IWM", "AMD", "NFLX")

SPECS: dict[str, Contract] = {
    # sym                     $ / pt   tick   comm/side  slip
    "NQ":  Contract("NQ",      20.0,   0.25,  2.50,      2),
    "MNQ": Contract("MNQ",      2.0,   0.25,  0.52,      2),   # the historical evidence base's numbers
    "ES":  Contract("ES",      50.0,   0.25,  2.50,      2),
    "MES": Contract("MES",      5.0,   0.25,  0.52,      2),
    "GC":  Contract("GC",     100.0,   0.10,  2.60,      2),
    "MGC": Contract("MGC",     10.0,   0.10,  0.60,      2),
}
for _s in _EQUITY_SYMS:                     # $0.01 tick, commission-free, 1-tick slip assumption
    SPECS[_s] = Contract(_s, 1.0, 0.01, 0.0, 1, kind="equity")

# options economics (see module docstring re: sealed journals)
OPTION_COMMISSION = 0.65        # $ per contract per side
OPTION_FEES = 0.10              # regulatory + exchange, $ per contract per side (approx)


def spec(sym: str) -> Contract:
    s = str(sym).upper()
    try:
        return SPECS[s]
    except KeyError:
        # unknown symbol fails LOUD — a silent MNQ default IS the Phase 3 defect
        raise KeyError(f"no contract spec for {s!r} — add it to engine/hs_contracts.py") from None


def is_equity(sym: str) -> bool:
    return spec(sym).kind == "equity"
