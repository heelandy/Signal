# UI PLAN — the Operator Console (Phase U implementation blueprint)
*(2026-07-12 · docs-first per project rule: this document precedes any Phase U code ·
authority: `docs/REMEDIATION_PLAN.md` §Phase U — hard rules 1–6 apply verbatim)*

The backend truth for every view now EXISTS (Phases 4–7, R, E landed). The UI's job is to make
it visible, block unsafe actions, and guide the workflow — it can never fix what the backend
can't prove, and it must never claim what the backend hasn't proven.

## The two primary views (entry-first charter)

Everything else supports these:
1. **Entry Console** — "Should I enter now, and why?"
2. **Profitability Lab** — "Has this exact entry type actually made money?"

## Page layout decision

Two pages, split by job (evolving the existing files — no rewrite, no new framework):
- **`dashboard.html` = OPERATE**: Mission Control strip · Entry Console · Orders & Fills ·
  Risk cockpit · Reconciliation Center. The trader's screen.
- **`training.html` = GOVERN**: Strategy Evidence · Profitability Lab · Models · Approvals
  ladder · Data Trust · Incidents. The reviewer's screen.

Conventions (already partly in place): `esc()` on every backend/operator string entering
innerHTML · X-API-Token auto-attach (done) · the four-state chips
`HEALTHY / DEGRADED / BLOCKED / UNKNOWN` (UNKNOWN never renders green; missing is never `0.00`) ·
no client-side risk math — the backend's numbers are displayed, never recomputed.

## New backend endpoints Phase U needs (thin, read-only)

| Endpoint | Serves | Notes |
|---|---|---|
| `GET /api/readiness` | Mission Control | THE single readiness source (hard rule 4): `{mode, kill_switch, overall: ok\|BLOCKED, gates: [{name, ok, reason}]}` aggregating: QA `all_ok` + staleness · A/B version match · approval state (incl. stale/legacy) · phase-8 criteria + reconciliation-clean · halt flag · autotrade/approval arm state · live lock. Server-computed verbatim reasons; the UI renders, never derives |
| `GET /api/exec/orders` | Orders & Fills, Reconciliation | `exec_orders` + latest event per order (state, reason, correlation_id, dims) |
| `GET /api/exec/fills` | Orders & Fills, Risk | `exec_fills` + realized round-trip P&L (reuse `_replay_fills`) |
| `GET /api/risk/state` | Risk cockpit | `account_truth()` rendered with per-field source+age; `AccountUnproven` → the UNKNOWN payload (blocking, rule 5) |
| `GET /api/removals` | Lab, Entry Console | `removals.active()` + nominations passthrough |
| `GET /api/incidents` | Incidents | crash_*.txt list (name, first line) · watchdog.log tail (parsed relaunch/unhealthy lines) · last backup + verify result · log sizes |

All GET, no mutation, `esc()`-safe strings, ≤50 lines each — they read stores that already exist.

## Views — source of truth → elements → acceptance

**1. Mission Control strip** (top of `dashboard.html`; ships first)
- Source: `/api/readiness`, `/api/live`.
- Elements: MODE badge · LIVE LOCKED badge · kill-switch state+button · "Trading readiness:
  OK/BLOCKED" with the ✕/✓ gate lines verbatim · process identity (role/pid/scan age) ·
  forward-gate chips (restart-gate day N/7 · fills n).
- Accept: readiness lines match the API byte-for-byte; BLOCKED shows every red gate; no
  client-side aggregation (TU.1 pins the API side).

**2. Entry Console** (replaces the signals table's row-rendering; primary #1)
- Source: `/api/signals` (already carries: signal_state, watch/cooldown/stale states via
  status, grade, removed, tradeable, entry/stop/tp1/tp2, rr, dir reads).
- Elements per candidate: side + symbol header · OR levels + trigger · entry/stop/target with
  risk/reward/R:R · the state machine rendered honestly (setup developing / armed / waiting
  confirmation / FIRED / too extended—do not chase / waiting for pullback / stale / invalidated /
  already traded / REMOVED) · the WHY line = the exact check that passed/failed · action verdict
  ("DO NOT ENTER YET" / "ENTER — conditions met") · grade with its three components
  (vwap/aligned/slope) shown, not just the letter.
- Accept: every state above renders from a fixture signal dict; a `removed` signal shows the
  reason + stays visible; no state is inferred client-side from prices.

**3. Profitability Lab** (`training.html` tab; primary #2)
- Source: `/api/entry_matrix?evidence=…`, `/api/entry_matrix/nominations`, `/api/removals`.
- Elements: evidence selector (backtest | shadow | paper | live — one at a time, rule 3; the
  page NEVER merges) · the matrix table (dims + n, WR, net exp, PF, totR, maxDD, CI90) ·
  INSUFFICIENT SAMPLE cells render as muted "n=X — not a verdict" (rule 6) · REMOVED badge rows
  with evidence link · nominations panel with "next step: cohort test" wording · lineage banner
  (frozen-span waiver visible).
- Accept: TE.2/TE.4 semantics visible: switching evidence never mixes; an n=9 loser cell cannot
  be visually confused with a verdict.

**4. Orders & Fills** (`dashboard.html`)
- Source: `/api/exec/orders`, `/api/exec/fills`, `/api/paper_log`.
- Elements: one row per order → expandable lifecycle timeline (signal → risk qty → submitted →
  acked → partial/final fills → bracket confirmed → exit → reconciled) each with timestamp ·
  quantity breakdown requested/filled/remaining/cancelled/**protected** · failure rows show the
  exact stage + verbatim reason ("BLOCKED AT RISK — daily loss …") · `SUBMIT_UNKNOWN` renders
  the "do not resubmit" banner · `INVESTIGATION_REQUIRED` renders red.
- Accept: the interaction-state rules of Phase U (race-proof buttons, CANCEL REQUESTED until
  reconciled) — pinned against fixture rows.

**5. Risk cockpit** (`dashboard.html`)
- Source: `/api/risk/state`.
- Elements: per-field value + source + age ("Daily P&L −$230 · fills replay · 8s") ·
  limits vs used (daily/weekly loss, trades today, streak, open positions) · correlated exposure
  as BUCKETS (nasdaq/spx/gold), never a symbol list · UNKNOWN on any field = the blocking banner
  (rule 5).
- Accept: an `AccountUnproven` payload renders BLOCKED, not zeros.

**6. Reconciliation Center** (`dashboard.html`; dedicated panel, not a chip)
- Source: `/api/exec/orders` (mismatch events), `/api/live` (halt state via readiness).
- Elements: internal-vs-broker table per symbol · CRITICAL banner on halt (system-wide, red) ·
  the halt reason verbatim · recovery instructions text · NO "continue anyway" control (rule 2)
  — clearing happens only by a clean reconcile pass backend-side.
- Accept: TU.2 semantics — banner and submission-halt come from the same flag.

**7. Data Trust** (`training.html`)
- Source: `/api/training/dataqa` (now carries fingerprints, staleness, grain, thresholds).
- Elements: per symbol/tf card — span, last complete session, freshness verdict, expected vs
  actual bars, short-day %, grain, fingerprint · consumers line ("used by: ORB 07.7, A/B, ML
  dataset") · the approval consequence line ("Result: paper approval requires override — frozen-
  span waiver") · GC's honest verdict shown as-is.
- Accept: a red QA symbol renders BLOCKED and names the downstream consequence.

**8. Strategy Evidence** (`training.html`; evolve the approvals block)
- Source: `/api/approval/status` (evidence + snapshot + stale/legacy + override flags),
  `/api/phase78`, A/B report.
- Elements: one card per version — backtest validity state · dataset fingerprint (pinned vs
  current, drift = STALE badge) · A/B match · parity status (pending TV) · shadow forward ·
  paper fills n · approval stage with OVERRIDE visibly flagged forever · the five evidence
  types SEPARATED (rule 3).
- Accept: an override approval can never render as a clean one.

**9. Models** (`training.html`)
- Source: `/api/training/registry`.
- Elements: champion/challenger · label strategy version vs current — mismatch renders
  "**MODEL BLOCKED — serving refused**" (the guard is already backend-enforced) · gates_passed ·
  promoted-against fingerprint · dataset/feature lineage.
- Accept: the 07.4 similarity model shows BLOCKED today.

**10. Approvals ladder** (`training.html`; extend existing)
- Source: `/api/approval/status`.
- Elements: Research→Replay→Paper→Live ladder · locked stages enumerate every unmet predicate
  verbatim · approve buttons disabled by BACKEND verdicts (clicking a locked stage explains,
  never submits) · override path demands typed notes.
- Accept: with today's red QA, Paper renders "requires override (frozen-span waiver)" — exactly
  the truth.

**11. Incidents** (`training.html`)
- Source: `/api/incidents`, `/api/alerts`.
- Elements: restarts + last crash reason (crash_*.txt first lines) · failed beats history ·
  provider/broker errors · log sizes · last backup + last verified restore · whether a restart
  left unresolved orders (exec recovery report).
- Accept: a synthetic crash file renders with its cause line; silence renders as "no incidents
  in N days" with the gate-1 day counter.

## Build order (each step lands runnable; sizes S/M/L)

1. **S** — the six thin endpoints (`readiness` first; TU.1 test with it).
2. **S** — Mission Control strip in `dashboard.html`.
3. **M** — Entry Console (evolve the signals renderer; fixture-driven state test).
4. **M** — Profitability Lab tab in `training.html`.
5. **M** — Orders & Fills + Reconciliation Center (fixture rows for every lifecycle state).
6. **S** — Risk cockpit.
7. **S** — Data Trust cards.
8. **M** — Strategy Evidence + Models + Approvals ladder evolution.
9. **S** — Incidents.

Rules of engagement: no new frameworks, no build step — plain JS in the existing pages;
`esc()` mandatory on every interpolated backend string; every step ends with the suite green and
a manual screenshot check (`driver.py --shot`); the feature freeze still bans decorative panels —
if an element doesn't expose backend truth or block an unsafe action, it doesn't ship.
