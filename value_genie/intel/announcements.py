"""Announcements subsystem (P1: A-share batch event tables, design §4).

Each fetcher returns a normalized DataFrame (columns documented per
function) or None on source failure — the radar marks derived columns
NaN in that case (fail-closed). Date columns are normalized to ISO so
window comparisons stay lexical.
"""

import pandas as pd

from .. import config
from ._dc import code_col, dc_report, name_col, norm_dates


def fetch_a_unlocks(start: str, end: str,
                    quiet: bool = True) -> pd.DataFrame | None:
    """解禁时间表 RPT_LIFT_STAGE，窗口 [start, end]（ISO 日期）。

    Columns: code, name, free_date (ISO), unlock_pct (解禁股/总股本 %,
    TOTAL_RATIO 是小数，×100), lift_cap_wan (解禁市值，万元).
    """
    df = dc_report(config.A_UNLOCK_REPORT_NAME,
                   [f"(FREE_DATE>='{start}')", f"(FREE_DATE<='{end}')"],
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


def fetch_a_holder_changes(since: str,
                           quiet: bool = True) -> pd.DataFrame | None:
    """股东增减持 RPT_SHARE_HOLDER_INCREASE，公告日 >= since。

    Columns: code, name, direction ("减持"/"增持"), change_num_wan (万股),
    notice_date/end_date (ISO，END_DATE 为减持窗口截止，可空),
    holder_name.
    """
    df = dc_report(config.A_HOLDER_REPORT_NAME,
                   [f"(NOTICE_DATE>='{since}')"],
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


def fetch_a_buybacks(since: str,
                     quiet: bool = True) -> pd.DataFrame | None:
    """回购 RPTA_WEB_GPHG，公告日 (GGRQ) >= since。

    该报表用 SCODE/SNAME 且不可带 sortColumns（探针铁律 2）。
    Columns: code, name, amount_yuan (HGJE，元), shares (HGSL，股),
    announce_date (GGRQ, ISO).
    """
    df = dc_report(config.A_BUYBACK_REPORT_NAME,
                   [f"(GGRQ>='{since}')"],
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


def fetch_a_placements(since: str,
                       quiet: bool = True) -> pd.DataFrame | None:
    """定增 RPT_SEO_DETAIL，发行日 (ISSUE_DATE) >= since。

    P1 语义：dilution_flag = 回看窗口内**已完成**的定增（进行中的
    预案在另一张报表，后续阶段接入）。
    Columns: code, name, issue_date (ISO), issue_num, net_raise (元),
    dilution_pct ((after-before)/before %), seo_type.
    """
    df = dc_report(config.A_PLACEMENT_REPORT_NAME,
                   [f"(ISSUE_DATE>='{since}')"],
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
