"""One-off backtest: Value Genie gates applied as of 2025-10-08 (HK).

Fundamentals rebuilt from EM HK F10 (12 report periods, CNY amounts);
visibility = period end <= 2025-06-30 (H1 interims published by Oct).
TTM = latest annual + latest cumulative - same cumulative prior year
(fiscal-calendar agnostic). Equity anchored on latest annual
(profit/roe) for ROE-TTM and PB. HKD->CNY at 0.915 (declared).
Prices from klines (2025-10-08 close -> latest). Returns exclude
dividends/costs. Benchmark: 02800 Tracker Fund. Output: console +
data/backtest_20251008_hk.csv
"""

import math
import time
from datetime import date
from pathlib import Path

import pandas as pd

from value_genie.fetch.fundamentals import fetch_hk_f10
from value_genie.fetch.kline import fetch_kline_any
import requests


def tx_hk_shares(code):
    """Shares outstanding via Tencent raw quote (field 44 = mcap in 1e8 HKD).

    Needed because hk_quotes.csv is a filtered universe; toolkit's parsed
    single-quote dict carries no market_cap for HK."""
    try:
        t = requests.get(f"https://qt.gtimg.cn/q=hk{code}", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"}).text
        p = t.split("~")
        if len(p) > 44 and p[44] and p[3]:
            return float(p[44]) * 1e8 / float(p[3])
    except Exception:
        pass
    return None

ASOF = "2025-10-08"
VIS_END = "2025-06-30"   # latest period end visible on ASOF
HKD_CNY = 0.915
SNAP = Path("data/snapshots/20261008")
CACHE = Path("data/backtest_cache") / "hk"
CACHE.mkdir(parents=True, exist_ok=True)
KF_CACHE = Path("data/backtest_cache") / "klines_hk"
KF_CACHE.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# HK F10 with as-of visibility
# ---------------------------------------------------------------------------
def f10(code):
    f = CACHE / f"{code}.csv"
    if f.exists():
        try:
            return pd.read_csv(f, dtype={"code": str})
        except Exception:
            pass
    df = fetch_hk_f10(code)
    time.sleep(0.1)
    if df is not None and len(df):
        df.to_csv(f, index=False)
    return df


def parse_dt(s):
    try:
        y, m, dd = str(s)[:10].split("-")
        return date(int(y), int(m), int(dd))
    except Exception:
        return None


def yr_before(d):
    try:
        return date(d.year - 1, d.month, d.day)
    except ValueError:
        return date(d.year - 1, d.month, d.day - 1)


def fundamentals_asof(df):
    """TTM metrics visible on ASOF from an F10 frame; None when unusable."""
    df = df.copy()
    df["rd"] = df["report_date"].astype(str).str[:10]
    df = df[df["rd"] <= VIS_END].sort_values("rd")
    if not len(df):
        return None
    latest = df.iloc[-1]
    anns = df[df["report_type"].astype(str).str.contains("年报")]
    if not len(anns):
        return None
    annual = anns.iloc[-1]
    ld, ad = parse_dt(latest["rd"]), parse_dt(annual["rd"])
    if not ld or not ad:
        return None

    def ttm(col):
        v_a = annual[col]
        v_l = latest[col]
        if pd.isna(v_a):
            return None
        if ld == ad:
            return v_a
        py = df[(df["rd"] != latest["rd"])].copy()
        target = yr_before(ld)
        py["gap"] = py["rd"].map(
            lambda s: abs((parse_dt(s) - target).days) if parse_dt(s) else 9999)
        py = py[py["gap"] <= 12]
        if not len(py) or pd.isna(v_l):
            return v_a   # interim-matching failed -> annual only (stale, declared)
        v_p = py.iloc[0][col]
        if pd.isna(v_p):
            return v_a
        return v_a + v_l - v_p

    rev_ttm, ni_ttm, ocf_ttm = ttm("revenue"), ttm("profit"), ttm("ocf")
    eq = (annual["profit"] / (annual["roe"] / 100)
          if pd.notna(annual["profit"]) and annual["roe"] else None)
    return {"rev": rev_ttm, "ni": ni_ttm, "ocf": ocf_ttm, "eq": eq,
            "roe_ttm": (ni_ttm / eq * 100 if ni_ttm is not None and eq
                        else None),
            "gm": latest["gross_margin"], "debt": latest["debt_ratio"],
            "dps": latest["dps_hkd"], "ni_yoy": latest["profit_yoy"],
            "rev_yoy": latest["rev_yoy"]}


# ---------------------------------------------------------------------------
# Klines
# ---------------------------------------------------------------------------
def load_klines(code, em_market=""):
    f = KF_CACHE / f"{code}.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"date": str})
    snap_f = SNAP / "kline" / f"HK_{code}.csv"
    if snap_f.exists():
        df = pd.read_csv(snap_f, dtype={"date": str})
        df.to_csv(f, index=False)
        return df
    df = fetch_kline_any("HK", code, em_market or "", lmt=400)
    if df is not None and len(df) and df["date"].min() <= ASOF:
        df.to_csv(f, index=False)
        return df
    return None


def kline_stats(df):
    df = df.sort_values("date").reset_index(drop=True)
    pre = df[df["date"] <= ASOF]
    if not len(pre):
        return None
    entry = float(pre.iloc[-1]["close"])
    exit_ = float(df.iloc[-1]["close"])
    closes = pre["close"].astype(float)
    ret60 = (entry / float(closes.iloc[-61]) - 1) * 100 if len(closes) > 60 else None
    hi, lo = closes.max(), closes.min()
    pos = (entry - lo) / (hi - lo) * 100 if hi > lo else 50.0
    rets = closes.pct_change().dropna()
    vol = float(rets.std() * math.sqrt(252) * 100) if len(rets) > 20 else None
    return {"entry": entry, "exit": exit_, "exit_date": df.iloc[-1]["date"],
            "ret_pct": (exit_ / entry - 1) * 100, "ret60": ret60,
            "pos": pos, "vol": vol, "bars_pre": len(pre)}


# hk_quotes.csv is a filtered universe (148 rows; BABA/SMIC absent), so
# supplement with a fixed large-cap list; invalid/delisted codes auto-skip
# when F10 or klines come back empty.
MEGA_CODES = """
00001 00002 00003 00005 00006 00011 00012 00016 00019 00027
00175 00241 00288 00291 00322 00386 00388 00390
00688 00700 00728 00762 00857 00883 00939 00941 00981 00992
01024 01066 01088 01093 01113 01171 01177 01211 01288 01339
01347 01357 01398 01478 01800 01801 01810 01876 01898 01919
01928 02007 02015 02018 02238 02269 02318 02319 02328 02331
02359 02382 02600 02601 02611 02628 02899 03328 03690 03888
03908 03988 03993 06030 06160 06186 06618 06690 06837 09618
09626 09633 09658 09868 09888 09922 09961 09987 09988 09999
""".split()


# ---------------------------------------------------------------------------
def main():
    quotes = pd.read_csv(SNAP / "hk_quotes.csv",
                         dtype={"code": str, "market": str})
    top80 = quotes.nlargest(80, "market_cap")
    uni = {}
    for f in sorted((SNAP / "kline").glob("HK_*.csv")):
        uni[f.stem[3:]] = ""
    for _, r in top80.iterrows():
        uni.setdefault(r["code"], r["market"])
    for c in MEGA_CODES:
        uni.setdefault(c, "")
    print(f"universe: {len(uni)} HK tickers")

    rows = []
    for i, (code, mkt) in enumerate(sorted(uni.items()), 1):
        if i % 30 == 0:
            print(f"  [{i}/{len(uni)}] ...")
        kl = load_klines(code, mkt)
        if kl is None:
            continue
        ks = kline_stats(kl)
        if ks is None or ks["bars_pre"] < 30:
            continue
        fm = f10(code)
        if fm is None:
            continue
        fnd = fundamentals_asof(fm)
        if not fnd or fnd["ni"] is None or not fnd["eq"]:
            continue
        q = quotes[quotes["code"] == code]
        if len(q) and q.iloc[0]["market_cap"]:
            shares = q.iloc[0]["market_cap"] / q.iloc[0]["price"]
        else:
            shares = tx_hk_shares(code)
            if not shares:
                continue
        mcap_hkd = shares * ks["entry"]
        mcap = mcap_hkd * HKD_CNY
        ni, eq, rev = fnd["ni"], fnd["eq"], fnd["rev"]
        pe = mcap / ni if ni > 0 else None
        pb = mcap / eq if eq > 0 else None
        ps = mcap / rev if rev else None
        ocfy = fnd["ocf"] / mcap * 100 if fnd["ocf"] is not None else None
        divy = (fnd["dps"] / ks["entry"] * 100
                if pd.notna(fnd["dps"]) and fnd["dps"] else 0.0)
        rows.append({"ticker": code, "entry": ks["entry"],
                     "exit": ks["exit"], "exit_date": ks["exit_date"],
                     "ret_pct": ks["ret_pct"], "mcap": mcap, "pe": pe,
                     "pb": pb, "ps": ps, "roe": fnd["roe_ttm"],
                     "gm": fnd["gm"], "debt": fnd["debt"], "ocfy": ocfy,
                     "divy": divy, "rev_yoy": fnd["rev_yoy"],
                     "ni_yoy": fnd["ni_yoy"], "ret60": ks["ret60"],
                     "pos": ks["pos"], "vol": ks["vol"],
                     "ocf": fnd["ocf"], "dps": fnd["dps"]})
    df = pd.DataFrame(rows)
    print(f"with fundamentals+kline: {len(df)}")

    df["pe_pctl"] = df["pe"].rank(pct=True)
    df["ps_pctl"] = df["ps"].rank(pct=True)
    df["roe_pctl"] = df["roe"].rank(pct=True)
    df["gm_pctl"] = df["gm"].rank(pct=True)
    df["vol_pctl"] = df["vol"].rank(pct=True) * 100
    df["spike"] = df["ni_yoy"] >= 200
    df["borrowed_div"] = (df["dps"].fillna(0) > 0) & (df["ocf"] <= 0)

    lane_a = (df["pe"] > 0) & (df["pe_pctl"] <= 0.25)
    lane_b = ((df["roe"] >= 15) & (df["gm"] >= 40) & (df["debt"] <= 60))
    cand = df[lane_a | lane_b].copy()
    cand = cand[~cand["spike"]]

    def votes(r):
        v = []
        bd = r["borrowed_div"]
        if (not bd and r["roe"] >= 15 and r["gm"] and r["gm"] >= 40
                and r["debt"] and r["debt"] <= 60 and r["ocfy"]
                and r["ocfy"] >= 5):
            v.append("buffett")   # FCF-yield gate dropped: no capex in F10
        if (not bd and r["roe"] >= 20 and r["gm"] and r["gm"] >= 40
                and r["debt"] and r["debt"] <= 50):
            v.append("munger")
        if (not bd and r["pe"] and r["pb"] and r["pe"] * r["pb"] <= 22.5
                and r["debt"] and r["debt"] <= 50 and r["roe"] >= 10):
            v.append("graham")
        if (not bd and r["roe"] >= 20 and r["gm"] and r["gm"] >= 40
                and r["vol_pctl"] <= 60):
            v.append("duan")
        if (not bd and r["roe"] >= 15 and r["debt"] and r["debt"] <= 60
                and r["ocfy"] and r["ocfy"] >= 4 and r["divy"] >= 2.5):
            v.append("sanhuyi")
        if (r["ret60"] is not None and r["ret60"] >= 0 and r["vol_pctl"]
                and r["vol_pctl"] >= 50 and r["pos"] and r["pos"] >= 60):
            v.append("livermore")
        if (r["ret60"] is not None and r["ret60"] >= 0 and r["vol_pctl"]
                and r["vol_pctl"] >= 60):
            v.append("sheng")
        return v

    cand["votes"] = cand.apply(votes, axis=1)
    cand["nv"] = cand["votes"].str.len()
    cand["score"] = (30 * (1 - cand["pe_pctl"]) + 20 * cand["roe_pctl"]
                     + 20 * cand["gm_pctl"] + 15 * cand["ps_pctl"].map(lambda x: 1 - x)
                     + 15 * cand["ocfy"].rank(pct=True))
    cand = cand.sort_values(["nv", "score"], ascending=False)
    cand["artifact"] = cand["ret_pct"].abs() > 300

    cand.to_csv("data/backtest_20251008_hk.csv", index=False)
    df.to_csv("data/backtest_20251008_hk_universe.csv", index=False)

    bench = None
    k = load_klines("02800", "128")
    if k is None:
        k = fetch_kline_any("HK", "02800", "128", lmt=400)
    if k is not None and len(k) and k["date"].min() <= ASOF:
        bench = kline_stats(k)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    show = cand[cand["nv"] >= 2].head(20)
    cols = ["ticker", "nv", "votes", "entry", "exit", "ret_pct", "pe",
            "pb", "roe", "gm", "debt", "ocfy", "divy", "ret60", "artifact"]
    print("\n=== Top HK candidates (>=2 master votes) ===")
    print(show[cols].to_string(index=False,
                               float_format=lambda x: f"{x:.1f}"))
    clean = cand[(cand["nv"] >= 2) & (~cand["artifact"])]
    for n in (5, 10):
        port = clean.head(n)
        if len(port) >= 3:
            beat = (port["ret_pct"] > (bench["ret_pct"] if bench else -1e9)).sum()
            print(f"\nTop-{n} equal-weight return: "
                  f"{port['ret_pct'].mean():.1f}%  "
                  f"(median {port['ret_pct'].median():.1f}%, "
                  f"beat-HSI-tracker {beat}/{len(port)})")
    if bench:
        print(f"02800 (HSI tracker) same window: {bench['ret_pct']:.1f}% "
              f"({bench['entry']:.2f} -> {bench['exit']:.2f})")

    print("\n=== calibration diagnostics ===")
    for code, note in (("00981", "SMIC"), ("01347", "HuaHong"),
                       ("01810", "Xiaomi"), ("00883", "CNOOC"),
                       ("00941", "ChinaMobile"), ("00700", "Tencent"),
                       ("09988", "BABA")):
        r = df[df["ticker"] == code]
        if not len(r):
            print(f"{code} {note}: not in universe/no data")
            continue
        r = r.iloc[0]
        fails = []
        if not (r["roe"] >= 15):
            fails.append(f"roe {r['roe']:.1f}<15")
        if not (pd.notna(r["gm"]) and r["gm"] >= 40):
            fails.append(f"gm {r['gm'] if pd.notna(r['gm']) else float('nan'):.1f}<40")
        if pd.isna(r["pe"]):
            fails.append("PE<=0 (loss)")
        in_cand = len(cand[cand["ticker"] == code]) > 0
        votes_s = (",".join(cand[cand["ticker"] == code].iloc[0]["votes"])
                   if in_cand else "-")
        print(f"{code} {note}: in_pool={in_cand} votes={votes_s} "
              f"ret={r['ret_pct']:.1f}% entry={r['entry']:.2f} "
              f"exit={r['exit']:.2f} gate_fails=[{'; '.join(fails)}]")


if __name__ == "__main__":
    main()
