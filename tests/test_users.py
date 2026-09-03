"""Tests for value_genie.users (profiles, styles, holdings)."""

import json

import pytest

from value_genie import users as usr
from value_genie.resolve import Match
from value_genie.strategy import masters  # noqa: F401  (register masters)
from value_genie.strategy.presets import normalize_weights
from value_genie.strategy.registry import get_strategy, list_strategies


@pytest.fixture()
def users_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(usr.config, "USERS_DIR", tmp_path / "users")
    return tmp_path / "users"


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------
def test_create_and_load_roundtrip(users_dir):
    u = usr.create_user("me", name="测试用户", horizon="long")
    path = users_dir / "me.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "me"
    assert data["name"] == "测试用户"
    assert data["style"]["horizon"] == "long"
    assert data["style"]["weights"] == {}

    loaded = usr.load_user("me")
    assert loaded.name == "测试用户"
    assert loaded.created_at
    assert loaded.has_style() is False


def test_create_rejects_bad_or_duplicate_ids(users_dir):
    with pytest.raises(ValueError):
        usr.create_user("Bad-ID")           # uppercase / dash
    with pytest.raises(ValueError):
        usr.create_user("buffett")          # collides with master id
    usr.create_user("me")
    with pytest.raises(ValueError):
        usr.create_user("me")               # duplicate file


def test_load_missing_user_hint(users_dir):
    with pytest.raises(FileNotFoundError) as ei:
        usr.load_user("nobody")
    assert "user create" in str(ei.value)


def test_list_users_skips_corrupt_files(users_dir):
    usr.create_user("a")
    (users_dir / "broken.json").write_text("{not json", encoding="utf-8")
    items = usr.list_users()
    assert [u.id for u in items] == ["a"]


# ---------------------------------------------------------------------------
# Style management
# ---------------------------------------------------------------------------
def test_parse_gate():
    assert usr.parse_gate("roe>=15") == ("roe", ">=", 15.0)
    assert usr.parse_gate("debt_ratio<=60") == ("debt_ratio", "<=", 60.0)
    assert usr.parse_gate("volatility pctl>=60") == \
        ("volatility", "pctl>=", 60.0)
    assert usr.parse_gate("pe_pb<=22.5") == ("pe_pb", "<=", 22.5)
    with pytest.raises(ValueError):
        usr.parse_gate("roe~=15")           # unknown op
    with pytest.raises(ValueError):
        usr.parse_gate("roe>=abc")          # non-numeric value


def test_set_style_weights_and_gates(users_dir):
    usr.create_user("me")
    u = usr.set_style("me", weights={"value": 0.4, "quality": 0.6},
                      gates=[("roe", ">=", 15.0)])
    # normalized to the full six-pillar profile, summing to 1
    assert u.style["weights"] == {"value": 0.4, "quality": 0.6,
                                  "growth": 0.0, "safety": 0.0,
                                  "momentum": 0.0, "cashflow": 0.0}
    assert u.style["gates"] == [["roe", ">=", 15.0]]
    assert u.has_style() is True

    reloaded = usr.load_user("me")
    assert reloaded.has_style() is True


def test_set_style_base_copies_master(users_dir):
    usr.create_user("me")
    u = usr.set_style("me", base="buffett")
    s = get_strategy("buffett")
    assert u.style["weights"] == normalize_weights(s.weights)
    assert u.style["gates"] == [list(g) for g in s.gates]
    assert u.style["horizon"] == "long"

    # explicit overrides merge after base, then renormalize
    merged = dict(s.weights)
    merged["value"] = 1.0
    u = usr.set_style("me", base="buffett",
                      weights={"value": 1.0}, clear_gates=True)
    assert u.style["weights"] == normalize_weights(merged)
    assert u.style["gates"] == []


def test_set_style_bad_horizon(users_dir):
    usr.create_user("me")
    with pytest.raises(ValueError):
        usr.set_style("me", horizon="bogus")


def test_register_user_strategies(users_dir):
    usr.create_user("plain")               # no style -> not registered
    usr.create_user("styled")
    usr.set_style("styled", weights={"value": 0.5, "quality": 0.5})
    out = usr.register_user_strategies()
    assert [s.id for s in out] == ["styled"]
    s = get_strategy("styled")
    assert s.kind == "user"
    assert s.weights["value"] == 0.5
    assert s.horizon == ""

    # shows up in the registry listing
    ids = [x.id for x in list_strategies()]
    assert "styled" in ids


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------
def _match(market="A", code="600519", name="Moutai"):
    return Match(market, code, name, 100.0, "1")


def test_add_update_remove_holding(users_dir):
    u = usr.create_user("me")
    h = usr.add_holding(u, _match(), qty=100, cost=1500.0,
                        opened="2025-03-15")
    assert (h.market, h.code, h.currency) == ("A", "600519", "CNY")
    assert h.opened == "2025-03-15"

    # duplicate rejected
    with pytest.raises(ValueError):
        usr.add_holding(u, _match(), qty=10, cost=1500.0)

    # update partial fields
    h2 = usr.update_holding(u, "A", "600519", qty=200)
    assert h2.qty == 200.0 and h2.cost == 1500.0
    h3 = usr.update_holding(u, "A", "600519", opened="")
    assert h3.opened == ""

    # persistence roundtrip keeps holdings
    usr.save_user(u)
    loaded = usr.load_user("me")
    assert len(loaded.holdings) == 1
    assert loaded.holdings[0].qty == 200.0

    removed = usr.remove_holding(u, "A", "600519")
    assert removed.code == "600519"
    assert u.holdings == []


def test_holding_code_normalization(users_dir):
    u = usr.create_user("me")
    # HK code zero-pads to master.csv form
    hk = usr.add_holding(u, Match("HK", "00116", "Chow Sang Sang",
                                  100.0, "116"),
                         qty=200, cost=9.5)
    assert hk.code == "00116" and hk.currency == "HKD"
    # US ticker uppercased
    us = usr.add_holding(u, Match("US", "aapl", "Apple", 100.0, "105"),
                         qty=10, cost=180.0)
    assert us.code == "AAPL" and us.currency == "USD"

    found = u.holding("HK", "116")         # normalize_code zfills
    assert found is not None and found.qty == 200


def test_holding_input_validation(users_dir):
    u = usr.create_user("me")
    with pytest.raises(ValueError):
        usr.add_holding(u, _match(), qty=0, cost=100.0)
    with pytest.raises(ValueError):
        usr.add_holding(u, _match(), qty=10, cost=-5)
    with pytest.raises(ValueError):
        usr.add_holding(u, _match(), qty=10, cost=100.0,
                        opened="2025/03/15")
    with pytest.raises(ValueError):
        usr.update_holding(u, "A", "000001")   # not held
    with pytest.raises(ValueError):
        usr.remove_holding(u, "A", "000001")   # not held


# ---------------------------------------------------------------------------
# CLI: user / holding commands
# ---------------------------------------------------------------------------
def test_cli_user_create_list_show(users_dir, capsys):
    from value_genie.__main__ import main
    assert main(["user", "create", "me", "--name", "tester"]) == 0
    with pytest.raises(SystemExit):
        main(["user", "create", "me"])                  # duplicate
    assert main(["user", "list"]) == 0
    out = capsys.readouterr().out
    assert "me" in out and "tester" in out

    assert main(["user", "show", "me"]) == 0
    out = capsys.readouterr().out
    assert "style" in out and "(unset" in out


def test_cli_user_set_style(users_dir, capsys):
    from value_genie.__main__ import main
    main(["user", "create", "me"])
    rc = main(["user", "set-style", "me", "--base", "buffett",
               "--weight", "value=0.3", "--gate", "roe>=15",
               "--horizon", "long"])
    assert rc == 0
    u = usr.load_user("me")
    # merge semantics: buffett profile with value overridden, renormalized
    s = get_strategy("buffett")
    expected = dict(s.weights)
    expected["value"] = 0.3
    expected = normalize_weights(expected)
    assert u.style["weights"] == expected
    assert ["roe", ">=", 15.0] in u.style["gates"]
    assert u.style["horizon"] == "long"

    out = capsys.readouterr().out
    assert "style set for me" in out
    assert "gates: roe >= 15" in out
    assert "horizon: long" in out
    assert "usable as" not in out   # human coaching removed (AI-only CLI)


def test_cli_holding_add_requires_user(users_dir, monkeypatch, capsys):
    from value_genie import __main__ as cli
    monkeypatch.setattr(cli, "_resolve_stock_or_exit",
                        lambda q: _match())
    # add auto-creates the user
    assert cli.main(["holding", "add", "me", "贵州茅台",
                     "--qty", "100", "--cost", "1500"]) == 0
    u = usr.load_user("me")
    assert len(u.holdings) == 1
    assert u.holdings[0].name == "Moutai"
