"""bayesian-log-odds — evidence in decibels, an L4 decision aid.

Pure param engine (no market data): posterior_odds = prior_odds x
Product(bf_i); decibels = 10 x log10(Product(bf_i)).  Verdict bands
(Jaynes): >= +10dB strong-for, +5..10 moderate-for, -5..+5 noise,
-10..-5 moderate-against, <= -10 strong-against.

Evidence items are {name, bf} with bf = Bayes factor (> 0); bf <= 0
or unparseable entries are skipped with a declared note, never
silently counted.  Lineage: Jaynes, Probability Theory: The Logic of
Science (2003) — the decibel evidence scale.
"""
from __future__ import annotations

import math

from .statsutil import num_or_none


def log_odds(prior_odds: float = 1.0, evidence: list | None = None) -> dict:
    """Posterior odds + per-evidence dB contributions + verdict band."""
    prior = float(prior_odds)
    if prior <= 0:
        return {"error": "prior_odds must be > 0"}
    items = []
    skipped = []
    total_db = 0.0
    prod_bf = 1.0
    for e in (evidence or []):
        bf = num_or_none((e or {}).get("bf"))
        name = str((e or {}).get("name", "unnamed"))
        if bf is None or bf <= 0:
            skipped.append(name)
            continue
        db = 10.0 * math.log10(bf)
        items.append({"name": name, "bf": bf, "db": db})
        total_db += db
        prod_bf *= bf
    posterior = prior * prod_bf
    if total_db >= 10.0:
        verdict = "strong-for"
    elif total_db >= 5.0:
        verdict = "moderate-for"
    elif total_db > -5.0:
        verdict = "noise"
    elif total_db > -10.0:
        verdict = "moderate-against"
    else:
        verdict = "strong-against"
    out = {
        "weapon": "bayesian-log-odds",
        "anchor": "证据分贝——L4 决策辅助: posterior_odds = 先验×ΠBF, "
                  "dB = 10·log10(ΠBF); ≥+10dB 强支持, +5..10 中等, "
                  "±5 噪音, ≤−10 强反对 (Jaynes)",
        "prior_odds": prior,
        "evidence": items,
        "total_db": num_or_none(total_db),
        "posterior_odds": num_or_none(posterior),
        "verdict": verdict,
    }
    if skipped:
        out["skipped"] = skipped
        out["skipped_note"] = "entries with bf <= 0 or unparseable " \
                              "skipped (declared, never counted)"
    return out


def run(ctx: dict, prior_odds: float = 1.0,
        evidence: list | None = None) -> dict:
    """ctx unused (pure engine); all inputs are params."""
    return log_odds(prior_odds, evidence)
