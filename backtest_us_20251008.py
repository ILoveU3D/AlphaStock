"""One-off backtest: Value Genie gates applied as of 2025-10-08 (US).

Universe = today's 200-name kline pool + top-120 by market cap (selection
bias declared). Fundamentals rebuilt from SEC companyfacts with
filed <= 2025-10-08 visibility filter; TTM over the latest 4 fiscal
quarters (annual fallback for 20-F filers). Prices from klines
(2025-10-08 close -> latest close). Returns exclude dividends and costs.
Output: console summary + data/backtest_20251008_us.csv
"""

import json
import math
import time
from datetime import date
from pathlib import Path

import pandas as pd

from value_genie.fetch.http import SEC
from value_genie.fetch.fundamentals import (load_sec_cik_map,
                                            normalize_us_ticker)
from value_genie.fetch.kline import fetch_kline, fetch_kline_any

ASOF = "2025-10-08"
SNAP = Path("data/snapshots/20261008")
CACHE = Path("data/backtest_cache")
CACHE.mkdir(exist_ok=True)
KF_CACHE = CACHE / "klines"
KF_CACHE.mkdir(exist_ok=True)

REV_C = ["RevenueFromContractWithCustomerExcludingAssessedTax",
         "RevenueFromContractWithCustomerIncludingAssessedTax",
         "Revenues", "SalesRevenueNet"]
NI_C = ["NetIncomeLoss", "ProfitLoss"]
GP_C = ["GrossProfit"]
EQ_C = ["StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
OCF_C = ["NetCashProvidedByUsedInOperatingActivities"]
CAP_C = ["PaymentsToAcquirePropertyPlantAndEquipment"]
DIV_C = ["PaymentsOfDividendsCommonStock",
         "PaymentsOfDividendsAndDividendEquivalents",
         "PaymentsOfDividends"]
COST_C = ["CostOfRevenue"]


def parse_dt(s):
    try:
        y, m, dd = s.split("-")
        return date(int(y), int(m), int(dd))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SEC companyfacts with as-of visibility
# ---------------------------------------------------------------------------
def companyfacts(ticker):
    f = CACHE / f"{normalize_us_ticker(ticker)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    cik = load_sec_cik_map().get(normalize_us_ticker(ticker))
    if not cik:
        return None
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    d = SEC.get_json(url, timeout=30, retries=2)
    time.sleep(0.12)
    if d:
        f.write_text(json.dumps(d), encoding="utf-8")
    return d


def dur_entries(d, concepts):
    """Duration facts from the freshest-covering concept in the chain.

    Issuers switch XBRL concepts over time (GOOGL: ExAssessedTax ->
    Revenues in 2025), so picking the first concept that merely exists
    can lock onto a discontinued, stale series. Pick the concept whose
    visible facts reach the latest period end; ties keep chain order.
    """
    gaap = (d or {}).get("facts", {}).get("us-gaap", {})
    best_c, best_end = None, ""
    for c in concepts:
        ends = [e.get("end") for e in
                ((gaap.get(c) or {}).get("units") or {}).get("USD") or []
                if e.get("end") and (e.get("filed") or "9999") <= ASOF
                and e["end"] <= ASOF]
        if ends and max(ends) > best_end:
            best_c, best_end = c, max(ends)
    if best_c is None:
        return
    for e in ((gaap.get(best_c) or {}).get("units") or {}).get("USD") or []:
        end, start, filed = e.get("end"), e.get("start"), e.get("filed")
        if not (end and start and filed and e.get("val") is not None):
            continue
        if filed > ASOF or end > ASOF:
            continue
        ed, sd = parse_dt(end), parse_dt(start)
        if not ed or not sd:
            continue
        yield {"end": end, "start": start, "val": e["val"],
               "filed": filed, "days": (ed - sd).days}


def instant_val(d, concepts):
    gaap = (d or {}).get("facts", {}).get("us-gaap", {})
    best = None
    for c in concepts:
        for e in ((gaap.get(c) or {}).get("units") or {}).get("USD") or []:
            end, filed = e.get("end"), e.get("filed")
            if not (end and filed) or e.get("val") is None:
                continue
            if filed > ASOF or end > ASOF:
                continue
            if best is None or end > best["end"]:
                best = {"end": end, "val": e["val"]}
        if best is not None:
            break
    return best["val"] if best else None


def shares_out(d):
    dei = (d or {}).get("facts", {}).get("dei", {})
    best = None
    for e in ((dei.get("EntityCommonStockSharesOutstanding") or {})
              .get("units") or {}).get("shares") or []:
        end, filed = e.get("end"), e.get("filed")
        if not (end and filed) or e.get("val") is None:
            continue
        if filed > ASOF or end > ASOF:
            continue
        if best is None or end > best["end"]:
            best = {"end": end, "val": e["val"]}
    return best["val"] if best else None


def ttm_pair(d, concepts):
    """(ttm, ttm_prev) from latest 8 fiscal quarters; annual fallback."""
    ents = list(dur_entries(d, concepts))
    if not ents:
        return None, None
    q = {}
    for e in ents:
        if 60 <= e["days"] <= 120:
            k = e["end"]
            if k not in q or e["filed"] > q[k]["filed"]:
                q[k] = e
    qs = sorted(q.values(), key=lambda x: x["end"])
    if len(qs) >= 4:
        ttm = sum(x["val"] for x in qs[-4:])
        prev = (sum(x["val"] for x in qs[-8:-4])
                if len(qs) >= 8 else None)
        return ttm, prev
    a = {}
    for e in ents:
        if e["days"] >= 300:
            k = e["end"]
            if k not in a or e["filed"] > a[k]["filed"]:
                a[k] = e
    anns = sorted(a.values(), key=lambda x: x["end"])
    if not anns:
        return None, None
    ttm = anns[-1]["val"]
    prev = anns[-2]["val"] if len(anns) >= 2 else None
    return ttm, prev


# ---------------------------------------------------------------------------
# Klines
# ---------------------------------------------------------------------------
def load_klines(ticker, em_market=""):
    f = KF_CACHE / f"{ticker}.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"date": str})
    snap_f = SNAP / "kline" / f"US_{ticker}.csv"
    if snap_f.exists():
        df = pd.read_csv(snap_f, dtype={"date": str})
        df.to_csv(f, index=False)
        return df
    df = fetch_kline_any("US", ticker, em_market or "", lmt=400)
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
    exit_date = df.iloc[-1]["date"]
    closes = pre["close"].astype(float)
    ret60 = (entry / float(closes.iloc[-61]) - 1) * 100 if len(closes) > 60 else None
    hi, lo = closes.max(), closes.min()
    pos = (entry - lo) / (hi - lo) * 100 if hi > lo else 50.0
    rets = closes.pct_change().dropna()
    vol = float(rets.std() * math.sqrt(252) * 100) if len(rets) > 20 else None
    return {"entry": entry, "exit": exit_, "exit_date": exit_date,
            "ret_pct": (exit_ / entry - 1) * 100, "ret60": ret60,
            "pos": pos, "vol": vol, "bars_pre": len(pre)}


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
def main():
    quotes = pd.read_csv(SNAP / "us_quotes.csv", dtype={"code": str,
                                                        "market": str})
    top120 = quotes.nlargest(120, "market_cap")
    uni = {}
    for f in sorted((SNAP / "kline").glob("US_*.csv")):
        uni[f.stem[3:]] = ""
    for _, r in top120.iterrows():
        uni.setdefault(r["code"], r["market"])

    cik_map = load_sec_cik_map()
    print(f"universe: {len(uni)} tickers")

    rows = []
    for i, (tk, mkt) in enumerate(sorted(uni.items()), 1):
        if i % 40 == 0:
            print(f"  [{i}/{len(uni)}] ...")
        kl = load_klines(tk, mkt)
        if kl is None:
            continue
        ks = kline_stats(kl)
        if ks is None or ks["bars_pre"] < 30:
            continue
        d = companyfacts(tk)
        if not d:
            continue
        rev, rev_p = ttm_pair(d, REV_C)
        ni, ni_p = ttm_pair(d, NI_C)
        gp, _ = ttm_pair(d, GP_C)
        cost, _ = ttm_pair(d, COST_C)
        if gp is None and rev is not None and cost is not None:
            gp = rev - cost  # issuers that tag cost but not GrossProfit
        ocf, _ = ttm_pair(d, OCF_C)
        cap, _ = ttm_pair(d, CAP_C)
        div, _ = ttm_pair(d, DIV_C)
        eq = instant_val(d, EQ_C)
        liab = instant_val(d, ["Liabilities"])
        assets = instant_val(d, ["Assets"])
        sh = shares_out(d)
        if sh is None:
            q = quotes[quotes["code"] == tk]
            if len(q) and q.iloc[0]["market_cap"] and q.iloc[0]["price"]:
                sh = q.iloc[0]["market_cap"] / q.iloc[0]["price"]
        if not (rev and ni is not None and eq and sh and assets):
            continue
        mcap = sh * ks["entry"]
        roe = ni / eq * 100
        gm = gp / rev * 100 if gp and rev else None
        debt = liab / assets * 100 if liab and assets else None
        pe = mcap / ni if ni > 0 else None
        pb = mcap / eq if eq > 0 else None
        ps = mcap / rev if rev else None
        ocfy = ocf / mcap * 100 if ocf is not None else None
        fcf = (ocf - cap) if (ocf is not None and cap is not None) else None
        fcfy = fcf / mcap * 100 if fcf is not None else None
        divy = div / mcap * 100 if div else 0.0
        rev_yoy = (rev - rev_p) / abs(rev_p) * 100 if rev_p else None
        ni_yoy = ((ni - ni_p) / abs(ni_p) * 100
                  if ni_p and ni_p > 0 else None)
        rows.append({"ticker": tk, "entry": ks["entry"], "exit": ks["exit"],
                     "exit_date": ks["exit_date"], "ret_pct": ks["ret_pct"],
                     "mcap": mcap, "pe": pe, "pb": pb, "ps": ps, "roe": roe,
                     "gm": gm, "debt": debt, "ocfy": ocfy, "fcfy": fcfy,
                     "divy": divy, "rev_yoy": rev_yoy, "ni_yoy": ni_yoy,
                     "ret60": ks["ret60"], "pos": ks["pos"], "vol": ks["vol"],
                     "fcf": fcf, "div": div or 0.0})
    df = pd.DataFrame(rows)
    print(f"with fundamentals+kline: {len(df)}")

    # cross-sectional percentiles (within backtest universe)
    df["pe_pctl"] = df["pe"].rank(pct=True)
    df["ps_pctl"] = df["ps"].rank(pct=True)
    df["roe_pctl"] = df["roe"].rank(pct=True)
    df["gm_pctl"] = df["gm"].rank(pct=True)
    df["fcfy_pctl"] = df["fcfy"].rank(pct=True)
    df["vol_pctl"] = df["vol"].rank(pct=True) * 100

    df["spike"] = df["ni_yoy"] >= 200
    df["borrowed_div"] = (df["div"] > 0) & (df["fcf"] <= 0)

    # funnel lanes
    lane_a = (df["pe"] > 0) & (df["pe_pctl"] <= 0.25)
    lane_b = ((df["roe"] >= 15) & (df["gm"] >= 40) & (df["debt"] <= 60)
              & (df["fcf"].notna()))
    cand = df[lane_a | lane_b].copy()
    cand = cand[~cand["spike"]]  # veto_hard approximation

    def votes(r):
        v = []
        bd = r["borrowed_div"]
        if (not bd and r["roe"] >= 15 and r["gm"] and r["gm"] >= 40
                and r["debt"] and r["debt"] <= 60 and r["ocfy"]
                and r["ocfy"] >= 5 and r["fcfy"] and r["fcfy"] >= 4):
            v.append("buffett")
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
                     + 20 * cand["gm_pctl"] + 15 * cand["fcfy_pctl"]
                     + 15 * (1 - cand["ps_pctl"]))
    cand = cand.sort_values(["nv", "score"], ascending=False)

    # sanity: |ret| > 300% flags possible split/adjustment artifacts
    cand["artifact"] = cand["ret_pct"].abs() > 300

    out = ["ticker", "nv", "votes", "score", "entry", "exit", "ret_pct",
           "pe", "pb", "ps", "roe", "gm", "debt", "ocfy", "fcfy", "divy",
           "rev_yoy", "ni_yoy", "ret60", "pos", "vol"]
    cand[out].to_csv("data/backtest_20251008_us.csv", index=False)
    df.to_csv("data/backtest_20251008_us_universe.csv", index=False)

    # benchmark
    spy = None
    for sym in ("SPY", "QQQ"):
        k = fetch_kline_any("US", sym, "", lmt=400)
        if k is not None and len(k) and k["date"].min() <= ASOF:
            spy = kline_stats(k)
            if spy:
                break
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    show = cand[cand["nv"] >= 2].head(20)
    cols = ["ticker", "nv", "votes", "entry", "exit", "ret_pct", "pe",
            "pb", "roe", "gm", "debt", "fcfy", "divy", "ret60", "artifact"]
    print("\n=== Top candidates (>=2 master votes), ranked votes->score ===")
    print(show[cols].to_string(index=False,
                               float_format=lambda x: f"{x:.1f}"))
    clean = cand[(cand["nv"] >= 2) & (~cand["artifact"])]
    for n in (5, 10):
        port = clean.head(n)
        if len(port) >= 3:
            beat = (port["ret_pct"] > (spy["ret_pct"] if spy else -1e9)).sum()
            print(f"\nTop-{n} equal-weight return: "
                  f"{port['ret_pct'].mean():.1f}%  "
                  f"(median {port['ret_pct'].median():.1f}%, "
                  f"beat-SPY {beat}/{len(port)})")
    if spy:
        print(f"SPY same window: {spy['ret_pct']:.1f}% "
              f"({spy['entry']:.2f} -> {spy['exit']:.2f})")

    print("\n=== calibration diagnostics: memory names ===")
    for tk in ("MU", "SNDK", "WDC", "STX"):
        r = df[df["ticker"] == tk]
        if not len(r):
            print(f"{tk}: not in universe/no data")
            continue
        r = r.iloc[0]
        fails = []
        if not (r["roe"] >= 15):
            fails.append(f"roe {r['roe']:.1f}<15")
        if not (r["gm"] and r["gm"] >= 40):
            fails.append(f"gm {r['gm'] if pd.notna(r['gm']) else float('nan'):.1f}<40")
        if r["pe"] is None or pd.isna(r["pe"]):
            fails.append("PE<=0 (loss)")
        in_cand = len(cand[cand["ticker"] == tk]) > 0
        print(f"{tk}: in_pool={in_cand} ret={r['ret_pct']:.1f}% "
              f"entry={r['entry']:.2f} exit={r['exit']:.2f} "
              f"ni_yoy={r['ni_yoy'] if pd.notna(r['ni_yoy']) else 'n/a'} "
              f"gate_fails=[{'; '.join(fails)}]")


if __name__ == "__main__":
    main()
