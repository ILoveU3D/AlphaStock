"""Tests for value_genie.report (snapshot loading, screening, exports)."""

from pathlib import Path

import pandas as pd
import pytest

from value_genie import report


# ---------------------------------------------------------------------------
# Synthetic master frames (pillar scores chosen for deterministic ranking)
# ---------------------------------------------------------------------------
def _master() -> pd.DataFrame:
    """Seven stocks with known pillar scores.

    Balanced composite (0.35/0.25/0.30/0.10, min 3 pillars):
      600519 68.50   00700 61.75   AAPL 57.50   MSFT 54.50
      300750 52.00   000858 47.50  601318 42.22   BADX excluded (2 pillars)
    """
    rows = [
        {"market": "A", "code": "600519", "name": "Moutai",
         "industry": "Liquor", "price": 1500.0, "market_cap": 1.9e12,
         "pe_ttm": 25.0, "pb": 8.0, "ps": 15.0, "dividend_yield": 3.0,
         "rev_yoy": 15.0, "profit_yoy": 18.0, "roe": 30.0,
         "gross_margin": 91.0, "net_margin": 50.0,
         "report_date": "2026-06-30",
         "value_score": 80.0, "growth_score": 70.0, "quality_score": 60.0,
         "safety_score": 50.0},
        {"market": "A", "code": "000858", "name": "Wuliangye",
         "industry": "Liquor", "price": 130.0, "market_cap": 5.0e11,
         "pe_ttm": 20.0, "pb": 5.0, "ps": 8.0, "dividend_yield": 2.0,
         "rev_yoy": 10.0, "profit_yoy": 12.0, "roe": 22.0,
         "gross_margin": 75.0, "net_margin": 35.0,
         "report_date": "2026-06-30",
         "value_score": 40.0, "growth_score": 90.0, "quality_score": 30.0,
         "safety_score": 20.0},
        {"market": "A", "code": "601318", "name": "Ping An",
         "industry": "Insurance", "price": 50.0, "market_cap": 9.0e11,
         "pe_ttm": 8.0, "pb": 1.0, "ps": 1.2, "dividend_yield": 5.0,
         "rev_yoy": 6.0, "profit_yoy": 5.0, "roe": 12.0,
         "gross_margin": 30.0, "net_margin": 15.0,
         "report_date": "2026-06-30",
         "value_score": 20.0, "growth_score": 10.0, "quality_score": 95.0,
         "safety_score": None},
        {"market": "A", "code": "300750", "name": "CATL",
         "industry": "Battery", "price": 200.0, "market_cap": 8.8e11,
         "pe_ttm": 30.0, "pb": 6.0, "ps": 3.0, "dividend_yield": 0.5,
         "rev_yoy": 20.0, "profit_yoy": 25.0, "roe": 18.0,
         "gross_margin": 22.0, "net_margin": 11.0,
         "report_date": "2026-06-30",
         "value_score": 60.0, "growth_score": None, "quality_score": 50.0,
         "safety_score": 30.0},
        {"market": "HK", "code": "00700", "name": "Tencent",
         "industry": "Internet", "price": 300.0, "market_cap": 2.8e12,
         "pe_ttm": 22.0, "pb": 4.0, "ps": 5.0, "dividend_yield": 1.0,
         "rev_yoy": 12.0, "profit_yoy": 15.0, "roe": 18.0,
         "gross_margin": 45.0, "net_margin": 25.0,
         "report_date": "2026-06-30",
         "value_score": 70.0, "growth_score": 65.0, "quality_score": 55.0,
         "safety_score": 45.0},
        {"market": "US", "code": "AAPL", "name": "Apple",
         "industry": "Electronics", "price": 220.0, "market_cap": 3.3e12,
         "pe_ttm": 30.0, "pb": 40.0, "ps": 8.0, "dividend_yield": 0.5,
         "rev_yoy": 8.0, "profit_yoy": 10.0, "roe": 90.0,
         "gross_margin": 46.0, "net_margin": 25.0,
         "report_date": "2025-12-31",
         "value_score": 50.0, "growth_score": 60.0, "quality_score": 70.0,
         "safety_score": 40.0},
        {"market": "US", "code": "MSFT", "name": "Microsoft",
         "industry": "Software", "price": 400.0, "market_cap": 3.0e12,
         "pe_ttm": 33.0, "pb": 35.0, "ps": 11.0, "dividend_yield": 0.8,
         "rev_yoy": 15.0, "profit_yoy": 20.0, "roe": 35.0,
         "gross_margin": 70.0, "net_margin": 35.0,
         "report_date": "2025-12-31",
         "value_score": 30.0, "growth_score": 80.0, "quality_score": 60.0,
         "safety_score": 60.0},
        {"market": "US", "code": "BADX", "name": "Two Pillars Only",
         "industry": "Misc", "price": 10.0, "market_cap": 2.0e9,
         "pe_ttm": 15.0, "pb": 2.0, "ps": 2.0, "dividend_yield": 0.0,
         "rev_yoy": 5.0, "profit_yoy": 5.0, "roe": 10.0,
         "gross_margin": 20.0, "net_margin": 8.0,
         "report_date": "2025-12-31",
         "value_score": 90.0, "growth_score": 90.0, "quality_score": None,
         "safety_score": None},
    ]
    df = pd.DataFrame(rows)
    # Add momentum/cashflow scores (None for all rows — not in test data)
    df["momentum_score"] = float("nan")
    df["cashflow_score"] = float("nan")
    df["data_completeness"] = (
        df[["value_score", "growth_score", "quality_score",
            "safety_score", "momentum_score",
            "cashflow_score"]].notna().sum(axis=1) / 6.0)
    return df


def _write_snapshot(data_dir: Path, name: str) -> Path:
    snap = data_dir / "snapshots" / name
    snap.mkdir(parents=True)
    _master().to_csv(snap / "master.csv", index=False)
    return snap


# ---------------------------------------------------------------------------
# Snapshot discovery / loading
# ---------------------------------------------------------------------------
def test_find_and_resolve_snapshots(tmp_path):
    _write_snapshot(tmp_path, "20260101")
    latest = _write_snapshot(tmp_path, "20260201")

    assert report.find_snapshots(tmp_path) == ["20260101", "20260201"]
    assert report.resolve_snapshot(tmp_path) == latest
    assert report.resolve_snapshot(tmp_path, "20260101") == (
        tmp_path / "snapshots" / "20260101")
    # dirs without master.csv are not snapshots
    (tmp_path / "snapshots" / "20260301").mkdir()
    assert report.find_snapshots(tmp_path) == ["20260101", "20260201"]


def test_resolve_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="no master.csv"):
        report.resolve_snapshot(tmp_path, "19990101")
    with pytest.raises(FileNotFoundError, match="no snapshots found"):
        report.resolve_snapshot(tmp_path)


def test_load_master_keeps_code_string(tmp_path):
    snap = _write_snapshot(tmp_path, "20260201")
    df = report.load_master(snap)
    # zero-padded codes survive the CSV roundtrip
    assert "00700" in set(df["code"].astype(str))
    assert "600519" in set(df["code"].astype(str))


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def test_screen_balanced_ranking():
    top = report.screen(_master(), preset="balanced", top_n=10)
    assert list(top.columns) == report.REPORT_COLUMNS
    assert list(top["rank"]) == list(range(1, len(top) + 1))
    # expected composite order (BADX dropped: only 2 of 4 pillars)
    assert list(top["code"]) == ["600519", "00700", "AAPL", "MSFT",
                                 "300750", "000858", "601318"]
    assert top.iloc[0]["composite_score"] == pytest.approx(68.5)
    assert top.iloc[1]["composite_score"] == pytest.approx(61.75)
    # missing safety renormalized over the remaining pillars
    assert top.iloc[-1]["composite_score"] == pytest.approx(
        (20 * 0.35 + 10 * 0.25 + 95 * 0.30) / 0.90)


def test_screen_top_n_and_market_filter():
    top = report.screen(_master(), top_n=2)
    assert len(top) == 2
    us = report.screen(_master(), top_n=10, markets=["US"])
    assert set(us["market"]) == {"US"}
    assert set(us["code"]) == {"AAPL", "MSFT"}     # BADX lacks 3 pillars


def test_screen_custom_weights():
    # value-only weights lower the pillar requirement to 1
    top = report.screen(_master(), weights={"value": 1.0}, top_n=10)
    assert list(top["code"]) == ["BADX", "600519", "00700", "300750",
                                 "AAPL", "000858", "MSFT", "601318"]


def test_screen_unknown_preset():
    with pytest.raises(ValueError, match="unknown strategy"):
        report.screen(_master(), preset="nope")


def test_screen_backfills_missing_pillar_scores(capsys):
    """Old snapshots lacking momentum_score/cashflow_score columns
    get momentum recomputed from ret_60d/ret_250d; cashflow stays NaN
    (weights renormalize inside apply_composite)."""
    df = _master().drop(columns=["momentum_score", "cashflow_score"])
    # add kline-derived raw factors so momentum can be recomputed
    df["ret_60d"] = [5.0, -2.0, 10.0, 0.0, -5.0, 3.0, 8.0, 1.0]
    df["ret_250d"] = [20.0, -10.0, 30.0, 5.0, -15.0, 10.0, 25.0, 2.0]
    top = report.screen(df, preset="balanced", top_n=10)
    assert len(top) > 0
    err = capsys.readouterr().err
    assert "backfilling pillar scores" in err


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def test_export_csv(tmp_path):
    top = report.screen(_master(), top_n=3)
    path = report.export_csv(top, tmp_path / "out" / "top.csv")
    assert path.exists()
    back = pd.read_csv(path, dtype={"code": str})
    assert list(back.columns) == report.REPORT_COLUMNS
    assert list(back["rank"]) == [1, 2, 3]
    assert back.iloc[0]["code"] == "600519"


def test_export_markdown(tmp_path):
    top = report.screen(_master(), top_n=3)
    path = report.export_markdown(
        top, tmp_path / "out" / "top.md", title="Value Genie - test",
        meta={"snapshot": "20260201", "strategy": "balanced"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Value Genie - test")
    assert "- **snapshot**: 20260201" in text
    assert "- **strategy**: balanced" in text
    assert "| rank | market | code | name |" in text
    assert "| 1 | A | 600519 | Moutai |" in text


def test_markdown_renders_missing_values(tmp_path):
    top = report.screen(_master(), top_n=10)
    path = report.export_markdown(top, tmp_path / "top.md")
    text = path.read_text(encoding="utf-8")
    # 601318 has no safety score and no ps
    assert "| - |" in text


def test_format_console(tmp_path):
    top = report.screen(_master(), top_n=3)
    text = report.format_console(top)
    assert "600519" in text
    assert "composite_score" in text


def test_describe_weights():
    line = report.describe_weights({"value": 0.35, "growth": 0.25,
                                    "quality": 0.30, "safety": 0.0})
    assert line == "value 0.35 / growth 0.25 / quality 0.30"
