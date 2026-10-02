"""Tests for the model CLI (json purity, gate behavior)."""

import json

import pytest

from value_genie import __main__ as cli
from value_genie import config


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


def _seed(market="US", code="TEST"):
    from value_genie.model import store
    years = [{"fy": y, "revenue": 100.0 * (1.1 ** (y - 2021)),
              "ebit": 20.0, "net_income": 15.0, "da": 3.0, "capex": 5.0,
              "ocf": 18.0, "cash": 20.0, "debt": 10.0, "shares": 10.0}
             for y in (2022, 2023, 2024)]
    store.save_history(store.new_history(market, code, name="T",
                                         source="test", currency="USD",
                                         years=years))


def test_build_writes_result_and_json(capsys, mdir, monkeypatch):
    _seed()
    monkeypatch.setattr(cli, "_check_freshness", lambda args: True)
    monkeypatch.setattr(cli, "_model_price", lambda m, args: 20.0)
    monkeypatch.setattr(cli, "_model_master", lambda args: None)
    monkeypatch.setattr(cli, "_resolve_stock_or_exit",
                        lambda q: _FakeMatch())
    rc = cli.main(["model", "build", "US:TEST", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["weighted_per_share"] is not None
    assert out["upside_pct"] is not None


def test_build_gate_fail_blocks(capsys, mdir, monkeypatch):
    _seed()
    monkeypatch.setattr(cli, "_check_freshness", lambda args: False)
    rc = cli.main(["model", "build", "US:TEST", "--json"])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_build_without_history_fails(capsys, mdir, monkeypatch):
    monkeypatch.setattr(cli, "_check_freshness", lambda args: True)
    monkeypatch.setattr(cli, "_resolve_stock_or_exit",
                        lambda q: _FakeMatch())
    rc = cli.main(["model", "build", "US:TEST", "--json"])
    assert rc == 1


def test_set_requires_reason(capsys, mdir, monkeypatch):
    _seed()
    from value_genie.model import store
    store.save_assumptions(store.default_assumptions("US", "TEST"))
    monkeypatch.setattr(cli, "_resolve_stock_or_exit",
                        lambda q: _FakeMatch())
    rc = cli.main(["model", "set", "US:TEST", "wacc=0.11", "--json"])
    assert rc == 1
    rc = cli.main(["model", "set", "US:TEST", "wacc=0.11",
                   "--reason", "调贴现率", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["wacc"] == 0.11


def test_list_json(capsys, mdir):
    rc = cli.main(["model", "list", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


class _FakeMatch:
    market, code, name = "US", "TEST", "Test Co"

    def label(self):
        return "TEST (US)"
