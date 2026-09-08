"""Announcements subsystem (P1: A-share batch event tables, design §4).

Each fetcher returns a normalized DataFrame (columns documented per
function) or None on source failure — the radar marks derived columns
NaN in that case (fail-closed). Date columns are normalized to ISO so
window comparisons stay lexical.
"""

from datetime import date, timedelta

import pandas as pd

from .. import config
from ..fetch.http import EM_WEB
from ._dc import code_col, dc_report, name_col, norm_dates
from .model import IntelItem

NOTICE_URL_TMPL = ("https://data.eastmoney.com/notices/detail/"
                   "{code}/{art}.html")


def fetch_stock_notices(code: str, name: str = "",
                        days: int = None) -> list | None:
    """近 days 天个股公告列表（np-anotice-stock），带分类与详情 URL。

    返回 IntelItem 列表（subsystem="announcements", kind="notice"，
    impact=neutral——公告性质由 AI 结合分类语境解读），源失败 None。
    """
    days = days or config.INTEL_NOTICE_DAYS
    since = (date.today() - timedelta(days=days)).isoformat()
    raw = EM_WEB.get_json(config.EM_NOTICE_URL, params={
        "sr": -1, "page_size": 50, "page_index": 1, "ann_type": "A",
        "stock_list": code, "f_node": 0, "s_node": 0,
    })
    if raw is None:
        return None
    rows = ((raw.get("data") or {}).get("list")) or []
    items = []
    for r in rows:
        nd = str(r.get("notice_date") or "")[:10]
        if not nd or nd < since:
            continue
        cols = r.get("columns") or []
        cat = "；".join(str(c.get("column_name") or "")
                       for c in cols if c.get("column_name")) or "公告"
        art = str(r.get("art_code") or "")
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="announcements", kind="notice",
            event_date=date.fromisoformat(nd),
            title=str(r.get("title") or ""),
            url=NOTICE_URL_TMPL.format(code=code, art=art) if art else "",
            source="eastmoney", impact="neutral",
            payload={"category": cat, "art_code": art}))
    return items


def fetch_a_unlocks(start: str, end: str, code: str | None = None,
                    quiet: bool = True) -> pd.DataFrame | None:
    """解禁时间表 RPT_LIFT_STAGE，窗口 [start, end]（ISO 日期）。

    code 非 None 时追加 (SECURITY_CODE="...") 单股过滤（P2 单股兜底）。
    Columns: code, name, free_date (ISO), unlock_pct (解禁股/总股本 %,
    TOTAL_RATIO 是小数，×100), lift_cap_wan (解禁市值，万元).
    """
    filters = [f"(FREE_DATE>='{start}')", f"(FREE_DATE<='{end}')"]
    if code:
        filters.append(f'(SECURITY_CODE="{code}")')
    df = dc_report(config.A_UNLOCK_REPORT_NAME, filters,
                   quiet=quiet, label="A unlocks")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "free_date": df["FREE_DATE"],
        "unlock_pct": pd.to_numeric(df["TOTAL_RATIO"],
                                    errors="coerce") * 100.0,
        "lift_cap_wan": pd.to_numeric(df["LIFT_MARKET_CAP"],
                                      errors="coerce"),
    })
    return norm_dates(out, "free_date")


def fetch_a_holder_changes(since: str, code: str | None = None,
                           quiet: bool = True) -> pd.DataFrame | None:
    """股东增减持 RPT_SHARE_HOLDER_INCREASE，公告日 >= since。

    code 非 None 时追加 (SECURITY_CODE="...") 单股过滤（P2 单股兜底）。
    Columns: code, name, direction ("减持"/"增持"), change_num_wan (万股),
    notice_date/end_date (ISO，END_DATE 为减持窗口截止，可空),
    holder_name.
    """
    filters = [f"(NOTICE_DATE>='{since}')"]
    if code:
        filters.append(f'(SECURITY_CODE="{code}")')
    df = dc_report(config.A_HOLDER_REPORT_NAME, filters,
                   quiet=quiet, label="A holder changes")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "direction": df["DIRECTION"].astype(str),
        "change_num_wan": pd.to_numeric(df["CHANGE_NUM"],
                                        errors="coerce"),
        "notice_date": df["NOTICE_DATE"],
        "end_date": df["END_DATE"],
        "holder_name": (df["HOLDER_NAME"].astype(str)
                        if "HOLDER_NAME" in df.columns else ""),
    })
    return norm_dates(out, "notice_date", "end_date")


def fetch_a_buybacks(since: str, code: str | None = None,
                     quiet: bool = True) -> pd.DataFrame | None:
    """回购 RPTA_WEB_GPHG，公告日 (GGRQ) >= since。

    code 非 None 时追加 (SCODE="...") 单股过滤（该报表用 SCODE）。
    该报表用 SCODE/SNAME 且不可带 sortColumns（探针铁律 2）。
    Columns: code, name, amount_yuan (HGJE，元), shares (HGSL，股),
    announce_date (GGRQ, ISO).
    """
    filters = [f"(GGRQ>='{since}')"]
    if code:
        filters.append(f'(SCODE="{code}")')
    df = dc_report(config.A_BUYBACK_REPORT_NAME, filters,
                   sort_columns=None,     # probe rule: GPHG 无该排序列
                   quiet=quiet, label="A buybacks")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "amount_yuan": pd.to_numeric(df["HGJE"], errors="coerce"),
        "shares": (pd.to_numeric(df["HGSL"], errors="coerce")
                   if "HGSL" in df.columns else None),
        "announce_date": df["GGRQ"],
    })
    return norm_dates(out, "announce_date")


def fetch_a_placements(since: str, code: str | None = None,
                       quiet: bool = True) -> pd.DataFrame | None:
    """定增 RPT_SEO_DETAIL，发行日 (ISSUE_DATE) >= since。

    code 非 None 时追加 (SECURITY_CODE="...") 单股过滤（P2 单股兜底）。
    P1 语义：dilution_flag = 回看窗口内**已完成**的定增（进行中的
    预案在另一张报表，后续阶段接入）。
    Columns: code, name, issue_date (ISO), issue_num, net_raise (元),
    dilution_pct ((after-before)/before %), seo_type.
    """
    filters = [f"(ISSUE_DATE>='{since}')"]
    if code:
        filters.append(f'(SECURITY_CODE="{code}")')
    df = dc_report(config.A_PLACEMENT_REPORT_NAME, filters,
                   quiet=quiet, label="A placements")
    if df is None:
        return None
    if df.empty:
        return df
    before = pd.to_numeric(df["ISSUE_SHARE_BEFORE"], errors="coerce")
    after = pd.to_numeric(df["ISSUE_SHARE_AFTER"], errors="coerce")
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "issue_date": df["ISSUE_DATE"],
        "issue_num": pd.to_numeric(df["ISSUE_NUM"], errors="coerce"),
        "net_raise": pd.to_numeric(df["NET_RAISE_FUNDS"],
                                   errors="coerce"),
        "dilution_pct": (after - before) / before * 100.0,
        "seo_type": (df["SEO_TYPE"].astype(str)
                     if "SEO_TYPE" in df.columns else ""),
    })
    return norm_dates(out, "issue_date")
