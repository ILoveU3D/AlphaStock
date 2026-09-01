"""Symbol resolution: free text -> market/code/name matches.

Chain: exact code forms (600519 / 02555.HK / AAPL) -> snapshot quote
name search (exact > substring > fuzzy) -> Eastmoney smartbox live
search, which works even with no snapshot on disk.
"""

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config
from .fetch.http import Fetcher

SB = Fetcher({"User-Agent": config.EM_UA}, "SB")
SMARTBOX_URL = "https://searchapi.eastmoney.com/api/suggest/get"
SMARTBOX_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
SMARTBOX_MKT = {"0": "A", "1": "A", "116": "HK",
                "105": "US", "106": "US", "107": "US"}


@dataclass
class Match:
    market: str
    code: str
    name: str
    score: float
    market_id: str = ""

    def label(self) -> str:
        return f"{self.name} ({self.market}/{self.code})"


def parse_code_form(query: str):
    """(market, code, market_id) when the query is a code form, else None.

    market_id is the Eastmoney push2 prefix needed for live quotes
    (A: 1=SH / 0=SZ+BJ, HK: 116; US is exchange-dependent and left
    blank — smartbox or the snapshot fills it in).
    """
    q = query.strip().lower()
    m = re.fullmatch(r"(?:sh|sz|bj)?(\d{6})(?:\.(?:sh|sz|bj))?", q)
    if m:
        code = m.group(1)
        return ("A", code, "1" if code[0] == "6" else "0")
    m = re.fullmatch(r"(?:hk)?(\d{1,5})(?:\.hk)?", q)
    if m:
        return ("HK", m.group(1).zfill(5), "116")
    m = re.fullmatch(r"(?:us)?([a-z]{1,6})", q)
    if m:
        return ("US", query.strip().upper(), "")
    return None


def search_frames(query: str, frames: dict) -> list:
    """Name matches across {market: DataFrame with code/name}."""
    q = query.strip()
    if not q:
        return []
    out = []
    for market, df in frames.items():
        if df is None or df.empty or "name" not in df.columns:
            continue
        names = df["name"].astype(str)
        exact = df[names == q]
        if not exact.empty:
            for _, r in exact.iterrows():
                out.append(Match(market, str(r["code"]), str(r["name"]),
                                 100.0, str(r.get("market_id") or "")))
            continue
        for _, r in df[names.str.contains(re.escape(q), na=False)].iterrows():
            out.append(Match(market, str(r["code"]), str(r["name"]),
                             80.0, str(r.get("market_id") or "")))
        for _, r in df[names.map(lambda n:
                                 difflib.SequenceMatcher(None, n, q).ratio()
                                 >= 0.6)].iterrows():
            ratio = difflib.SequenceMatcher(None, str(r["name"]), q).ratio()
            out.append(Match(market, str(r["code"]), str(r["name"]),
                             round(ratio * 60.0, 1),
                             str(r.get("market_id") or "")))
    out.sort(key=lambda m: -m.score)
    return out


def load_snapshot_frames(snapshot_dir=None) -> dict:
    """{market: quotes DataFrame} from a snapshot dir (latest default)."""
    from .report import resolve_snapshot
    snap = Path(snapshot_dir) if snapshot_dir else resolve_snapshot()
    frames = {}
    for market in config.MARKETS:
        p = snap / f"{market.lower()}_quotes.csv"
        if p.exists():
            frames[market] = pd.read_csv(p, dtype={"code": str})
    return frames


def search_smartbox(query: str, count: int = 8) -> list:
    """Live Eastmoney suggest search; empty list on failure."""
    d = SB.get_json(SMARTBOX_URL, params={
        "input": query, "type": "14", "token": SMARTBOX_TOKEN,
        "count": count}, retries=2)
    items = ((d or {}).get("QuotationCodeTable") or {}).get("Data") or []
    out = []
    for it in items:
        market = SMARTBOX_MKT.get(str(it.get("MktNum") or ""))
        code = str(it.get("Code") or "").strip()
        name = str(it.get("Name") or "").strip()
        if not market or not code or not name:
            continue
        if market == "HK":
            code = code.zfill(5)
        out.append(Match(market, code, name, 50.0,
                         str(it.get("MktNum") or "")))
    return out


def resolve(query: str, snapshot_dir=None, live: bool = True) -> list:
    """All candidate matches for a query, best first."""
    out = []
    form = parse_code_form(query)
    if form:
        out.append(Match(form[0], form[1], query.strip(), 120.0, form[2]))
    try:
        frames = load_snapshot_frames(snapshot_dir)
    except FileNotFoundError:
        frames = {}
    out += search_frames(query, frames)
    if live and len(out) < 3:
        seen = {(m.market, m.code) for m in out}
        out += [m for m in search_smartbox(query)
                if (m.market, m.code) not in seen]
    best = {}
    for m in out:
        key = (m.market, m.code)
        if key not in best or m.score > best[key].score:
            best[key] = m
    res = sorted(best.values(), key=lambda m: -m.score)
    # enrich code-form matches with real display names
    for m in res:
        df = frames.get(m.market)
        if df is not None and not df.empty and "name" in df.columns:
            hit = df[df["code"].astype(str) == m.code]
            if not hit.empty:
                m.name = str(hit.iloc[0]["name"])
                if not m.market_id and "market_id" in hit.columns:
                    m.market_id = str(hit.iloc[0].get("market_id") or "")
    return res
