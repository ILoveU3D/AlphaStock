"""Tests for value_genie.model.comps (trading comps table)."""

import pandas as pd
import pytest

from value_genie.model import comps


def _master():
    rows = [{"market": "A", "code": f"60000{i}", "name": f"P{i}",
             "industry": "电力", "price": 10.0 + i, "pe_ttm": 10.0 + i,
             "pb": 1.0 + i / 10, "ps": 2.0 + i / 10,
             "market_cap": 1e10 * (i + 1)} for i in range(1, 9)]
    rows.append({"market": "A", "code": "600900", "name": "目标",
                 "industry": "电力", "price": 25.0, "pe_ttm": 20.0,
                 "pb": 2.5, "ps": 3.0, "market_cap": 5e10})
    rows.append({"market": "A", "code": "000001", "name": "外行",
                 "industry": "银行", "price": 12.0, "pe_ttm": 5.0,
                 "pb": 0.6, "ps": 1.0, "market_cap": 2e11})
    return pd.DataFrame(rows)


class TestSelectPeers:
    def test_same_industry_excludes_self(self):
        df = _master()
        peers = comps.select_peers(df, "A", "600900", "电力")
        assert "600900" not in set(peers["code"])
        assert set(peers["industry"]) == {"电力"}
        assert len(peers) == 8

    def test_cap_by_market_cap_proximity(self):
        df = _master()
        peers = comps.select_peers(df, "A", "600900", "电力", limit=3)
        assert len(peers) == 3
        # 目标市值 5e10 → log 最接近的三家是 5e10/6e10/4e10
        assert set(peers["code"]) == {"600004", "600005", "600003"}

    def test_no_industry_falls_back_to_market(self):
        df = _master()
        peers = comps.select_peers(df, "A", "600900", None)
        assert "600900" not in set(peers["code"])
        assert len(peers) == 9


class TestCompsTable:
    def test_median_multiples_and_implied(self):
        df = _master()
        peers = comps.select_peers(df, "A", "600900", "电力")
        table = comps.comps_table(peers)
        assert len(table["rows"]) == 8
        med = table["medians"]
        # pe 中位 of 11..18 = 14.5；目标 EPS = 25/20 = 1.25 → 隐含 18.125
        assert med["pe_ttm"] == pytest.approx(14.5)
        target = df[df["code"] == "600900"].iloc[0]
        implied = comps.implied_range(target, med)
        assert implied["by_pe"] == pytest.approx(14.5 * 25.0 / 20.0)
        assert implied["by_pb"] == pytest.approx(med["pb"] * 25.0 / 2.5)
        assert implied["by_ps"] == pytest.approx(med["ps"] * 25.0 / 3.0)
        assert implied["low"] <= implied["mid"] <= implied["high"]

    def test_missing_multiple_declared(self):
        df = _master()
        df.loc[df["code"] == "600001", "pe_ttm"] = None
        peers = comps.select_peers(df, "A", "600900", "电力")
        table = comps.comps_table(peers)
        assert table["rows"][0]["pe_ttm"] is None or \
            all(r["code"] != "600001" or r["pe_ttm"] is None
                for r in table["rows"])
        # 中位数跳过缺失：12..18 的中位 = 15.0
        assert table["medians"]["pe_ttm"] == pytest.approx(15.0)
