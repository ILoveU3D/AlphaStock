"""forensic-audit — the three-layer financial-statement forensic report.

LAYER 1 strength (auto-selected by stock type):
- Piotroski F (2000): 9 binary signals for value stocks.
- Mohanram G (2005): 8 binary signals for growth stocks
  (selected when pe_ttm > 25 or rev_yoy > 15%).
HONESTY (non-negotiable): a score computed from k of n signals is
reported as ``score k_of_available (of n canonical)`` — never
renormalized to a pseudo-9/pseudo-8.  Per-market feed reality:
- US (us_financials.csv): roa=profit/assets, ocf, accrual (ocf>profit)
  computable; assets_prev / liabilities_prev / gross_profit_prev /
  current-ratio / share-count ABSENT -> those signals are None.
  G-score adds roa-vs-peer-median and capex/assets-vs-peer-median
  (cross-section from the same file); R&D, advertising and multi-year
  ROA volatility are declared gaps.
- A (a_financials + a_cashflow_annual + a_balance): no assets ->
  ROA gap; profit>0 stands in (named proxy), profit_yoy>0 stands in
  for Delta-ROA (named proxy).  accrual (ocf>profit) compares FY-annual
  ocf (a_cashflow_annual) against the latest INTERIM profit
  (a_financials) — period mismatch declared on the signal.
- HK (hk_f10 + hk_cashflow): profit>0, ocf>0, accrual, profit_yoy>0;
  same period-mismatch caveat; ocf frequently NaN at interim.

LAYER 2 fraud (three detectors cross-verifying):
(a) Beneish (1999) 8 indices where fields exist.  Today: SGI (rev/
    rev_prev, or 1+rev_yoy/100) everywhere; TATA=(profit-ocf)/assets
    US-only; DSRI A-only as the DECLARED approximation
    (1+rece_yoy/100)/(1+rev_yoy/100) (receivable levels absent).
    GMI/AQI/DEPI/SGAI/LVGI are gaps (prior gross margin, asset
    quality split, depreciation, SG&A, leverage fields absent).
    The canonical M-score needs all 8 -> NEVER computable on current
    feeds, said out loud in the output.  Detector flag: TATA dubious
    (Beneish's strongest single index) OR >=2 dubious indices.
(b) modified-Jones lite (Dechow et al. 1995): cross-sectional
    regression within the stock's market, total accruals
    (profit-ocf)/assets ~ Delta-rev/assets (PPE term absent ->
    declared lite).  Target residual z-score; |z|>2 flags.  Needs
    >=20 peers with profit+ocf+assets+rev_prev -> US only
    realistically; A/HK report data_gap (assets absent).
(c) Roychowdhury (2006) real-EM lite: abnormal OCF = residual of
    ocf/assets ~ rev/assets + Delta-rev/assets, same cross-sectional
    approach.  Production-cost and discretionary-expense detectors are
    declared gaps (no COGS-split / opex fields).

LAYER 3 distress: Altman (1968) Z components x4=market_cap/liabilities
and x5=rev/assets (US only; x1-x3 gaps: working capital, retained
earnings, EBIT absent) -> 2/5 partial coverage, NO canonical Z verdict.

Verdict: red when any layer-2 detector flags OR strength coverage >=7
with score <=2; amber on thin coverage (<4 signals); else green (always
carrying the coverage note).  House rule anchor: red may veto, green is
never a buy reason.

Lineage: Piotroski 2000 / Mohanram 2005 / Beneish 1999 / Dechow et al.
1995 (modified Jones) / Roychowdhury 2006 / Altman 1968.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, ols, zscore

ANCHOR = ("财报三层法医——红灯可否决，绿灯不构成买入理由;"
          "score 永远报 x/available(of canonical), 绝不归一化")

# Beneish canonical dubious thresholds (Beneish 1999).
BENEISH_THRESHOLDS = {
    "dsri": 1.465, "gmi": 1.193, "aqi": 1.254, "sgi": 1.608,
    "depi": 1.077, "sgai": 1.041, "lvgi": 1.037, "tata": 0.018,
}
GROWTH_PE_CUT = 25.0        # pe_ttm above -> Mohanram G instead of F
GROWTH_REV_YOY_CUT = 15.0   # rev_yoy % above -> Mohanram G
MIN_PEERS = 20              # cross-sectional regressions need >= 20
Z_FLAG = 2.0                # |residual z| above -> detector flag
THIN_COVERAGE = 4           # strength signals below -> amber


# ---------------------------------------------------------------------------
# Layer 1: strength signals (Piotroski F / Mohanram G)
# ---------------------------------------------------------------------------
def piotroski_signals(fin: dict, market: str) -> dict:
    """Canonical 9 F-signals -> True/False/None + proxy documentation.

    ``fin`` keys (all optional): profit, profit_prev, rev, rev_prev,
    ocf, capex, assets, liabilities, gross_margin, gross_margin_prev,
    profit_yoy_pct, period_mismatch.
    """
    market = str(market).upper()
    sig: dict[str, object] = {}
    proxies: dict[str, str] = {}
    notes: list[str] = []
    profit, ocf = fin.get("profit"), fin.get("ocf")
    assets = fin.get("assets")

    # 1. ROA > 0
    if profit is not None and assets:
        sig["roa_pos"] = profit / assets > 0
    elif profit is not None:
        sig["roa_pos"] = profit > 0
        proxies["roa_pos"] = "profit>0 proxy — assets absent, ROA not computable"
    else:
        sig["roa_pos"] = None
    # 2. OCF > 0
    sig["ocf_pos"] = (ocf > 0) if ocf is not None else None
    # 3. Delta-ROA > 0 — assets_prev absent everywhere -> US gap;
    #    A/HK stand in with profit_yoy>0 (named proxy).
    pyoy = fin.get("profit_yoy_pct")
    if market in ("A", "HK") and pyoy is not None:
        sig["d_roa_pos"] = pyoy > 0
        proxies["d_roa_pos"] = "profit_yoy>0 proxy — assets_prev absent"
    else:
        sig["d_roa_pos"] = None
    # 4. accrual: OCF > profit
    if ocf is not None and profit is not None:
        sig["accrual"] = ocf > profit
        if fin.get("period_mismatch"):
            notes.append("accrual compares FY-annual ocf vs latest "
                         "interim profit — period mismatch")
    else:
        sig["accrual"] = None
    # 5. Delta-leverage < 0 — liabilities_prev absent
    sig["d_leverage_neg"] = None
    # 6. Delta-current-ratio > 0 — current asset/liability split absent
    sig["d_current_ratio_pos"] = None
    # 7. no new share issuance — share counts absent from feeds
    sig["no_new_shares"] = None
    # 8. Delta-gross-margin > 0
    gm, gm_prev = fin.get("gross_margin"), fin.get("gross_margin_prev")
    sig["d_gross_margin_pos"] = ((gm > gm_prev)
                                 if gm is not None and gm_prev is not None
                                 else None)
    # 9. Delta-asset-turnover > 0 — assets_prev absent
    sig["d_asset_turnover_pos"] = None

    available = sum(v is not None for v in sig.values())
    score = sum(v is True for v in sig.values())
    return {"score_type": "piotroski-f", "score": int(score),
            "signals_available": int(available), "signals_total": 9,
            "signals": sig, "proxies": proxies, "notes": notes}


def g_score_signals(fin: dict, market: str,
                    peer_medians: dict | None = None) -> dict:
    """Canonical 8 Mohanram G-signals -> True/False/None + gaps.

    ``peer_medians``: {"roa": ..., "capex_a": ...} cross-sectional
    medians (US computable from us_financials; else None -> gaps).
    """
    market = str(market).upper()
    peer_medians = peer_medians or {}
    sig: dict[str, object] = {}
    proxies: dict[str, str] = {}
    notes: list[str] = []
    profit, ocf = fin.get("profit"), fin.get("ocf")
    assets, capex = fin.get("assets"), fin.get("capex")

    roa = (profit / assets) if (profit is not None and assets) else None
    if roa is not None:
        sig["roa_pos"] = roa > 0
    elif profit is not None:
        sig["roa_pos"] = profit > 0
        proxies["roa_pos"] = "profit>0 proxy — assets absent, ROA not computable"
    else:
        sig["roa_pos"] = None
    sig["ocf_pos"] = (ocf > 0) if ocf is not None else None
    if ocf is not None and profit is not None:
        sig["accrual"] = ocf > profit
        if fin.get("period_mismatch"):
            notes.append("accrual compares FY-annual ocf vs latest "
                         "interim profit — period mismatch")
    else:
        sig["accrual"] = None
    # G4 roa > industry median
    med_roa = peer_medians.get("roa")
    sig["roa_vs_peers"] = ((roa > med_roa)
                           if roa is not None and med_roa is not None
                           else None)
    # G5 less volatile ROA than peers — multi-year ROA series absent;
    # a single current/prev pair cannot measure volatility.  Gap.
    sig["roa_stability"] = None
    notes.append("roa_stability: multi-year ROA absent — peer-vol "
                 "comparison not computable (declared gap)")
    # G6 R&D/assets — R&D absent from every feed.  Gap.
    sig["rd_intensity"] = None
    notes.append("rd_intensity: R&D field absent (declared gap)")
    # G7 capex/assets > industry median (fallback: > 0, named proxy)
    med_cap = peer_medians.get("capex_a")
    capex_a = (capex / assets) if (capex is not None and assets) else None
    if capex_a is not None and med_cap is not None:
        sig["capex_intensity"] = capex_a > med_cap
    elif capex_a is not None:
        sig["capex_intensity"] = capex_a > 0
        proxies["capex_intensity"] = "capex/assets>0 proxy — peer median absent"
    else:
        sig["capex_intensity"] = None
    # G8 advertising/assets — advertising absent.  Gap.
    sig["ad_intensity"] = None
    notes.append("ad_intensity: advertising field absent (declared gap)")

    available = sum(v is not None for v in sig.values())
    score = sum(v is True for v in sig.values())
    return {"score_type": "mohanram-g", "score": int(score),
            "signals_available": int(available), "signals_total": 8,
            "signals": sig, "proxies": proxies, "notes": notes}


def strength_layer(fin: dict, market: str, row=None,
                   peer_medians: dict | None = None) -> dict:
    """Auto-select F (value) or G (growth) by pe_ttm / rev_yoy."""
    pe = rev_yoy = None
    if row is not None:
        pe = num_or_none(row.get("pe_ttm"))
        rev_yoy = num_or_none(row.get("rev_yoy"))
    growth = ((pe is not None and pe > GROWTH_PE_CUT)
              or (rev_yoy is not None and rev_yoy > GROWTH_REV_YOY_CUT))
    out = (g_score_signals(fin, market, peer_medians) if growth
           else piotroski_signals(fin, market))
    out["selected_by"] = (f"growth (pe={pe}, rev_yoy={rev_yoy})"
                          if growth else f"value (pe={pe}, rev_yoy={rev_yoy})")
    out["coverage_note"] = (
        f"{out['signals_available']}/{out['signals_total']} signals "
        "computable — NOT a canonical score; never rescaled")
    return out


# ---------------------------------------------------------------------------
# Layer 2a: Beneish 8 indices
# ---------------------------------------------------------------------------
def _idx(value, threshold: float, note: str = "") -> dict:
    v = num_or_none(value)
    return {"value": v, "threshold": threshold,
            "dubious": (bool(v > threshold) if v is not None else None),
            "note": note}


def beneish_indices(fin: dict) -> dict:
    """The 8 Beneish indices where fields exist; per-index dubious flags.

    Returns {"indices": {...}, "coverage": n, "m_score": None,
             "m_note": ...} — the canonical M-score needs all 8 and is
    never computable on current feeds (said out loud).
    """
    idx: dict[str, dict] = {}
    rev, rev_prev = fin.get("rev"), fin.get("rev_prev")
    rev_yoy = fin.get("rev_yoy_pct")
    if rev is not None and rev_prev not in (None, 0):
        sgi = rev / rev_prev
    elif rev_yoy is not None:
        sgi = 1.0 + rev_yoy / 100.0
    else:
        sgi = None
    idx["sgi"] = _idx(sgi, BENEISH_THRESHOLDS["sgi"],
                      "rev/rev_prev (or 1+rev_yoy/100)")
    profit, ocf, assets = fin.get("profit"), fin.get("ocf"), fin.get("assets")
    tata = ((profit - ocf) / assets
            if profit is not None and ocf is not None and assets else None)
    idx["tata"] = _idx(tata, BENEISH_THRESHOLDS["tata"],
                       "(profit-ocf)/assets — needs assets (US only)")
    rece_yoy = fin.get("rece_yoy_pct")
    dsri = ((1.0 + rece_yoy / 100.0) / (1.0 + rev_yoy / 100.0)
            if rece_yoy is not None and rev_yoy is not None else None)
    idx["dsri"] = _idx(dsri, BENEISH_THRESHOLDS["dsri"],
                       "approx (1+rece_yoy)/(1+rev_yoy) — receivable "
                       "levels absent (A only)")
    gm, gm_prev = fin.get("gross_margin"), fin.get("gross_margin_prev")
    idx["gmi"] = _idx((gm_prev / gm
                       if gm not in (None, 0) and gm_prev is not None
                       else None),
                      BENEISH_THRESHOLDS["gmi"],
                      "prior gross margin absent from feeds")
    idx["aqi"] = _idx(None, BENEISH_THRESHOLDS["aqi"],
                      "asset-quality split absent")
    idx["depi"] = _idx(None, BENEISH_THRESHOLDS["depi"],
                       "depreciation & gross PPE absent")
    idx["sgai"] = _idx(None, BENEISH_THRESHOLDS["sgai"],
                       "SG&A absent")
    idx["lvgi"] = _idx(None, BENEISH_THRESHOLDS["lvgi"],
                       "liabilities/assets prior pair absent")
    coverage = sum(i["value"] is not None for i in idx.values())
    return {"indices": idx, "coverage": int(coverage), "m_score": None,
            "m_note": "canonical M-score needs all 8 indices — never "
                      "computable on current feeds (DSRI/GMI/AQI/DEPI/"
                      "SGAI/LVGI gaps); no partial M is ever reported"}


def beneish_flag(beneish: dict):
    """Detector flag: TATA dubious (strongest single index) or >=2
    dubious among computed indices; None when nothing computable."""
    idx = beneish["indices"]
    computed = [i for i in idx.values() if i["dubious"] is not None]
    if not computed:
        return None
    if idx["tata"]["dubious"] is True:
        return True
    return sum(i["dubious"] is True for i in computed) >= 2


# ---------------------------------------------------------------------------
# Layer 2b/c: cross-sectional accrual regressions (modified-Jones lite,
# Roychowdhury abnormal-OCF lite)
# ---------------------------------------------------------------------------
def jones_lite(df: pd.DataFrame, code_col: str = "code",
               min_peers: int = MIN_PEERS, z_flag: float = Z_FLAG) -> dict:
    """TA/assets ~ DeltaRev/assets cross-sectional lite (PPE term absent).

    ``df`` columns: code_col, ta, drev.  Returns a table with per-code
    residual z and flag; data_gap when peers < min_peers.
    """
    d = df[[code_col, "ta", "drev"]].dropna()
    if len(d) < min_peers:
        return {"status": "data_gap", "n": int(len(d)),
                "reason": f"needs >= {min_peers} peers with profit, ocf, "
                          "assets, rev_prev (assets absent outside US)"}
    fit = ols(d["ta"], d["drev"])
    resid = fit["resid"]
    z = zscore(resid)
    table = pd.DataFrame({code_col: d[code_col].values,
                          "resid": resid.values, "z": z.values})
    table["flag"] = table["z"].abs() > z_flag
    return {"status": "ok", "n": int(len(d)), "r2": num_or_none(fit["r2"]),
            "lite_note": "modified-Jones lite — PPE term absent "
                         "(declared)", "table": table}


def abnormal_ocf_lite(df: pd.DataFrame, code_col: str = "code",
                      min_peers: int = MIN_PEERS,
                      z_flag: float = Z_FLAG) -> dict:
    """Roychowdhury abnormal OCF: ocf/assets ~ rev/assets + dRev/assets.

    Production-cost and discretionary-expense detectors are declared
    gaps (no COGS-split / opex fields) — see run() output.
    """
    d = df[[code_col, "ocf_a", "rev_a", "drev"]].dropna()
    if len(d) < min_peers:
        return {"status": "data_gap", "n": int(len(d)),
                "reason": f"needs >= {min_peers} peers with ocf, rev, "
                          "assets, rev_prev (assets absent outside US)"}
    Y = d["ocf_a"].to_numpy(float)
    X = np.column_stack([d["rev_a"].to_numpy(float),
                         d["drev"].to_numpy(float),
                         np.ones(len(d))])
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ coef
    sd = resid.std()
    z = (resid - resid.mean()) / (sd if sd > 0 else 1.0)
    table = pd.DataFrame({code_col: d[code_col].values,
                          "resid": resid, "z": z})
    table["flag"] = table["z"].abs() > z_flag
    return {"status": "ok", "n": int(len(d)),
            "lite_note": "abnormal-OCF lite — production-cost / "
                         "discretionary-expense detectors are gaps "
                         "(no COGS-split/opex fields)", "table": table}


def _target_from(table_res: dict, code: str) -> dict:
    """Pull the target row out of a lite-regression table."""
    if table_res.get("status") != "ok":
        return table_res
    hit = table_res["table"][table_res["table"]["code"].astype(str)
                             == str(code)]
    if not len(hit):
        return {"status": "data_gap", "n": table_res["n"],
                "reason": "target not in the peer regression frame "
                          "(missing ta/drev fields)"}
    h = hit.iloc[0]
    return {"status": "ok", "n": table_res["n"],
            "r2": table_res.get("r2"),
            "lite_note": table_res.get("lite_note"),
            "resid": num_or_none(h["resid"]),
            "z": num_or_none(h["z"]), "flag": bool(h["flag"])}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def combine_verdict(l2_flags, strength_score, strength_available) -> str:
    """red: any layer-2 detector flag, or coverage>=7 with score<=2.
    amber: thin coverage.  else green (always with coverage note)."""
    flags = [f for f in l2_flags if f is not None]
    if any(flags):
        return "red"
    if (strength_available is not None and strength_available >= 7
            and (strength_score or 0) <= 2):
        return "red"
    if strength_available is None or strength_available < THIN_COVERAGE:
        return "amber"
    return "green"


# ---------------------------------------------------------------------------
# Snapshot loaders
# ---------------------------------------------------------------------------
def _load_fin(snap: Path, market: str, code: str) -> dict:
    """Assemble the fin dict for one stock from the per-market feeds."""
    market = str(market).upper()
    fin: dict = {"market": market}
    if market == "US":
        us = pd.read_csv(snap / "us_financials.csv")
        hit = us[us["ticker"].astype(str) == str(code)]
        if not len(hit):
            return {"market": market, "data_gap": "ticker absent from us_financials.csv"}
        h = hit.iloc[0]
        for k in ("rev", "rev_prev", "profit", "profit_prev", "ocf",
                  "capex", "assets", "liabilities", "equity",
                  "gross_margin", "div_paid"):
            fin[k] = num_or_none(h.get(k))
    elif market == "A":
        af = pd.read_csv(snap / "a_financials.csv", dtype={"code": str})
        hit = af[af["code"] == str(code)]
        if len(hit):
            h = hit.iloc[0]
            fin["rev"] = num_or_none(h.get("revenue"))
            fin["profit"] = num_or_none(h.get("profit"))
            fin["profit_yoy_pct"] = num_or_none(h.get("profit_yoy"))
            fin["rev_yoy_pct"] = num_or_none(h.get("rev_yoy"))
            fin["gross_margin"] = num_or_none(h.get("gross_margin"))
            fin["report_date"] = str(h.get("report_date"))
        ac = pd.read_csv(snap / "a_cashflow_annual.csv",
                         dtype={"code": str})
        hit = ac[ac["code"] == str(code)]
        if len(hit):
            h = hit.iloc[0]
            fin["ocf"] = num_or_none(h.get("ocf"))
            fin["capex"] = num_or_none(h.get("capex"))
            fin["ocf_report_date"] = str(h.get("report_date"))
        fin["period_mismatch"] = True  # FY-annual ocf vs interim profit
        ab = pd.read_csv(snap / "a_balance.csv", dtype={"code": str})
        hit = ab[ab["code"] == str(code)]
        if len(hit):
            fin["rece_yoy_pct"] = num_or_none(hit.iloc[0].get("rece_yoy"))
    elif market == "HK":
        hk = pd.read_csv(snap / "hk_f10.csv", dtype={"code": str})
        hit = hk[hk["code"] == str(code).zfill(5)]
        if len(hit):
            h = hit.iloc[0]
            fin["rev"] = num_or_none(h.get("revenue"))
            fin["profit"] = num_or_none(h.get("profit"))
            fin["profit_yoy_pct"] = num_or_none(h.get("profit_yoy"))
            fin["rev_yoy_pct"] = num_or_none(h.get("rev_yoy"))
            fin["gross_margin"] = num_or_none(h.get("gross_margin"))
            fin["ocf"] = num_or_none(h.get("ocf"))
            fin["report_date"] = str(h.get("report_date"))
        hc = pd.read_csv(snap / "hk_cashflow.csv", dtype={"code": str})
        hit = hc[hc["code"] == str(code).zfill(5)]
        if len(hit):
            h = hit.iloc[0]
            # f10 ocf is often NaN at interim — fall back to the annual
            # cash-flow row; period mismatch vs interim profit declared
            if fin.get("ocf") is None:
                fin["ocf"] = num_or_none(h.get("ocf"))
            fin["capex"] = num_or_none(h.get("capex"))
            fin["div_paid"] = num_or_none(h.get("div_paid"))
            fin["period_mismatch"] = True
    return fin


def _us_peer_frames(snap: Path):
    """US cross-section for Beneish-free detectors + G-score medians."""
    us = pd.read_csv(snap / "us_financials.csv")
    a = pd.to_numeric(us["assets"], errors="coerce").where(
        pd.to_numeric(us["assets"], errors="coerce") > 0)
    num = lambda c: pd.to_numeric(us[c], errors="coerce")
    peers = pd.DataFrame({
        "code": us["ticker"].astype(str),
        "ta": (num("profit") - num("ocf")) / a,
        "drev": (num("rev") - num("rev_prev")) / a,
        "ocf_a": num("ocf") / a,
        "rev_a": num("rev") / a,
        "roa": num("profit") / a,
        "capex_a": num("capex") / a,
    })
    medians = {"roa": num_or_none(peers["roa"].median()),
               "capex_a": num_or_none(peers["capex_a"].median())}
    return peers, medians


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, **params) -> dict:
    """Three-layer forensic report for the target row (deep weapon —
    needs with_kline=(market, code) in the context)."""
    out = {"weapon": "forensic-audit", "anchor": ANCHOR}
    row = ctx.get("row")
    if row is None:
        out["status"] = "data_gap"
        out["reason"] = ("no target row — build the context with "
                         "with_kline=(market, code)")
        return out
    snap = ctx["snap"]
    market, code = str(row["market"]), str(row["code"])
    out.update(market=market, code=code)

    fin = _load_fin(snap, market, code)
    peers = medians = None
    if market == "US":
        peers, medians = _us_peer_frames(snap)

    # LAYER 1 strength
    strength = strength_layer(fin, market, row, medians)

    # LAYER 2 fraud
    beneish = beneish_indices(fin)
    b_flag = beneish_flag(beneish)
    if peers is not None:
        jones = _target_from(jones_lite(peers), code)
        roych = _target_from(abnormal_ocf_lite(peers), code)
    else:
        gap = ("assets absent in A/HK feeds — cross-sectional accrual "
               "regressions not computable")
        jones = {"status": "data_gap", "reason": gap}
        roych = {"status": "data_gap", "reason": gap}
    roych["production_cost_detector"] = {
        "status": "data_gap", "reason": "no COGS-split fields"}
    roych["discretionary_expense_detector"] = {
        "status": "data_gap", "reason": "no opex fields"}
    l2_flags = [b_flag,
                jones.get("flag") if jones.get("status") == "ok" else None,
                roych.get("flag") if roych.get("status") == "ok" else None]
    fraud = {"beneish": {**beneish, "flag": b_flag},
             "jones_lite": jones, "roychowdhury_lite": roych,
             "any_flag": any(f is True for f in l2_flags)}

    # LAYER 3 distress — Altman partial (x4, x5 US only)
    liabilities, assets, rev = (fin.get("liabilities"), fin.get("assets"),
                                fin.get("rev"))
    mcap = num_or_none(row.get("market_cap"))
    x4 = (mcap / liabilities
          if mcap is not None and liabilities not in (None, 0) else None)
    x5 = (rev / assets if rev is not None and assets not in (None, 0)
          else None)
    distress = {"components": {
                    "x4_mcap_liabilities": num_or_none(x4),
                    "x5_sales_assets": num_or_none(x5)},
                "components_available": sum(v is not None
                                            for v in (x4, x5)),
                "components_total": 5,
                "note": "x1-x3 gaps (working capital, retained earnings, "
                        "EBIT absent) — partial coverage, NO canonical "
                        "Z verdict"}

    verdict = combine_verdict(l2_flags, strength["score"],
                              strength["signals_available"])
    out["layers"] = {"strength": strength, "fraud": fraud,
                     "distress": distress}
    out["verdict"] = verdict
    out["verdict_note"] = ("红灯可否决，绿灯不构成买入理由 — verdict is a "
                           "veto instrument, never a buy reason")
    if fin.get("data_gap"):
        out["feed_note"] = fin["data_gap"]
    return out
