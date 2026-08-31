# -*- coding: utf-8 -*-
"""
港美股消费板块低估成长股分析脚本
================================

读取 fetch_data.py 拉取的数据，进行以下分析：
  1. 个股指标计算: 52周价格位置、区间涨跌幅、市销率、TTM口径财务指标
  2. 四维评分(按市场分组百分位, 0-100):
       估值得分(35%): PE-TTM / PB / PS 越低分越高
       成长得分(30%): 营收同比 / 净利润同比 越高分越高
       位置得分(15%): 越接近52周低点、区间跌幅越深分越高
       质量得分(20%): 毛利率 / 净利率 / ROE 越高分越高
  3. 综合机会分 = 四维加权, 并按“低位+低估+正增长”硬条件筛选
  4. 重点标的深度分析: 茶百道(02555.HK)、周黑鸭(01458.HK)
     —— 逐项对照港股消费池中位数与同业中位数, 输出数据结论

用法：
  python analyze.py                 # 分析 data/ 下的最新数据
  python analyze.py --data-dir data --out-dir output

输出（output 目录）：
  消费股综合评分排名.csv
  低估值高成长筛选.csv
  分析报告.md

依赖：pandas
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

# 综合评分权重
W_VAL, W_GROW, W_POS, W_QUAL = 0.35, 0.30, 0.15, 0.20
# 硬筛选条件
FILTER_POS_MAX = 0.35      # 52周位置上限(0=最低点, 1=最高点)
FILTER_GROWTH_MIN = 0.0    # 营收同比下限(%)
FILTER_PE_POS = True       # 要求 PE 为正

FOCUS_STOCKS = [("港股", "02555", "茶百道"), ("港股", "01458", "周黑鸭")]


# ----------------------------------------------------------------------------
# 数据加载
# ----------------------------------------------------------------------------
def load_all(data_dir: Path):
    snap = pd.read_csv(data_dir / "消费股池快照.csv",
                       dtype={"代码": str})
    hk_fin = None
    if (data_dir / "港股财务指标.csv").exists():
        hk_fin = pd.read_csv(data_dir / "港股财务指标.csv", dtype={"证券代码": str})
    us_fin = None
    if (data_dir / "美股财务指标.csv").exists():
        us_fin = pd.read_csv(data_dir / "美股财务指标.csv", dtype={"代码": str})

    # 港股代码补齐前导零
    snap.loc[snap["市场"] == "港股", "代码"] = (
        snap.loc[snap["市场"] == "港股", "代码"].astype(str).str.zfill(5))
    if hk_fin is not None and "证券代码" in hk_fin.columns:
        hk_fin["代码"] = hk_fin["证券代码"].astype(str).str.split(".").str[0]
        hk_fin["代码"] = hk_fin["代码"].str.zfill(5)
    if us_fin is not None:
        us_fin["代码"] = us_fin["代码"].astype(str).str.upper()

    # 汇率
    fx = 0.92
    mf = data_dir / "fetch_manifest.json"
    if mf.exists():
        import json
        fx = json.loads(mf.read_text(encoding="utf-8")).get("fx_hkdcny", 0.92)
    return snap, hk_fin, us_fin, fx


def load_kline_metrics(data_dir: Path, market: str, code: str) -> dict:
    """从日K(前复权)计算价格位置与动量指标"""
    f = data_dir / "kline" / f"{market}_{code}.csv"
    if not f.exists():
        return {}
    kl = pd.read_csv(f)
    if kl.empty or "收盘" not in kl.columns:
        return {}
    close = kl["收盘"].astype(float).to_numpy()
    n = len(close)
    price = close[-1]
    w52 = close[-252:] if n >= 252 else close
    hi, lo = float(np.max(w52)), float(np.min(w52))
    pos = (price - lo) / (hi - lo) if hi > lo else np.nan
    def ret(days):
        if n > days:
            return (price / close[-days - 1] - 1) * 100
        if n > 1:
            return (price / close[0] - 1) * 100
        return np.nan
    rets = np.diff(close) / close[:-1]
    vol = float(np.std(rets) * np.sqrt(250) * 100) if len(rets) > 30 else np.nan
    return {
        "52周最高": round(hi, 3), "52周最低": round(lo, 3),
        "52周位置": round(pos, 4) if pos == pos else np.nan,
        "距52周高点%": round((price / hi - 1) * 100, 2) if hi else np.nan,
        "250日涨跌幅%": round(ret(250), 2),
        "60日涨跌幅%": round(ret(60), 2),
        "年化波动率%": round(vol, 1) if vol == vol else np.nan,
    }


# ----------------------------------------------------------------------------
# 港股财务: 最新报告期 + TTM营收 + 最新年报质量指标
# ----------------------------------------------------------------------------
def hk_fin_metrics(hk_fin: pd.DataFrame, code: str) -> dict:
    if hk_fin is None or hk_fin.empty:
        return {}
    df = hk_fin[hk_fin["代码"] == code].copy()
    if df.empty:
        return {}
    df["报告期"] = df["报告期"].astype(str)
    df = df.sort_values("报告期", ascending=False)

    latest = df.iloc[0]
    out = {
        "最新报告期": str(latest.get("报告期", "")),
        "报告类型": str(latest.get("报告类型", "")),
        "营收同比%": _f(latest.get("营业收入同比%")),
        "净利同比%": _f(latest.get("归母净利润同比%")),
    }

    # ---- TTM 营收: 上年年报 + 本期累计 - 上年同期累计 ----
    def find(period_like):
        m = df[df["报告期"].str.startswith(period_like)]
        return m.iloc[0] if not m.empty else None

    rev_ttm = None
    if "营业收入" in df.columns:
        latest_date = str(latest["报告期"])
        if latest_date.endswith("12-31"):
            rev_ttm = _f(latest.get("营业收入"))
        else:
            y, md = latest_date[:4], latest_date[5:]
            prev_same = find(f"{int(y) - 1}-{md}")
            prev_annual = find(f"{int(y) - 1}-12-31")
            if prev_same is not None and prev_annual is not None:
                a, b, c = (_f(prev_annual.get("营业收入")),
                           _f(latest.get("营业收入")),
                           _f(prev_same.get("营业收入")))
                if None not in (a, b, c):
                    rev_ttm = a + b - c
    out["TTM营收"] = rev_ttm

    # ---- 最新年报质量指标 ----
    ann = df[df["报告期"].str.endswith("12-31")]
    if ann.empty:
        ann = df.iloc[[0]]
    ann_row = ann.iloc[0]
    out["最新年报"] = str(ann_row.get("报告期", ""))
    out["毛利率%"] = _f(ann_row.get("毛利率%"))
    out["净利率%"] = _f(ann_row.get("净利率%"))
    out["ROE%"] = _f(ann_row.get("ROE%"))
    out["资产负债率%"] = _f(ann_row.get("资产负债率%"))

    # ---- 股息率: 近12个月每股股息 / 现价 (由调用方补现价) ----
    # 注: 东财F10的 DPS_HKD 字段本身即"近12个月累计已派股息"(各报告期同值,
    #     如茶百道 0.403 = 2025中期0.197 + 2025末期0.206), 直接取最新行,
    #     不可再与上年年报相加(否则翻倍高估)。
    dps12 = None
    if "每股股息HKD" in df.columns:
        dps12 = _f(latest.get("每股股息HKD"))
    out["近12月每股股息"] = dps12
    dr = _f(latest.get("股息率%"))
    out["报告期股息率%"] = dr if (dr is not None and 0 < dr <= 30) else None
    return out


def _f(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# 美股财务
# ----------------------------------------------------------------------------
def us_fin_metrics(us_fin: pd.DataFrame, ticker: str) -> dict:
    if us_fin is None or us_fin.empty:
        return {}
    df = us_fin[us_fin["代码"] == ticker]
    if df.empty:
        return {}
    r = df.iloc[0]
    rev, ni = _f(r.get("营业收入(最新财年)")), _f(r.get("净利润(最新财年)"))
    out = {
        "最新报告期": str(r.get("最新财年期末", "")) + "(财年)",
        "营收同比%": _f(r.get("营收同比%")),
        "净利同比%": _f(r.get("净利润同比%")),
        "最新季营收同比%": _f(r.get("最新季度营收同比%")),
        "TTM营收": rev,
    }
    if rev and ni is not None:
        out["净利率%"] = round(ni / rev * 100, 2)
        eq1, eq0 = _f(r.get("股东权益(最新)")), _f(r.get("股东权益(上年)"))
        if eq1 and eq0:
            out["ROE%"] = round(ni / ((eq1 + eq0) / 2) * 100, 2)
    return out


# ----------------------------------------------------------------------------
# 评分
# ----------------------------------------------------------------------------
def pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100.0


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["估值得分"] = np.nan
    df["成长得分"] = np.nan
    df["位置得分"] = np.nan
    df["质量得分"] = np.nan

    for mkt, g in df.groupby("市场"):
        idx = g.index

        # --- 估值得分: PE/PB/PS 越低越好 ---
        pe = g["市盈率TTM"].where(g["市盈率TTM"] > 0)
        pb = g["市净率"].where(g["市净率"] > 0)
        ps = g["市销率"].where(g["市销率"] > 0)
        comp = pd.concat([100 - pct_rank(pe), 100 - pct_rank(pb),
                          100 - pct_rank(ps)], axis=1)
        df.loc[idx, "估值得分"] = comp.mean(axis=1, skipna=True).round(1)

        # --- 成长得分 ---
        grow = pd.concat([
            pct_rank(g["营收同比%"]),
            pct_rank(g["净利同比%"]),
            pct_rank(g["最新季营收同比%"]) if "最新季营收同比%" in g else
            pd.Series(np.nan, index=g.index),
        ], axis=1)
        df.loc[idx, "成长得分"] = grow.mean(axis=1, skipna=True).round(1)

        # --- 位置得分: 越接近低点分越高 ---
        pos = 0.6 * (100 - pct_rank(g["52周位置"])) + \
              0.4 * (100 - pct_rank(g["250日涨跌幅%"]))
        df.loc[idx, "位置得分"] = pos.round(1)

        # --- 质量得分 ---
        qual = pd.concat([
            pct_rank(g["毛利率%"]),
            pct_rank(g["净利率%"]),
            pct_rank(g["ROE%"]),
        ], axis=1)
        df.loc[idx, "质量得分"] = qual.mean(axis=1, skipna=True).round(1)

    # --- 综合机会分: 可得分量加权(至少3维) ---
    parts = {"估值得分": W_VAL, "成长得分": W_GROW,
             "位置得分": W_POS, "质量得分": W_QUAL}
    scores = []
    completeness = []
    for _, r in df.iterrows():
        avail = {k: (r[k], w) for k, w in parts.items()
                 if pd.notna(r[k])}
        completeness.append(len(avail))
        if len(avail) >= 3:
            wsum = sum(w for _, w in avail.values())
            scores.append(round(sum(v * w / wsum for v, w in avail.values()), 1))
        else:
            scores.append(np.nan)
    df["综合机会分"] = scores
    df["数据完整度"] = completeness
    return df


def fmt(v, suffix=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}{suffix}"
    return f"{v}{suffix}"


# ----------------------------------------------------------------------------
# 报告生成
# ----------------------------------------------------------------------------
REPORT_HEADER = """# 港美股消费板块“低估 + 低位 + 成长”分析报告

* 数据拉取时间: {fetch_time}
* 行情口径: 东方财富(上一个交易日收盘), 日K为前复权
* 财务口径: 港股=最新报告期(东财F10); 美股=最新完整财年(SEC EDGAR 官方备案数据)
* 评分口径: 各市场消费池内百分位计分, 综合机会分 = 估值35% + 成长30% + 位置15% + 质量20%

## 评分方法

| 维度 | 权重 | 构成 | 方向 |
|---|---|---|---|
| 估值得分 | 35% | PE(TTM) / PB / PS 池内百分位 | 越低分越高 |
| 成长得分 | 30% | 营收同比 / 净利润同比 / 最新季营收同比 | 越高分越高 |
| 位置得分 | 15% | 52周位置 / 250日涨跌幅 | 越接近52周低点分越高 |
| 质量得分 | 20% | 毛利率 / 净利率 / ROE | 越高分越高 |

“综合机会分”高 = 相对同池股票同时具备更低的估值、更强的成长、更深的回撤位置与更好的经营质量，
**不等于**买入建议；亏损、负增长或数据缺失的标的会被降权或剔除。
"""


def build_master(snap, hk_fin, us_fin, fx, data_dir):
    rows = []
    for _, s in snap.iterrows():
        mkt, code = s["市场"], str(s["代码"]).zfill(5) if s["市场"] == "港股" else s["代码"]
        row = {
            "市场": mkt, "代码": s["代码"], "名称": s["名称"],
            "板块": s["板块"], "细分行业": s["细分行业"], "货币": s["货币"],
            "最新价": _f(s.get("最新价")),
            "总市值(亿)": round(_f(s.get("总市值")) / 1e8, 1)
            if _f(s.get("总市值")) is not None else np.nan,
            "市盈率TTM": _f(s.get("市盈率TTM")),
            "市净率": _f(s.get("市净率")),
        }
        row.update(load_kline_metrics(data_dir, mkt, code))
        if mkt == "港股":
            fm = hk_fin_metrics(hk_fin, code)
            row.update(fm)
            # 市销率: 市值(HKD) * 汇率 / TTM营收(CNY)
            rev_ttm = row.get("TTM营收")
            mcap = _f(s.get("总市值"))
            if rev_ttm and mcap:
                row["市销率"] = round(mcap * fx / rev_ttm, 2)
            else:
                row["市销率"] = np.nan
            # 股息率
            price = row.get("最新价")
            dps12 = row.get("近12月每股股息")
            if dps12 and price:
                y = dps12 / price * 100
                if 0 < y < 30:
                    row["股息率%"] = round(y, 2)
                else:
                    row["股息率%"] = row.get("报告期股息率%")
            else:
                row["股息率%"] = row.get("报告期股息率%")
        else:
            fm = us_fin_metrics(us_fin, code)
            row.update(fm)
            rev = row.get("TTM营收")
            mcap = _f(s.get("总市值"))
            # 仅美元报表参与市销率(美股财务币种来自SEC XBRL)
            usd = (us_fin is not None and not us_fin.empty)
            if usd and "币种" in us_fin.columns:
                m = us_fin[us_fin["代码"] == code]
                usd = (not m.empty) and (str(m.iloc[0].get("币种")) == "USD")
            row["市销率"] = round(mcap / rev, 2) if (rev and mcap and usd) else np.nan
            row["股息率%"] = np.nan
        row.pop("近12月每股股息", None)
        row.pop("报告期股息率%", None)
        row.pop("TTM营收", None)
        rows.append(row)
    return pd.DataFrame(rows)


def top_table(df, cols):
    t = df[cols].copy()
    for c in t.columns:
        if t[c].dtype.kind == "f":
            t[c] = t[c].map(lambda x: "" if pd.isna(x) else round(x, 2))
    return t


def focus_section(master, mkt, code, name, report, mkt_pool):
    """重点标的深度分析"""
    m = master[(master["市场"] == mkt) & (master["代码"] == code)]
    if m.empty:
        report.append(f"\n## {name}({code}): 未在股池中找到\n")
        return
    r = m.iloc[0]
    pool = master[master["市场"] == mkt].dropna(subset=["市盈率TTM"])
    pool = pool[pool["市盈率TTM"] > 0]
    industry = r["细分行业"]
    peers = master[(master["市场"] == mkt) & (master["细分行业"] == industry)]
    peers_valid = peers[peers["市盈率TTM"] > 0]

    def pv(col, higher_is_better=None):
        """池内百分位(仅对非缺失值)"""
        s = master[master["市场"] == mkt][col].dropna()
        if len(s) < 3 or pd.isna(r.get(col)):
            return None
        return round(float((s <= r[col]).mean() * 100))

    pe_med = float(np.nanmedian(pool["市盈率TTM"])) if len(pool) else np.nan
    pe_ind = float(np.nanmedian(peers_valid["市盈率TTM"])) if len(peers_valid) else np.nan
    pb_med = float(np.nanmedian(master[master["市场"] == mkt]["市净率"].dropna()))

    report.append(f"\n## {name}（{r['代码']}，{industry}）深度分析\n")
    report.append("| 指标 | 数值 | 含义/对照 |")
    report.append("|---|---|---|")
    pos52 = r.get("52周位置")
    pos_desc = ("处于52周最低点附近" if pos52 is not None and pos52 <= 0.05 else
                "接近52周低点" if pos52 is not None and pos52 <= 0.2 else
                "处于52周区间中部" if pos52 is not None and pos52 <= 0.5 else
                "处于52周区间偏高位置")
    report.append(f"| 现价 | {fmt(r.get('最新价'))} {r.get('货币')} | {pos_desc} |")
    report.append(f"| 52周区间(前复权) | {fmt(r.get('52周最低'))} ~ {fmt(r.get('52周最高'))} "
                  f"| 位置 {fmt(pos52, '') if pos52 is not None else '-'} |")
    report.append(f"| 距52周高点 | {fmt(r.get('距52周高点%'), '%')} | 250日涨跌幅 "
                  f"{fmt(r.get('250日涨跌幅%'), '%')} |")
    pe = r.get("市盈率TTM")
    pe_note = ("亏损或无意义" if pe is None or (isinstance(pe, float) and np.isnan(pe)) else
               (f"池内第{pv('市盈率TTM')}百分位, 池中位数 {pe_med:.1f}, "
                f"同业中位数 {pe_ind:.1f}" if pe > 0 else "PE为负(亏损)"))
    report.append(f"| 市盈率TTM | {fmt(pe)} | {pe_note} |")
    report.append(f"| 市净率 | {fmt(r.get('市净率'))} | 池中位数 {fmt(pb_med)} |")
    report.append(f"| 市销率 | {fmt(r.get('市销率'))} | 市值/TTM营收 |")
    report.append(f"| 营收同比 | {fmt(r.get('营收同比%'), '%')} | {r.get('最新报告期','')} |")
    report.append(f"| 净利同比 | {fmt(r.get('净利同比%'), '%')} | - |")
    report.append(f"| 毛利率 | {fmt(r.get('毛利率%'), '%')} | 最新年报口径 |")
    report.append(f"| 净利率 | {fmt(r.get('净利率%'), '%')} | - |")
    report.append(f"| ROE | {fmt(r.get('ROE%'), '%')} | 最新年报口径 |")
    if mkt == "港股":
        report.append(f"| 股息率 | {fmt(r.get('股息率%'), '%')} | 近12月股息/现价 |")
    report.append(f"| 综合机会分 | {fmt(r.get('综合机会分'))} "
                  f"(估值{fmt(r.get('估值得分'))}/成长{fmt(r.get('成长得分'))}"
                  f"/位置{fmt(r.get('位置得分'))}/质量{fmt(r.get('质量得分'))}) "
                  f"| 池内排名 {int((mkt_pool['综合机会分'] > r.get('综合机会分', -1)).sum()) + 1}"
                  f"/{len(mkt_pool)} |")

    # 同业对比表
    if len(peers) > 1:
        report.append(f"\n### 同业对比（{industry}）\n")
        cols = ["名称", "最新价", "市盈率TTM", "市净率", "市销率",
                "营收同比%", "净利同比%", "ROE%", "52周位置", "综合机会分"]
        t = top_table(peers.sort_values("综合机会分", ascending=False), cols)
        report.append(t.to_markdown(index=False))

    # 数据结论
    report.append(f"\n### 数据结论（{name}）\n")
    verdicts = []
    if pos52 is not None and pos52 <= 0.15:
        verdicts.append(f"价格确实处于低位：现价位于52周区间的 {pos52 * 100:.0f}% 位置，"
                        f"距52周高点回撤 {abs(r.get('距52周高点%', 0)):.0f}%。")
    elif pos52 is not None and pos52 <= 0.35:
        verdicts.append(f"价格处于相对低位：52周区间位置 {pos52 * 100:.0f}%。")
    elif pos52 is not None:
        verdicts.append(f"价格并不处于低位：52周区间位置已达 {pos52 * 100:.0f}%，"
                        f"“处于低点”的判断在价格维度证据不足。")
    pe = r.get("市盈率TTM")
    if pe is not None and not np.isnan(pe) and pe > 0:
        if pe < pe_med * 0.7:
            verdicts.append(f"估值维度支持“低估”：PE(TTM) {pe:.1f} 显著低于"
                            f"该市场消费池中位数 {pe_med:.1f}。")
        elif pe < pe_med:
            verdicts.append(f"估值低于消费池中位数（{pe:.1f} vs {pe_med:.1f}），"
                            f"属于偏低但非极端。")
        else:
            verdicts.append(f"估值维度不支持“低估”：PE(TTM) {pe:.1f} 高于消费池中位数 "
                            f"{pe_med:.1f}。")
    else:
        verdicts.append("公司处于亏损或 PE 无意义状态，估值判断需依赖 PB/PS 及基本面拐点。")
    g = r.get("营收同比%")
    gp = r.get("净利同比%")
    if g is not None and not np.isnan(g):
        if g > 10:
            verdicts.append(f"成长性较好：最新报告期营收同比 +{g:.1f}%。")
        elif g > 0:
            verdicts.append(f"成长性为正但温和：营收同比 +{g:.1f}%。")
        else:
            verdicts.append(f"成长性存疑：营收同比 {g:.1f}%，“高增长后发趋势”"
                            f"在当前数据中尚无体现。")
    if mkt == "港股" and r.get("股息率%") is not None and not np.isnan(r.get("股息率%")) \
            and r.get("股息率%") > 4:
        verdicts.append(f"股息率 {r['股息率%']:.1f}% 提供了一定的安全垫。")
    for v in verdicts:
        report.append(f"- {v}")
    report.append("")


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="港美股消费板块分析")
    ap.add_argument("--data-dir", default=str(BASE_DIR / "data"))
    ap.add_argument("--out-dir", default=str(BASE_DIR / "output"))
    args = ap.parse_args()
    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    snap_path = data_dir / "消费股池快照.csv"
    if not snap_path.exists():
        print(f"[错误] 未找到 {snap_path}, 请先运行 fetch_data.py")
        sys.exit(1)

    print("=" * 72)
    print("港美股消费板块低估成长股分析")
    print("=" * 72)

    fetch_time = ""
    mf = data_dir / "fetch_manifest.json"
    if mf.exists():
        import json
        fetch_time = json.loads(mf.read_text(encoding="utf-8")).get("end_time", "")

    snap, hk_fin, us_fin, fx = load_all(data_dir)
    print(f"消费股池: {len(snap)} 只 (港股 "
          f"{(snap['市场'] == '港股').sum()}, 美股 {(snap['市场'] == '美股').sum()})")

    master = build_master(snap, hk_fin, us_fin, fx, data_dir)
    master = add_scores(master)

    # 标签列
    def tag_row(r):
        tags = []
        if pd.notna(r["52周位置"]) and r["52周位置"] <= FILTER_POS_MAX:
            tags.append("低位")
        pe_ok = pd.notna(r["市盈率TTM"]) and r["市盈率TTM"] > 0
        if pe_ok:
            med = master[master["市场"] == r["市场"]]["市盈率TTM"]
            med = med[med > 0].median()
            if r["市盈率TTM"] <= med:
                tags.append("低估")
        else:
            tags.append("亏损/无PE")
        if pd.notna(r["营收同比%"]) and r["营收同比%"] > FILTER_GROWTH_MIN:
            tags.append("正增长")
        if pd.notna(r["营收同比%"]) and r["营收同比%"] <= FILTER_GROWTH_MIN:
            tags.append("负增长")
        if r["数据完整度"] < 3:
            tags.append("数据不足")
        return "+".join(tags) if tags else "-"

    master["标签"] = master.apply(tag_row, axis=1)

    # ---- 硬筛选: 低位 + 低估 + 正增长 ----
    flt = master[
        (master["52周位置"] <= FILTER_POS_MAX)
        & (master["市盈率TTM"] > 0 if FILTER_PE_POS else True)
        & (master["营收同比%"] > FILTER_GROWTH_MIN)
    ].copy()
    mkt_med = master[master["市盈率TTM"] > 0].groupby("市场")["市盈率TTM"].median()
    flt = flt[flt["市盈率TTM"] <= flt["市场"].map(mkt_med)]
    flt = flt[flt["净利率%"] > 0]
    flt = flt.sort_values("综合机会分", ascending=False)

    # ---- 输出 CSV ----
    rank_cols = ["市场", "代码", "名称", "板块", "细分行业", "最新价", "货币",
                 "总市值(亿)", "市盈率TTM", "市净率", "市销率", "股息率%",
                 "52周位置", "距52周高点%", "250日涨跌幅%", "60日涨跌幅%",
                 "营收同比%", "净利同比%", "最新季营收同比%", "毛利率%",
                 "净利率%", "ROE%", "估值得分", "成长得分", "位置得分",
                 "质量得分", "综合机会分", "数据完整度", "标签", "最新报告期"]
    rank_cols = [c for c in rank_cols if c in master.columns]
    out_rank = master[rank_cols].sort_values(
        ["市场", "综合机会分"], ascending=[True, False])
    out_rank.to_csv(out_dir / "消费股综合评分排名.csv", index=False,
                    encoding="utf-8-sig")
    flt[rank_cols].to_csv(out_dir / "低估值高成长筛选.csv", index=False,
                          encoding="utf-8-sig")

    # ---- 报告 ----
    report = [REPORT_HEADER.format(fetch_time=fetch_time or "见 fetch_manifest.json")]

    hk_pool = master[master["市场"] == "港股"].sort_values(
        "综合机会分", ascending=False)
    us_pool = master[master["市场"] == "美股"].sort_values(
        "综合机会分", ascending=False)

    report.append(f"\n## 股池概览\n\n- 港股消费股 {len(hk_pool)} 只, "
                  f"美股消费股 {len(us_pool)} 只\n")
    report.append(f"- 港股池 PE(TTM) 中位数: "
                  f"{fmt(float(np.nanmedian(hk_pool[hk_pool['市盈率TTM'] > 0]['市盈率TTM'])))}"
                  f"；美股池: "
                  f"{fmt(float(np.nanmedian(us_pool[us_pool['市盈率TTM'] > 0]['市盈率TTM'])))}\n")

    show_cols = ["代码", "名称", "细分行业", "最新价", "市盈率TTM", "市净率",
                 "市销率", "营收同比%", "52周位置", "综合机会分", "标签"]
    for title, pool in (("港股消费池 综合机会分 TOP15", hk_pool),
                        ("美股消费池 综合机会分 TOP15", us_pool)):
        report.append(f"\n## {title}\n")
        t = top_table(pool.head(15), show_cols)
        report.append(t.to_markdown(index=False))

    report.append("\n## “低位 + 低估 + 正增长”硬筛选结果\n")
    report.append(f"筛选条件: 52周位置≤{FILTER_POS_MAX:.0%}、PE(TTM)为正且不高于"
                  f"所在市场池中位数、营收同比>0、净利率>0。\n")
    if flt.empty:
        report.append("无标的满足全部条件。\n")
    else:
        report.append(f"共 {len(flt)} 只满足 (港股 {(flt['市场'] == '港股').sum()}, "
                      f"美股 {(flt['市场'] == '美股').sum()}):\n")
        t = top_table(flt, show_cols)
        report.append(t.to_markdown(index=False))

    # 重点标的
    report.append("\n# 重点标的验证\n")
    report.append("以下对用户点名的两只标的做逐项数据核验。\n")
    for mkt, code, name in FOCUS_STOCKS:
        pool = hk_pool if mkt == "港股" else us_pool
        focus_section(master, mkt, code, name, report, pool)

    # 附: 全部指标中的关键说明
    report.append("\n# 数据与口径说明\n")
    report.append("- 日K为前复权口径, 52周高低点/区间涨跌幅据此计算, 与行情软件"
                  "“不复权”数值可能略有差异。")
    report.append("- 港股市销率 = 总市值(HKD) × 汇率 / TTM营收(CNY), 汇率取自动探测值。")
    report.append("- 港股成长口径为最新报告期同比(中报/年报), 美股为最新完整财年同比, "
                  "口径存在时滞差异。")
    report.append("- 美股ADR(百威英博/帝亚吉欧/联合利华等)不向SEC提交US-GAAP的XBRL, "
                  "财务成长指标缺失, 评分自动降权。")
    report.append("- 本报告由脚本自动生成, 仅为数据研究参考, 不构成投资建议。\n")

    (out_dir / "分析报告.md").write_text("\n".join(report), encoding="utf-8")

    # ---- 控制台摘要 ----
    print("\n【综合机会分 TOP10 - 港股消费】")
    cols = ["代码", "名称", "最新价", "市盈率TTM", "营收同比%", "52周位置", "综合机会分", "标签"]
    print(hk_pool.head(10)[cols].to_string(index=False))
    print("\n【综合机会分 TOP10 - 美股消费】")
    print(us_pool.head(10)[cols].to_string(index=False))
    print(f"\n【低位+低估+正增长 硬筛选】共 {len(flt)} 只:")
    if not flt.empty:
        print(flt[["市场"] + cols].to_string(index=False))
    print(f"\n输出目录: {out_dir}")
    print("  消费股综合评分排名.csv / 低估值高成长筛选.csv / 分析报告.md")
    print("=" * 72)


if __name__ == "__main__":
    main()
