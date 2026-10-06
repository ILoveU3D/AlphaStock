"""Model persistence: history / assumptions / result under models/ (LOCAL-
ONLY, untracked — same rule as profiles/). Also the DCF overlay hook
(D3-parallel): a built model's probability-weighted upside replaces the
reverse-DCF anchor in core_dcf for that row only.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import config
from ..users import normalize_code

SCHEMA_VERSION = 1

# marker written into core_gaps when a model supplies the dcf core
DCF_MODELED = "dcf modeled (model build)"

_SCENARIO_DRIVER_KEYS = ("revenue_growth", "ebit_margin", "da_pct_rev",
                         "capex_pct_rev", "nwc_pct_drev", "prob")
_TOP_KEYS = ("version", "horizon_years", "wacc", "terminal_g", "tax_rate",
             "net_debt", "shares", "currency", "price_fx")


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Paths & persistence
# ---------------------------------------------------------------------------
def models_dir() -> Path:
    return Path(config.MODELS_DIR)


def _stock_dir(market: str, code: str) -> Path:
    code = normalize_code(market, code)
    return models_dir() / market.lower() / code


def history_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "history.json"


def assumptions_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "assumptions.json"


def result_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "result.json"


def raw_dir(market: str, code: str) -> Path:
    """Drop-in dir for audit-opinion / DD material text the AI reads."""
    return _stock_dir(market, code) / "raw"


def _hash_years(years: list) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(years, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:12]


def _load_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt {what} file {path}: {exc}") from None
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(
            f"corrupt {what} file {path}: top level must be an object "
            f"with an 'id'")
    return data


def _save(path: Path, data: dict) -> Path:
    from ..atomic import atomic_write_text
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def new_history(market: str, code: str, name: str = "", source: str = "",
                currency: str = "", years: list | None = None,
                gaps: list | None = None) -> dict:
    code = normalize_code(market, code)
    years = list(years or [])
    return {
        "id": f"{market}:{code}", "market": market, "code": code,
        "name": name, "fetched_at": _now(), "source": source,
        "currency": currency, "years": years,
        "history_hash": _hash_years(years), "gaps": list(gaps or []),
    }


def save_history(h: dict) -> Path:
    return _save(history_path(h["market"], h["code"]), h)


def load_history(market: str, code: str) -> dict | None:
    p = history_path(market, code)
    return _load_json(p, "model history") if p.exists() else None


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------
def _median(vals: list) -> float | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _pct(numer, denom) -> float | None:
    if numer is None or not denom:
        return None
    return numer / denom


def default_assumptions(market: str, code: str) -> dict:
    """Derive default drivers from history medians (last 3 years); missing
    fields fall back to config constants and are declared in gaps."""
    h = load_history(market, code)
    if h is None:
        raise ValueError(f"no history for {market}:{code} — "
                         f"run `model fetch` first")
    years = h["years"][-3:]
    gaps = []

    growths, margins, das, capexs, nwcs = [], [], [], [], []
    prev_rev = None
    for y in (h["years"][-4:] if len(h["years"]) >= 4 else h["years"]):
        rev = y.get("revenue")
        if prev_rev and rev:
            growths.append(rev / prev_rev - 1.0)
            nwcs.append(config.MODEL_FALLBACK_NWC_PCT)
        prev_rev = rev
        m = _pct(y.get("ebit"), rev)
        if m is not None:
            margins.append(m)
        d = _pct(y.get("da"), rev)
        if d is not None:
            das.append(d)
        c = _pct(y.get("capex"), rev)
        if c is not None:
            capexs.append(c)

    g0 = _median(growths)
    m0 = _median(margins)
    if g0 is None:
        g0 = 0.05
        gaps.append("no revenue history -> base growth defaults to 5%")
    if m0 is None:
        m0 = 0.15
        gaps.append("no ebit history -> base margin defaults to 15%")
    da = _median(das)
    if da is None:
        da = config.MODEL_FALLBACK_DA_PCT
        gaps.append("no da history -> fallback da_pct_rev")
    capex = _median(capexs)
    if capex is None:
        capex = config.MODEL_FALLBACK_CAPEX_PCT
        gaps.append("no capex history -> fallback capex_pct_rev")

    n = config.MODEL_HISTORY_YEARS
    fade = [round(g0 * (1 - 0.15 * i), 4) for i in range(n)]  # 逐年衰减15%
    margins_path = [round(m0, 4)] * n
    last = h["years"][-1]

    def _scenario(scale_g, scale_m, prob):
        return {"prob": prob,
                "revenue_growth": [round(g * scale_g, 4) for g in fade],
                "ebit_margin": [round(m * scale_m, 4) for m in margins_path],
                "da_pct_rev": round(da, 4), "capex_pct_rev": round(capex, 4),
                "nwc_pct_drev": _median(nwcs) or config.MODEL_FALLBACK_NWC_PCT}

    return {
        "id": h["id"], "market": h["market"], "code": h["code"],
        "version": SCHEMA_VERSION, "updated_at": _now(),
        "horizon_years": n, "wacc": config.DCF_DISCOUNT,
        "terminal_g": config.DCF_TERMINAL_G, "tax_rate": 0.15,
        "currency": h.get("currency") or "",
        "net_debt": (last.get("debt") or 0) - (last.get("cash") or 0)
        if last.get("debt") is not None or last.get("cash") is not None
        else None,
        "shares": last.get("shares"),
        "scenarios": {
            "bear": _scenario(0.5, 0.8, config.MODEL_DEFAULT_PROBS["bear"]),
            "base": _scenario(1.0, 1.0, config.MODEL_DEFAULT_PROBS["base"]),
            "bull": _scenario(1.5, 1.15, config.MODEL_DEFAULT_PROBS["bull"]),
        },
        "gaps": gaps, "changelog": [],
    }


def save_assumptions(a: dict) -> Path:
    return _save(assumptions_path(a["market"], a["code"]), a)


def load_assumptions(market: str, code: str) -> dict | None:
    p = assumptions_path(market, code)
    return _load_json(p, "model assumptions") if p.exists() else None


def set_assumptions(market: str, code: str, updates: dict,
                    reason: str) -> dict:
    """Apply dotted-key updates (e.g. 'base.revenue_growth', 'wacc');
    every change appends a changelog entry — reason is mandatory."""
    if not reason or not reason.strip():
        raise ValueError("--reason is required for every assumption change")
    a = load_assumptions(market, code)
    if a is None:
        raise ValueError(f"no assumptions for {market}:{code} — "
                         f"run `model build` first (defaults are generated)")
    for key, val in updates.items():
        parts = key.split(".")
        if parts[0] in config.MODEL_SCENARIOS:
            if len(parts) != 2 or parts[1] not in _SCENARIO_DRIVER_KEYS:
                raise ValueError(f"unknown assumption key: {key}")
            old = a["scenarios"][parts[0]][parts[1]]
            a["scenarios"][parts[0]][parts[1]] = val
        elif len(parts) == 1 and key in _TOP_KEYS and key != "version":
            old = a.get(key)
            a[key] = val
        else:
            raise ValueError(f"unknown assumption key: {key}")
        a.setdefault("changelog", []).append(
            {"at": _now(), "key": key, "from": old, "to": val,
             "reason": reason.strip()})
    a["updated_at"] = _now()
    save_assumptions(a)
    return a


# ---------------------------------------------------------------------------
# Results & staleness
# ---------------------------------------------------------------------------
def save_result(r: dict) -> Path:
    r = dict(r)
    r.setdefault("built_at", _now())
    return _save(result_path(r["market"], r["code"]), r)


def load_result(market: str, code: str) -> dict | None:
    p = result_path(market, code)
    return _load_json(p, "model result") if p.exists() else None


def is_stale(result: dict | None, history: dict | None) -> bool:
    """Result pins the history hash it was built from; a refetched/changed
    history (new reporting period) marks it STALE until rebuilt."""
    if result is None:
        return False
    if history is None:
        return True
    return result.get("history_hash") != history.get("history_hash")


def list_models() -> list:
    """Coverage + staleness report: one row per built model."""
    out = []
    d = models_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*/*/result.json")):
        try:
            r = _load_json(p, "model result")
        except ValueError:
            continue
        h = load_history(r["market"], r["code"])
        out.append({"id": r["id"], "built_at": r.get("built_at"),
                    "weighted_per_share": r.get("weighted_per_share"),
                    "upside_pct": r.get("upside_pct"),
                    "stale": is_stale(r, h)})
    return out


# ---------------------------------------------------------------------------
# DCF overlay hook (D3-parallel to profile.apply_distilled_culture)
# ---------------------------------------------------------------------------
def load_dcf_scores() -> dict:
    """{id: upside_pct} for built, non-stale models."""
    scores = {}
    for row in list_models():
        if row["stale"] or row["upside_pct"] is None:
            continue
        scores[row["id"]] = float(row["upside_pct"])
    return scores


def _anchor_upside(upside_pct: float) -> float:
    lo, hi = config.CORE_ANCHORS["model_upside"]
    v = (upside_pct - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, v))


def apply_modeled_dcf(df: pd.DataFrame, scores: dict | None = None) -> tuple:
    """Overlay modeled dcf scores onto a scored frame (D3-parallel hook).

    Rows WITH a built, non-stale model get ``core_dcf`` = anchored model
    upside, ``core_score`` recomputed, and DCF_MODELED in core_gaps.
    Rows without one keep the reverse-DCF anchor. Returns (frame, count).
    Pure display-layer transform — the stored snapshot is not modified.
    """
    if scores is None:
        scores = load_dcf_scores()
    if not scores or "market" not in df.columns \
            or "code" not in df.columns:
        return df, 0
    out = df.copy()
    ids = out["market"].astype(str) + ":" + out["code"].astype(str)
    mapped = pd.to_numeric(ids.map(scores), errors="coerce")
    has = mapped.notna()
    n = int(has.sum())
    if n == 0:
        return out, 0
    out.loc[has, "core_dcf"] = mapped[has].map(_anchor_upside)
    cols = [c for c in ("core_business", "core_culture", "core_dcf")
            if c in out.columns]
    out["core_score"] = out[cols].mean(axis=1, skipna=True)
    if "core_gaps" in out.columns:
        def _fix(g):
            tag = DCF_MODELED
            if not isinstance(g, str) or not g:
                return tag
            return g if tag in g else g + "; " + tag
        out.loc[has, "core_gaps"] = out.loc[has, "core_gaps"].map(_fix)
    return out, n
