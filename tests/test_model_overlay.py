"""Tests for the model fusion layer (masters-vote wiring + ask block)."""

import pandas as pd
import pytest

from value_genie import config
from value_genie.model import store


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


def _seed_result(upside=25.0):
    years = [{"fy": 2024, "revenue": 100.0, "ebit": 20.0, "shares": 10.0,
              "cash": 20.0, "debt": 10.0}]
    store.save_history(store.new_history("A", "600900", source="t",
                                         currency="CNY", years=years))
    h = store.load_history("A", "600900")
    store.save_result({"id": "A:600900", "market": "A", "code": "600900",
                       "history_hash": h["history_hash"],
                       "weighted_per_share": 30.0,
                       "upside_pct": upside,
                       "scenarios": {"base": {"prob": 1.0,
                                              "per_share": 30.0}},
                       "price": 24.0, "currency": "CNY"})


def test_overlay_end_to_end(mdir):
    _seed_result()
    df = pd.DataFrame({
        "market": ["A"], "code": ["600900"], "core_business": [80.0],
        "core_culture": [70.0], "core_dcf": [50.0], "core_gaps": [None]})
    out, n = store.apply_modeled_dcf(df)
    assert n == 1
    assert out.loc[0, "core_dcf"] != 50.0
    assert store.DCF_MODELED in out.loc[0, "core_gaps"]


def test_ask_model_block(mdir, monkeypatch):
    _seed_result()
    from value_genie import analyze as az
    # 单股 overlay: model_summary 返回摘要 dict 或 None
    s = az.model_summary("A", "600900")
    assert s is not None
    assert s["weighted_per_share"] == 30.0
    assert s["upside_pct"] == 25.0
    assert s["stale"] is False
    assert az.model_summary("A", "000001") is None
