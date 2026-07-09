"""Ensemble decision layer (MLP-001 §10) — ONE advisory verdict per rule-valid candidate.

Hard rules first (they already fired — a candidate only reaches here if the rule engine emitted
it). Risk stays the final authority. This layer BLENDS the advisory reads into a single, explained
verdict the dashboard and journal show:

    blocked_by_rules                     (never reaches here — rules didn't emit)
    risk_blocked                         risk gate said no
    approved_low_ai_confidence           rules + risk ok, AI reads weak/absent
    approved_high_ai_confidence          rules + risk ok, AI reads strong and agree

AI NEVER overrides the rules or the risk gate — it only grades confidence and explains itself.
"""
from __future__ import annotations

HIGH_P = 0.55            # calibrated P(win) above this = confident
NO_TRADE_HIGH = 0.65     # no-trade head above this = the blocked-setup model dislikes it
SIM_GOOD_R = 0.15        # nearest-cluster avg R above this = looks like winners


def decide_ensemble(risk_approved: bool, ml_p: float | None = None,
                    heads: dict | None = None, similarity: dict | None = None,
                    grade: str | None = None, nn_p: float | None = None) -> dict:
    """Blend the advisory reads. Absent models simply don't vote (prior-only = low confidence).
    nn_p = the NN sequence champion's calibrated confidence (None until one is promoted)."""
    heads = heads or {}
    reasons: list[str] = []
    if not risk_approved:
        return {"verdict": "risk_blocked", "score": None,
                "reasons": ["risk gate rejected — final authority"]}
    votes_up = votes_dn = 0
    if ml_p is not None:
        if ml_p >= HIGH_P:
            votes_up += 1; reasons.append(f"P(win) {ml_p:.2f} >= {HIGH_P}")
        elif ml_p < 0.45:
            votes_dn += 1; reasons.append(f"P(win) {ml_p:.2f} weak")
    exp_r = heads.get("expected_r")
    if exp_r is not None:
        (votes_up, votes_dn) = (votes_up + 1, votes_dn) if exp_r > 0.2 else \
            ((votes_up, votes_dn + 1) if exp_r < 0 else (votes_up, votes_dn))
        reasons.append(f"expected R {exp_r:+.2f}")
    nt = heads.get("no_trade")
    if nt is not None:
        if nt >= NO_TRADE_HIGH:
            votes_dn += 1; reasons.append(f"no-trade model dislikes it ({nt:.2f})")
        else:
            reasons.append(f"no-trade {nt:.2f} ok")
    if nn_p is not None:
        if nn_p >= HIGH_P:
            votes_up += 1; reasons.append(f"NN sequence {nn_p:.2f} >= {HIGH_P}")
        elif nn_p < 0.45:
            votes_dn += 1; reasons.append(f"NN sequence {nn_p:.2f} weak")
        else:
            reasons.append(f"NN sequence {nn_p:.2f} neutral")
    if similarity and similarity.get("avg_r") is not None:
        if similarity["avg_r"] >= SIM_GOOD_R:
            votes_up += 1
            reasons.append(f"looks like winner cluster {similarity['cluster']} "
                           f"({similarity['win_rate']:.0%}, {similarity['avg_r']:+.2f}R)")
        else:
            reasons.append(f"cluster {similarity['cluster']} is mediocre ({similarity['avg_r']:+.2f}R)")
    if grade in ("A+", "A"):
        votes_up += 1; reasons.append(f"grade {grade}")
    score = votes_up - votes_dn
    # No ML champion passed the gates yet, so nothing but the grade votes -> label it RULES-ONLY, not
    # "AI low" (user 2026-07-09: a grade-A+ setup read "LOW" only because no ML model exists to add a
    # confirming vote, which is misleading — "low" implied the AI disliked it).
    ml_voted = (ml_p is not None or exp_r is not None or nt is not None or nn_p is not None
                or (similarity is not None and similarity.get("avg_r") is not None))
    if not ml_voted:
        verdict = "rules_only"
        reasons.append("no ML champion serving — rules/grade only (not an AI 'low' read)")
    elif score >= 2 and votes_dn == 0:
        verdict = "approved_high_ai_confidence"
    else:
        verdict = "approved_low_ai_confidence"
    return {"verdict": verdict, "score": score, "reasons": reasons}


if __name__ == "__main__":
    hi = decide_ensemble(True, ml_p=0.61, heads={"expected_r": 0.35, "no_trade": 0.3},
                         similarity={"cluster": 2, "win_rate": 0.48, "avg_r": 0.4}, grade="A+")
    assert hi["verdict"] == "approved_high_ai_confidence", hi
    lo = decide_ensemble(True, ml_p=0.42, heads={"no_trade": 0.8})
    assert lo["verdict"] == "approved_low_ai_confidence" and lo["score"] < 0, lo
    rb = decide_ensemble(False)
    assert rb["verdict"] == "risk_blocked"
    none = decide_ensemble(True)                       # no models at all -> RULES-ONLY (not "AI low")
    assert none["verdict"] == "rules_only", none
    gr = decide_ensemble(True, grade="A+")             # grade A+ but no ML champion -> rules_only, not "low"
    assert gr["verdict"] == "rules_only", gr
    print("ensemble OK -", hi["verdict"], "|", ", ".join(hi["reasons"][:3]))
