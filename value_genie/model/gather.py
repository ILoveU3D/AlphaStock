"""Gather raw material for one company into models/<mkt>/<code>/raw/.

The machine's hands for the AI's modeling work (user mandate 2026-10-03:
AI models one company at a time; scripts are the hands, never the
modeler). Gathers full listing-history statements, intel events, the
company's own profile text, and peers. Never writes model.json — the
understanding layer is the AI's alone.

All sources fail-closed: a failed fetch leaves existing raw untouched
and reports a gap. Raw is regenerable; model.json is the asset.
"""

import json

from .. import config
from ..users import normalize_code
from . import history as mh
from . import store

# full listing history cap (user mandate: every annual report since IPO)
FULL_HISTORY_LIMIT = 100

# peer columns exported for cross-reading (financials + valuation)
_PEER_COLS = ("market", "code", "name", "industry", "market_cap", "price",
              "pe_ttm", "pb", "ps", "roe", "gross_margin", "net_margin",
              "debt_ratio", "dividend_yield", "rev_yoy", "fcf_yield")


def _dump(market: str, code: str, name: str, payload) -> "str | None":
    d = store.raw_dir(market, code)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    from ..atomic import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False,
                                    indent=2, default=str))
    return str(p)


def gather_history(market: str, code: str) -> tuple:
    """Full listing-history statements -> raw/history.json."""
    h = mh.fetch_history(market, code, limit=FULL_HISTORY_LIMIT)
    if h is None:
        return None, "history source returned nothing (fail-closed)"
    return _dump(market, code, "history.json", h), None


def gather_profile(market: str, code: str) -> tuple:
    """Company's own profile text -> raw/profile_raw.json (also kept in
    the classic data/profiles/raw store by update_raw)."""
    from ..fetch import profiles as fp
    raw = fp.update_raw(market, code)
    if raw is None:
        return None, "profile source returned nothing (fail-closed)"
    return _dump(market, code, "profile_raw.json", raw), None


def gather_annual(market: str, code: str) -> tuple:
    """Annual-report text material (MD&A review, segment breakdown,
    business scope, core themes, sell-side consensus, exec bios;
    US: 10-K Item 1/7 slices) -> raw/annual.json."""
    from ..fetch import annual as fa
    if market == "HK":
        return None, ("HK annual-report text is PDF-only (披露易); no "
                      "PDF parser in the global Python — declared gap")
    doc = fa.fetch_annual(market, code)
    if doc is None:
        return None, "annual-text source returned nothing (fail-closed)"
    return _dump(market, code, "annual.json", doc), None


def gather_filings(market: str, code: str) -> tuple:
    """Disclosure PDF full texts -> raw/filings/<file>.txt with an index
    at raw/filings.json. Full texts live in a SUBDIR so the lint text
    ratio (raw/*.json only) stays meaningful. A: cninfo annual reports
    (MD&A section sliced) + prospectus; US: covered by annual.json
    (10-K HTML); HK: HKEX PDFs not yet probed — gap."""
    if market != "A":
        return None, ("filings full-text is A-share only for now "
                      "(US: see annual.json 10-K slices; HK: HKEX "
                      "PDFs not yet probed)")
    from ..atomic import atomic_write_text
    from ..fetch import filings as ff
    if ff._pypdf() is None:
        return None, ("pypdf not installed in the global Python — "
                      "user installs it to unlock disclosure PDFs")
    doc = ff.fetch_filings_a(code)
    if doc is None:
        return None, "cninfo discovery/extraction failed (fail-closed)"
    d = store.raw_dir(market, code)
    fdir = d / "filings"
    fdir.mkdir(parents=True, exist_ok=True)
    index = {"id": doc["id"], "source": doc["source"],
             "reports": [], "gaps": list(doc["gaps"])}
    for i, rep in enumerate(doc["reports"]):
        stem = f"{rep['kind']}_{i}" if rep["kind"] == "annual" \
            else rep["kind"]
        fpath = fdir / f"{stem}.txt"
        atomic_write_text(fpath, rep.pop("text"))
        entry = {k: v for k, v in rep.items() if k != "mdna"}
        entry["file"] = f"filings/{stem}.txt"
        mdna = rep.get("mdna") or ""
        if mdna:
            mpath = fdir / f"{stem}_mdna.txt"
            atomic_write_text(mpath, mdna)
            entry["mdna_file"] = f"filings/{stem}_mdna.txt"
            entry["mdna_chars"] = len(mdna)
        index["reports"].append(entry)
    return _dump(market, code, "filings.json", index), None


def gather_intel(market: str, code: str, snap_dir) -> tuple:
    """Intel events for this company from the snapshot event radar ->
    raw/intel.json (empty list is a valid result, not a failure)."""
    import pandas as pd
    snap = snap_dir
    er = snap / "event_radar.csv"
    if not er.exists():
        return None, f"event_radar.csv missing in snapshot {snap.name}"
    df = pd.read_csv(er, dtype=str)
    hit = df[(df["market"].astype(str) == market)
             & (df["code"].astype(str) == str(code))]
    rows = hit.to_dict("records")
    return _dump(market, code, "intel.json", rows), None


def gather_peers(market: str, code: str, snap_dir,
                 limit: int = 10,
                 explicit: list | None = None) -> tuple:
    """Same-industry peers with financials/valuation -> raw/peers.json.

    ``explicit`` = AI-chosen peer codes (the modeler knows the true
    comparables — e.g. 寒武纪/海光 for a new GPU listing absent from
    master.csv); falls back to industry+market-cap proximity."""
    from ..report import load_master
    from . import comps as mcomps
    master = load_master(snap_dir)
    row = master[(master["market"].astype(str) == market)
                 & (master["code"].astype(str) == str(code))]
    cols = [c for c in _PEER_COLS if c in master.columns]
    if explicit:
        picked = master[(master["market"].astype(str) == market)
                        & (master["code"].astype(str).isin(
                            [str(x) for x in explicit]))]
        found = set(picked["code"].astype(str))
        missing = [x for x in explicit if str(x) not in found]
        payload = {
            "target": (row.iloc[0][cols].to_dict() if len(row)
                       else {"market": market, "code": str(code),
                             "note": "target absent from master.csv"}),
            "peers": picked[cols].to_dict("records"),
            "selection": "ai-explicit",
        }
        gap = (f"explicit peers not in master: {missing}"
               if missing else None)
        return _dump(market, code, "peers.json", payload), gap
    if not len(row):
        return None, ("target absent from master.csv — pass --peers "
                      "with AI-chosen comparables")
    industry = row.iloc[0].get("industry")
    peers = mcomps.select_peers(master, market, code, industry,
                                limit=limit)
    tgt_cols = [c for c in _PEER_COLS if c in master.columns]
    payload = {
        "target": row.iloc[0][tgt_cols].to_dict(),
        "peers": peers[cols].to_dict("records") if cols else [],
        "selection": "industry-proximity",
    }
    return _dump(market, code, "peers.json", payload), None


def gather(market: str, code: str, snap_dir=None,
           force: bool = False, peers: list | None = None) -> dict:
    """Aggregate all raw material for one company. Returns a report
    {paths, gaps}; individual source failures never stop the others.
    ``peers`` = AI-chosen comparable codes (explicit peer set)."""
    code = normalize_code(market, code)
    if snap_dir is None:
        from ..report import resolve_snapshot
        snap_dir = resolve_snapshot(None)
    d = store.raw_dir(market, code)
    report = {"id": f"{market}:{code}", "raw_dir": str(d),
              "gathered": {}, "gaps": []}

    def _want(fname):
        return force or not (d / fname).exists()

    if _want("history.json"):
        p, gap = gather_history(market, code)
        report["gathered"]["history"] = p
        if gap:
            report["gaps"].append(f"history: {gap}")
    if _want("profile_raw.json"):
        p, gap = gather_profile(market, code)
        report["gathered"]["profile_raw"] = p
        if gap:
            report["gaps"].append(f"profile: {gap}")
    if _want("annual.json"):
        try:
            p, gap = gather_annual(market, code)
        except Exception as exc:
            p, gap = None, str(exc)
        report["gathered"]["annual"] = p
        if gap:
            report["gaps"].append(f"annual: {gap}")
    if _want("filings.json"):
        try:
            p, gap = gather_filings(market, code)
        except Exception as exc:
            p, gap = None, str(exc)
        report["gathered"]["filings"] = p
        if gap:
            report["gaps"].append(f"filings: {gap}")
    if _want("intel.json"):
        try:
            p, gap = gather_intel(market, code, snap_dir)
        except Exception as exc:  # radar unreadable -> gap, not crash
            p, gap = None, str(exc)
        report["gathered"]["intel"] = p
        if gap:
            report["gaps"].append(f"intel: {gap}")
    if _want("peers.json"):
        try:
            p, gap = gather_peers(market, code, snap_dir,
                                  explicit=peers)
        except Exception as exc:
            p, gap = None, str(exc)
        report["gathered"]["peers"] = p
        if gap:
            report["gaps"].append(f"peers: {gap}")
    return report
