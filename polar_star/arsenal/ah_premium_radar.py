"""ah-premium-radar — house-unique dual-market lens: A/H dual-listed
premium level + 60-day mean-reversion z-score.

premium_% = ((price_A_CNY / fx_hkdcny) / price_HK_HKD - 1) * 100 —
fx_hkdcny (CNY per 1 HKD) from snap/manifest.json; the A leg is
converted into HKD before the ratio.  premium_z = (last - mean60) /
std60 (ddof=0) of the daily premium series rebuilt from both legs'
klines on inner-joined dates, last 60 common bars; None when < 60
common bars or a flat (zero-std) window.

CANONICAL-FORM GAP (declared): the Engle-Granger cointegration test
with MacKinnon critical values is the canonical pair gate — parked as a
future upgrade until a scipy-free critical-value table is wired; the
current form is level + z (a mean-reversion RADAR, never a traded
signal by itself).

Pair discovery is best-effort name normalization between master A and
HK rows (strip 股份/有限公司/集团/H股/holdings/ltd/...); ambiguous
matches are logged in the output, never silently guessed.  An explicit
``pairs=[("A:600028", "HK:00386")]`` parameter overrides discovery.
Missing leg/kline/manifest -> data_gap per pair.
"""

import json
import re
from pathlib import Path

import pandas as pd

from .low_beta_bab import close_series, load_kline
from .statsutil import num_or_none

Z_WINDOW = 60

_CN_TOKENS = ("股份有限公司", "有限责任公司", "有限公司", "股份",
              "集团", "控股", "公司", "h股", "a股")
_EN_TOKENS = {"international", "holdings", "holding", "limited", "ltd",
              "corporation", "corp", "company", "co", "inc", "group",
              "plc", "the", "sa", "ag"}


def normalize_name(name) -> str:
    """Best-effort A/H name normalization for pair discovery."""
    s = str(name or "").lower()
    for t in _CN_TOKENS:
        s = s.replace(t, "")
    s = re.sub(r"[^0-9a-z一-鿿]+", " ", s)
    return "".join(w for w in s.split() if w not in _EN_TOKENS)


def _manifest_fx(snap) -> float | None:
    p = Path(snap) / "manifest.json" if snap is not None else None
    if p is None or not p.exists():
        return None
    try:
        return num_or_none(json.loads(p.read_text(
            encoding="utf-8")).get("fx_hkdcny"))
    except (OSError, json.JSONDecodeError):
        return None


def premium_series(snap, a_code, hk_code, fx,
                   bars: int = Z_WINDOW) -> pd.Series | None:
    """Daily premium_% series on the last `bars` common kline dates."""
    if fx is None or fx <= 0:
        return None
    ca = close_series(load_kline(snap, "A", a_code))
    ch = close_series(load_kline(snap, "HK", hk_code))
    if ca is None or ch is None:
        return None
    pair = pd.concat([ca.rename("a"), ch.rename("h")],
                     axis=1, join="inner").dropna().tail(bars)
    if len(pair) < bars:
        return None
    return (pair["a"] / fx) / pair["h"] * 100.0 - 100.0


def premium_z(prem: pd.Series | None) -> float | None:
    """(last - mean) / std(ddof=0); None for a flat window."""
    if prem is None or len(prem) < 2:
        return None
    sd = float(prem.std(ddof=0))
    if sd == 0:
        return None
    return float((prem.iloc[-1] - prem.mean()) / sd)


def discover_pairs(master: pd.DataFrame) -> tuple:
    """(pairs, ambiguous) from name normalization; pairs =
    [(a_code, hk_code, name)] with a unique match on both sides."""
    a = master[master["market"].astype(str) == "A"]
    hk = master[master["market"].astype(str) == "HK"]
    amap: dict[str, list] = {}
    for _, r in a.iterrows():
        n = normalize_name(r.get("name"))
        if n:
            amap.setdefault(n, []).append(r)
    hmap: dict[str, list] = {}
    for _, r in hk.iterrows():
        n = normalize_name(r.get("name"))
        if n:
            hmap.setdefault(n, []).append(r)
    pairs, ambiguous = [], []
    for n, arows in amap.items():
        hrows = hmap.get(n)
        if not hrows:
            continue
        if len(arows) == 1 and len(hrows) == 1:
            pairs.append((str(arows[0]["code"]), str(hrows[0]["code"]),
                          str(arows[0].get("name"))))
        else:
            ambiguous.append({"name": n,
                              "a_codes": [str(r["code"]) for r in arows],
                              "hk_codes": [str(r["code"]) for r in hrows]})
    return pairs, ambiguous


def _pair_reading(master, snap, fx, a_code, hk_code, name="") -> dict:
    """Level (master prices) + z (klines) for one pair; data_gap honest."""
    rec = {"a_code": str(a_code), "hk_code": str(hk_code),
           "name": name or None, "premium_pct": None,
           "premium_z": None, "data_gap": None}
    a = master[(master["market"].astype(str) == "A")
               & (master["code"].astype(str) == str(a_code))]
    h = master[(master["market"].astype(str) == "HK")
               & (master["code"].astype(str) == str(hk_code))]
    if not len(a) or not len(h):
        rec["data_gap"] = "leg missing from master.csv"
        return rec
    if not rec["name"]:
        rec["name"] = (None if pd.isna(a.iloc[0].get("name"))
                       else str(a.iloc[0]["name"]))
    pa = num_or_none(a.iloc[0].get("price"))
    ph = num_or_none(h.iloc[0].get("price"))
    if fx and pa and ph and ph > 0:
        rec["premium_pct"] = (pa / fx) / ph * 100.0 - 100.0
    prem = premium_series(snap, a_code, hk_code, fx)
    rec["premium_z"] = premium_z(prem)
    if rec["premium_pct"] is None and rec["premium_z"] is None:
        rec["data_gap"] = "no fx/price and <60 common kline bars"
    elif rec["premium_z"] is None:
        rec["data_gap"] = "level only (<60 common kline bars or flat)"
    return rec


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, pairs=None, top: int = 10) -> dict:
    """Top divergent A/H pairs (|premium_z| desc) + target pair reading."""
    master = ctx["master"]
    snap = ctx.get("snap")
    fx = _manifest_fx(snap)
    if pairs:
        found = [(a.split(":", 1)[1], h.split(":", 1)[1], "")
                 for a, h in pairs]
        ambiguous = []
    else:
        found, ambiguous = discover_pairs(master)
    recs = [_pair_reading(master, snap, fx, a, h, n)
            for a, h, n in found]
    divergent = sorted(
        (r for r in recs if r["premium_z"] is not None),
        key=lambda r: -abs(r["premium_z"]))[:top]
    out = {
        "weapon": "ah-premium-radar",
        "anchor": "A/H 溢价水平 + 60 日均值回复 z (配对内日期 inner-join); "
                  "协整 MacKinnon 检验为声明的将来升级, 当前=雷达非信号; "
                  "名称为 best-effort 归一化, 歧义记档不瞎猜",
        "fx_hkdcny": fx,
        "pairs_found": int(len(recs)),
        "ambiguous": ambiguous,
        "top_divergent": divergent,
        "pairs": recs,
    }
    row = ctx.get("row")
    if row is not None:
        rm, rc = str(row["market"]), str(row["code"])
        for r in recs:
            if (rm == "A" and r["a_code"] == rc) or \
               (rm == "HK" and r["hk_code"] == rc):
                out["row"] = r
                break
    return out
