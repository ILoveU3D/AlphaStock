"""Shared Eastmoney datacenter paging helper for intel fetchers.

Eastmoney datacenter probe rules (verified 2026-09-09, design
appendix A):
1. Date filter values use SINGLE quotes — double quotes trip
   "filter字段中日期参数格式错误". String/boolean values use DOUBLE
   quotes — single quotes trip an ANTLR InputMismatchException on
   some reports (e.g. IS_LATEST='T').
2. RPTA_WEB_GPHG must be fetched WITHOUT sortColumns/sortTypes
   ("SECURITY_CODE排序列不存在") — pass sort_columns=None.
3. A non-filterable field silently voids the whole filter and returns
   the FULL table — callers must re-filter rows in pandas and sanity
   check counts.
4. A valid empty window answers {"success": false, "code": 9201,
   "message": "返回数据为空"} on some reports (e.g. RPT_PUBLIC_BS_
   APPOIN forward windows) — that is an empty DataFrame, not a
   source failure.
"""

import time

import pandas as pd

from .. import config
from ..fetch.http import DC


def dc_report(report_name: str, filters: list, *,
              page_size: int = None, sort_columns: str = "SECURITY_CODE",
              max_pages: int = 60, retries: int = 3,
              sleep_sec: float = 0.4, quiet: bool = True,
              label: str = "") -> pd.DataFrame | None:
    """Paged datacenter report fetch -> raw-row DataFrame.

    ``filters`` are ``(FIELD=value)`` chunks joined verbatim (the
    caller controls quoting). Returns None on transport failure or a
    report-level error ({"success": false}) so callers can mark the
    derived columns NaN (fail-closed, design §6.2); an empty DataFrame
    means a valid empty window.
    """
    page_size = page_size or config.A_PAGE_SIZE
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": "".join(filters),
        "pageSize": page_size,
        "source": "WEB",
        "client": "WEB",
    }
    if sort_columns:
        params["sortColumns"] = sort_columns
        params["sortTypes"] = "1"
    frames = []
    page = 1
    while page <= max_pages:
        raw = DC.get_json(config.DC_WEB_URL,
                          params={**params, "pageNumber": page},
                          retries=retries)
        if raw is None:
            return None
        if raw.get("success") is False:
            # probe rule 4: 9201 "返回数据为空" = valid empty window
            if "返回数据为空" in str(raw.get("message") or ""):
                if frames:          # paged past the end — keep rows so far
                    break
                return pd.DataFrame()
            return None
        result = raw.get("result") or {}
        rows = result.get("data") or []
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        if not quiet:
            print(f"    [{label}] page {page}: {len(rows)} rows")
        if page >= (result.get("pages") or 1):
            break
        page += 1
        time.sleep(sleep_sec)
    return (pd.concat(frames, ignore_index=True)
            if frames else pd.DataFrame())


def code_col(df: pd.DataFrame):
    """Security code series from a raw DC frame (SECURITY_CODE or SCODE)."""
    for c in ("SECURITY_CODE", "SCODE"):
        if c in df.columns:
            return df[c].astype(str)
    raise KeyError("no SECURITY_CODE/SCODE column in datacenter report")


def name_col(df: pd.DataFrame, default=""):
    """Display-name series, tolerant of per-report naming."""
    for c in ("SECURITY_NAME_ABBR", "SNAME"):
        if c in df.columns:
            return df[c].astype(str)
    return default


def norm_dates(df: pd.DataFrame, *cols) -> pd.DataFrame:
    """Trim datetime-ish columns to ISO dates (YYYY-MM-DD) so window
    comparisons stay lexical."""
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.slice(0, 10)
    return df
