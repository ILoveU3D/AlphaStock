"""Earnings subsystem (P1: A-share forecast / appointment / balance
batch tables, design §4)."""

import pandas as pd

from .. import config
from ._dc import code_col, dc_report, name_col, norm_dates


def fetch_a_forecasts(since: str,
                      quiet: bool = True) -> pd.DataFrame | None:
    """业绩预告 RPT_PUBLIC_OP_NEWPREDICT，最新公告 (IS_LATEST=T) 且
    NOTICE_DATE >= since。

    Columns: code, name, predict_type (预增/预减/首亏/扭亏…),
    change_pct (INCREASE_JZ 幅度), notice_date (ISO).
    """
    df = dc_report(config.A_FORECAST_REPORT_NAME,
                   [f'(NOTICE_DATE>="{since}")', '(IS_LATEST="T")'],
                   quiet=quiet, label="A forecasts")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "predict_type": df["PREDICT_TYPE"].astype(str),
        "change_pct": pd.to_numeric(df["INCREASE_JZ"], errors="coerce"),
        "notice_date": df["NOTICE_DATE"],
    })
    return norm_dates(out, "notice_date")


def fetch_a_appointments(start: str, end: str,
                         quiet: bool = True) -> pd.DataFrame | None:
    """披露预约 RPT_PUBLIC_BS_APPOIN，预约日窗口 [start, end]。

    空窗口是正常时序（三季报预约 9 月末才挂出），不是接口失败。
    Columns: code, name, appoint_date (ISO), is_published ("0"=未披露),
    report_type.
    """
    df = dc_report(config.A_APPOINT_REPORT_NAME,
                   [f'(APPOINT_PUBLISH_DATE>="{start}")',
                    f'(APPOINT_PUBLISH_DATE<="{end}")'],
                   quiet=quiet, label="A appointments")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "appoint_date": df["APPOINT_PUBLISH_DATE"],
        "is_published": (df["IS_PUBLISH"].astype(str)
                         if "IS_PUBLISH" in df.columns else ""),
        "report_type": (df["REPORT_TYPE_NAME"].astype(str)
                        if "REPORT_TYPE_NAME" in df.columns else ""),
    })
    return norm_dates(out, "appoint_date")


def fetch_a_balance(report_date: str,
                    quiet: bool = True) -> pd.DataFrame | None:
    """资产负债表批表 RPT_DMSK_FN_BALANCE（全市场约 5.6k 行）。

    ACCOUNTS_RECE_RATIO / INVENTORY_RATIO = 应收/存货 YoY 增速 %
    （TCL/长安/比亚迪三股交叉验证，非占比）；该表无商誉字段
    （eq_goodwill 推迟，设计 §5）。
    Columns: code, rece_yoy, inv_yoy, receivable, inventory,
    report_date.
    """
    df = dc_report(config.A_BALANCE_REPORT_NAME,
                   [f'(REPORT_DATE="{report_date}")'],
                   quiet=quiet, label="A balance")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "rece_yoy": pd.to_numeric(df["ACCOUNTS_RECE_RATIO"],
                                  errors="coerce"),
        "inv_yoy": pd.to_numeric(df["INVENTORY_RATIO"],
                                 errors="coerce"),
        "receivable": pd.to_numeric(df["ACCOUNTS_RECE"],
                                    errors="coerce"),
        "inventory": pd.to_numeric(df["INVENTORY"], errors="coerce"),
    })
    out["report_date"] = report_date
    return out
