"""Single-stock analysis engine.

Assembles a live quote, snapshot fundamentals and kline metrics for one
resolved stock, ranks it against its market's gated peer universe, and
renders a deterministic verdict. Output is brief-first (verdict + key
numbers) with the full evidence table available on demand — the calling
AI writes the prose; this module supplies facts.
"""

import json
from pathlib import Path

import pandas as pd

from . import config
from .fetch.fundamentals import fetch_hk_f10
from .fetch.kline import (fetch_kline_any, kline_cache_path,
                          kline_is_fresh, load_kline)
from .fetch.pipeline import add_cashflow_factors, apply_gates, \
    backfill_kline_factors, load_annual_cashflows, \
    merge_a_financials, merge_us_financials
from .fetch.quotes import fetch_quotes_by_secids
from .report import resolve_snapshot
from .resolve import Match
from .strategy.composite import apply_composite
from .strategy.factors import PILLARS, add_pillar_scores, kline_metrics
from .strategy.horizons import apply_horizon_score
from .strategy.registry import get_horizon, get_strategy, list_horizons

# (column, label, lower_is_better) — evidence table layout
EVIDENCE_METRICS = [
    ("pe_ttm", "PE (TTM)", True),
    ("pb", "PB", True),
    ("ps", "P/S", True),
    ("dividend_yield", "Div yield %", False),
    ("rev_yoy", "Revenue YoY %", False),
    ("profit_yoy", "Profit YoY %", False),
    ("rev_q_yoy", "Revenue QoQ YoY %", False),
    ("roe", "ROE %", False),
    ("gross_margin", "Gross margin %", False),
    ("net_margin", "Net margin %", False),
    ("debt_ratio", "Debt ratio %", True),
    ("ret_250d", "1y return %", False),
    ("ret_60d", "3m return %", False),
    ("volatility", "Volatility %", True),
    ("drawdown_52w", "Drawdown %", False),
    ("ocf_yield", "OCF yield % (annual)", False),
    ("fcf_yield", "FCF yield % (annual)", False),
    ("capex_to_ocf", "Capex/OCF", True),
]

VERDICTS = [
    (85, "outstanding opportunity"),
    (70, "attractive"),
    (40, "reasonable"),
    (20, "unattractive"),
    (0, "poor"),
]


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------
def percentile(value, series, lower_is_better: bool = False):
    """Oriented percentile of value in series (0-100, higher=better)."""
    s = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if s.empty or value is None or pd.isna(value):
        return None
    frac = (float((s < value).mean())
            + 0.5 * float((s == value).mean())) * 100.0
    return round(100.0 - frac if lower_is_better else frac, 1)


def verdict_band(pct):
    """Five-band label from the blended composite percentile."""
    if pct is None:
        return "inconclusive (insufficient data)"
    for floor, label in VERDICTS:
        if pct >= floor:
            return label
    return "poor"


def _flat_row(result: dict) -> dict:
    row = dict(result.get("quote") or {})
    row.update(result.get("fundamentals") or {})
    row.update(result.get("cashflow_factors") or {})
    for k, v in (result.get("kline") or {}).items():
        if not k.startswith("_"):
            row[k] = v
    return row


def _snapshot_factors(snap, market: str, code: str) -> dict:
    """Cashflow-first factors for the target from the snapshot's
    master/watchlist rows (annual basis, snapshot market cap)."""
    if snap is None:
        return {}
    for fname in ("master.csv", "watchlist.csv"):
        p = snap / fname
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if "market" not in df.columns or "code" not in df.columns:
            continue
        hit = df[(df["market"] == market)
                 & (df["code"].astype(str) == str(code))]
        if not hit.empty:
            r = hit.iloc[0]
            return {k: r.get(k) for k in ("ocf_yield", "fcf_yield",
                                         "capex_to_ocf",
                                         "borrowed_dividend")}
    return {}


def _manifest_fx(snap) -> float | None:
    """HKD/CNY rate recorded by the fetch run, if any."""
    try:
        m = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
        v = m.get("fx_hkdcny")
        return float(v) if v else None
    except (OSError, ValueError, TypeError):
        return None


def risk_flags(result: dict) -> list:
    """Hard observations, not opinions."""
    row = _flat_row(result)
    flags = []

    def _num(col):
        v = row.get(col)
        try:
            f = float(v)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    if (v := _num("debt_ratio")) is not None and v > 70:
        flags.append(f"high leverage: debt ratio {v:.0f}%")
    if (v := _num("rev_yoy")) is not None and v < 0:
        flags.append(f"revenue contracting: {v:.1f}% YoY")
    if (v := _num("profit_yoy")) is not None and v < 0:
        flags.append(f"profit contracting: {v:.1f}% YoY")
    if (v := _num("drawdown_52w")) is not None and v < -40:
        flags.append(f"deep drawdown: {v:.0f}% from 52w high")
    if (v := _num("volatility")) is not None and v > 60:
        flags.append(f"high volatility: {v:.0f}% annualized")
    if (v := _num("borrowed_dividend")) is not None and v > 0:
        flags.append("borrowed dividend: 年报分红超过自由现金流且筹资净流入"
                     "（A 股语境：保再融资资格的借钱分红，危险信号）")
    if result.get("warnings"):
        flags.append("incomplete data: " + "; ".join(result["warnings"]))
    return flags


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------
def build_peer_set(snapshot_dir, market: str) -> pd.DataFrame:
    """The gated universe for a market, rebuilt from snapshot files."""
    snap = Path(snapshot_dir)
    quotes = pd.read_csv(snap / f"{market.lower()}_quotes.csv",
                         dtype={"code": str})
    if market == "A":
        fin = None
        if (snap / "a_financials.csv").exists():
            fin = pd.read_csv(snap / "a_financials.csv",
                              dtype={"code": str})
        df = merge_a_financials(quotes, fin)
    elif market == "US":
        fin = None
        if (snap / "us_financials.csv").exists():
            fin = pd.read_csv(snap / "us_financials.csv",
                              dtype={"ticker": str})
        df = merge_us_financials(quotes, fin)
    else:
        df = quotes
    gated = apply_gates(df, market)
    annual = load_annual_cashflows(snap)
    if not annual.empty:
        gated = add_cashflow_factors(gated, _manifest_fx(snap), annual)
    return backfill_kline_factors(gated, snap)


def live_quote(match: Match):
    """Real-time quote row via push2 ulist; None on failure."""
    if not match.market_id:
        return None
    df = fetch_quotes_by_secids([f"{match.market_id}.{match.code}"])
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    if match.market == "HK":
        row["code"] = str(row["code"]).zfill(5)
    return row


HK_F10_FIELDS = ("report_date", "revenue", "rev_yoy", "profit_yoy",
                 "roe", "gross_margin", "net_margin", "debt_ratio",
                 "dividend_yield")
A_FIN_FIELDS = ("report_date", "revenue", "rev_yoy", "profit_yoy",
                "roe", "gross_margin")
US_FIN_FIELDS = ("rev", "rev_yoy", "profit_yoy", "rev_q_yoy", "roe",
                 "gross_margin", "net_margin", "debt_ratio")


def target_fundamentals(match: Match, snapshot_dir) -> dict:
    """Fundamental metrics for the target, snapshot-first, HK live."""
    snap = Path(snapshot_dir) if snapshot_dir else None
    if snap is not None:
        if match.market == "A" and (snap / "a_financials.csv").exists():
            f = pd.read_csv(snap / "a_financials.csv",
                            dtype={"code": str})
            hit = f[f["code"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in A_FIN_FIELDS}
        if match.market == "US" and (snap / "us_financials.csv").exists():
            f = pd.read_csv(snap / "us_financials.csv",
                            dtype={"ticker": str})
            hit = f[f["ticker"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in US_FIN_FIELDS}
        if match.market == "HK" and (snap / "hk_f10.csv").exists():
            f = pd.read_csv(snap / "hk_f10.csv", dtype={"code": str})
            hit = f[f["code"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in HK_F10_FIELDS}
    if match.market == "HK":
        f10 = fetch_hk_f10(match.code)
        if f10 is not None and not f10.empty:
            r = f10.iloc[0]
            return {k: r.get(k) for k in HK_F10_FIELDS}
    return {}


def target_kline_metrics(match: Match, snapshot_dir) -> dict:
    """Kline-derived momentum metrics; fresh cache preferred."""
    kl = None
    if snapshot_dir is not None:
        p = kline_cache_path(Path(snapshot_dir), match.market, match.code)
        if p.exists() and kline_is_fresh(p, match.market):
            kl = load_kline(p)
    if kl is None:
        kl = fetch_kline_any(match.market, match.code,
                             match.market_id, lmt=config.KLINE_DAYS)
    out = kline_metrics(kl)
    out["_bars"] = len(kl) if kl is not None else 0
    out["_last_date"] = (str(kl["date"].iloc[-1])
                         if kl is not None and not kl.empty else None)
    return out


def _target_row(match: Match, quote, fins: dict, klm: dict) -> dict:
    row = {"market": match.market, "code": match.code,
           "name": match.name}
    for col in ("price", "pe_ttm", "pb", "market_cap", "pct_chg"):
        if quote and quote.get(col) is not None:
            row[col] = quote.get(col)
    row.update({k: v for k, v in (fins or {}).items()
                if v is not None and not (isinstance(v, float)
                                          and pd.isna(v))})
    row.update({k: v for k, v in klm.items() if not k.startswith("_")})
    rev = row.get("revenue") or row.get("rev")
    if rev and row.get("market_cap"):
        # HK F10 revenue is CNY while market cap is HKD — HK peers carry
        # no ps column at all, so only derive ps where currencies match.
        if match.market in ("A", "US"):
            row["ps"] = row["market_cap"] / rev
    return row


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def analyze_stock(match: Match, snapshot_dir=None, live: bool = True,
                  horizon: str | None = None) -> dict:
    """Full analysis for one resolved stock."""
    snap = None
    if snapshot_dir is not None:
        snap = Path(snapshot_dir)
    else:
        try:
            snap = resolve_snapshot()
        except FileNotFoundError:
            snap = None
    result = {"match": match,
              "snapshot": snap.name if snap else None,
              "horizon": horizon,
              "warnings": []}

    quote = live_quote(match) if live else None
    if quote is None:
        result["warnings"].append(
            "live quote unavailable; using snapshot/fallback data")
    result["quote"] = quote

    fins = target_fundamentals(match, snap) if snap else {}
    if not fins and match.market == "HK":
        fins = target_fundamentals(match, None)
    if not fins:
        result["warnings"].append("no fundamentals available")
    result["fundamentals"] = fins
    result["cashflow_factors"] = _snapshot_factors(snap, match.market,
                                                   match.code)

    klm = target_kline_metrics(match, snap)
    result["kline"] = klm

    pct, scores, composite_pct = {}, {}, None
    prof = {}
    if snap is not None:
        peers = build_peer_set(snap, match.market)
        peers = peers[peers["code"].astype(str) != match.code]
        if peers.empty:
            result["warnings"].append("empty peer universe")
        else:
            row = _target_row(match, quote, fins, klm)
            row.update({k: v for k, v in result["cashflow_factors"].items()
                        if v is not None
                        and not (isinstance(v, float) and pd.isna(v))})
            frame = pd.concat(
                [peers, pd.DataFrame([row])], ignore_index=True)
            frame = add_pillar_scores(frame)
            scored = apply_composite(
                frame, get_strategy(config.DEFAULT_PRESET).weights,
                min_pillars=1)
            tgt = scored.iloc[-1]
            scores = {}
            for p in PILLARS:
                v = tgt.get(f"{p}_score")
                scores[p] = (None if v is None or pd.isna(v)
                             else round(float(v), 1))
            comp = tgt.get("composite_score")
            if comp is not None and not pd.isna(comp):
                composite_pct = round(float(
                    (scored["composite_score"] < comp).mean() * 100.0), 1)
            for col, _label, lower in EVIDENCE_METRICS:
                if col in frame.columns:
                    p = percentile(tgt.get(col), frame[col], lower)
                    if p is not None:
                        pct[col] = p
            # Four-horizon suitability profile (descriptive: screening
            # gates do not apply; momentum measured per horizon window)
            prof = {}
            for hz in list_horizons():
                scored_h = apply_horizon_score(frame, hz, min_pillars=1)
                comp = scored_h.iloc[-1].get("composite_score")
                if comp is None or pd.isna(comp):
                    continue
                prof[hz.id] = {
                    "score": round(float(comp), 1),
                    "percentile": round(float(
                        (scored_h["composite_score"] < comp).mean()
                        * 100.0), 1),
                }
    result["percentiles"] = pct
    result["scores"] = scores
    result["composite_percentile"] = composite_pct
    result["horizon_profile"] = prof if snap is not None else {}
    result["verdict"] = verdict_band(composite_pct)
    result["risk_flags"] = risk_flags(result)
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _as_of(result: dict) -> str:
    parts = []
    if result.get("quote"):
        parts.append("quote: live")
    rd = (result.get("fundamentals") or {}).get("report_date")
    if rd:
        parts.append(f"fundamentals: {rd}")
    ld = (result.get("kline") or {}).get("_last_date")
    if ld:
        parts.append(f"kline: {ld}")
    return "; ".join(parts) or "unknown"


def _horizon_lines(result: dict) -> list[str]:
    """The four-horizon (or single-horizon) profile block."""
    prof = result.get("horizon_profile") or {}
    if not prof:
        return []
    m = result["match"]
    only = result.get("horizon")
    names = {h.id: h.name for h in list_horizons()}
    order = [h.id for h in list_horizons()]
    entries = [(hid, prof[hid]) for hid in order if hid in prof]
    if only:
        entries = [(hid, v) for hid, v in entries if hid == only]
    weakest = (min(prof, key=lambda k: prof[k]["percentile"])
               if len(prof) > 1 else None)
    lines = [f"horizon profile (vs {m.market} gated universe):"]
    for hid, v in entries:
        mark = "   <- weakest" if hid == weakest else ""
        lines.append(f"  {hid:<11}{names.get(hid, ''):<6}"
                     f"{v['score']:>6.1f}  ({v['percentile']:.0f}th "
                     f"pctile){mark}")
    return lines


def render_brief(result: dict) -> str:
    m = result["match"]
    q = result.get("quote") or {}
    row = _flat_row(result)
    p = result.get("percentiles") or {}
    lines = [f"{m.name}  [{m.market}/{m.code}]"]
    if q.get("price") is not None:
        chg = q.get("pct_chg")
        chg_s = f" ({chg:+.2f}% today)" if chg is not None else ""
        lines.append(f"price: {q['price']:,.2f} "
                     f"{config.MARKET_CURRENCIES[m.market]}{chg_s}")
    lines.append(f"verdict: {result['verdict']}")
    if result.get("composite_percentile") is not None:
        lines.append(f"blended rank: {result['composite_percentile']:.0f}th "
                     f"percentile of the {m.market} gated universe")
    for col, label in (("pe_ttm", "PE"), ("rev_yoy", "rev YoY"),
                       ("roe", "ROE"), ("fcf_yield", "FCF yield"),
                       ("capex_to_ocf", "capex/ocf")):
        v = row.get(col)
        if v is not None and not pd.isna(v):
            extra = f" ({p[col]:.0f}th pctile)" if col in p else ""
            lines.append(f"{label}: {v:,.1f}{extra}")
    h = result.get("horizon")
    if h:
        hh = get_horizon(h)
        lines.append(f"horizon lens: {hh.name} ({hh.window})")
    lines += _horizon_lines(result)
    flags = result["risk_flags"]
    if flags:
        lines.append(f"risk flags: {len(flags)} - " + "; ".join(flags))
    else:
        lines.append("risk flags: 0")
    lines.append(f"data as of: {_as_of(result)}")
    return "\n".join(lines)


def render_evidence(result: dict) -> str:
    m = result["match"]
    row = _flat_row(result)
    p = result.get("percentiles") or {}
    lines = [f"== {m.name} [{m.market}/{m.code}] - evidence ==",
             f"verdict: {result['verdict']}"]
    sc = [f"{k}={v:.0f}" for k, v in (result.get("scores") or {}).items()
          if v is not None]
    if sc:
        lines.append("pillar scores (peer percentiles): " + "  ".join(sc))
    if result.get("composite_percentile") is not None:
        lines.append(f"blended composite: "
                     f"{result['composite_percentile']:.0f}th percentile")
    h = result.get("horizon")
    if h:
        hh = get_horizon(h)
        lines.append(f"horizon lens: {hh.name} ({hh.window})")
    lines += _horizon_lines(result)
    lines += ["", f"{'metric':<20}{'value':>12}{'peer pctile':>13}"]
    for col, label, _lower in EVIDENCE_METRICS:
        v = row.get(col)
        vs = ("-" if v is None or (isinstance(v, float) and pd.isna(v))
              else f"{v:,.2f}")
        ps = f"{p[col]:.0f}" if col in p else "-"
        lines.append(f"{label:<20}{vs:>12}{ps:>13}")
    flags = result["risk_flags"]
    lines += ["", f"risk flags ({len(flags)}):"]
    lines += [f"  - {f}" for f in flags] or ["  none"]
    lines += ["", f"data as of: {_as_of(result)}"]
    return "\n".join(lines)


def to_json(result: dict) -> str:
    m = result["match"]
    payload = {
        "market": m.market, "code": m.code, "name": m.name,
        "snapshot": result.get("snapshot"),
        "verdict": result["verdict"],
        "composite_percentile": result.get("composite_percentile"),
        "horizon": result.get("horizon"),
        "horizon_profile": result.get("horizon_profile"),
        "scores": result.get("scores"),
        "percentiles": result.get("percentiles"),
        "metrics": {k: v for k, v in _flat_row(result).items()
                    if isinstance(v, (int, float, str))
                    and not (isinstance(v, float) and pd.isna(v))},
        "risk_flags": result["risk_flags"],
        "warnings": result["warnings"],
        "data_as_of": _as_of(result),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2,
                      default=str)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def compare_stocks(matches, snapshot_dir=None) -> pd.DataFrame:
    """Side-by-side table of resolved stocks."""
    rows = []
    for m in matches:
        r = analyze_stock(m, snapshot_dir)
        row = _flat_row(r)
        rows.append({
            "market": m.market, "code": m.code, "name": m.name,
            "price": row.get("price"),
            "pe_ttm": row.get("pe_ttm"),
            "pe_pctile": (r["percentiles"] or {}).get("pe_ttm"),
            "rev_yoy": row.get("rev_yoy"),
            "roe": row.get("roe"),
            "composite_pctile": r["composite_percentile"],
            "verdict": r["verdict"],
            "risks": len(r["risk_flags"]),
        })
    return pd.DataFrame(rows)
