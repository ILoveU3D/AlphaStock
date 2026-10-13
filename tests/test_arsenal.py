"""Arsenal registry integrity + statsutil + CLI smoke tests.

Weapon-specific formula tests live in test_arsenal_value.py /
test_arsenal_price.py / test_arsenal_deep.py / test_arsenal_forensic.py;
this file guards the registry contract itself (精品四关: every weapon
has lineage and limits; id == filename; module importable with run()).
"""

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

from polar_star.arsenal import (build_context, get_weapon, list_weapons,
                                load_registry, weapon_runner)
from polar_star.arsenal import statsutil as su
from polar_star.__main__ import build_parser, main

REQUIRED_FIELDS = ("id", "family", "stage", "sweepable", "status",
                   "inputs", "lineage", "limits")


class TestRegistryIntegrity:
    def test_every_json_has_required_fields(self):
        for p in sorted(Path(
                __file__).resolve().parent.parent.glob(
                "polar_star/arsenal/registry/*.json")):
            meta = json.loads(p.read_text(encoding="utf-8"))
            for f in REQUIRED_FIELDS:
                assert f in meta, f"{p.name} missing field {f!r}"

    def test_id_equals_filename(self):
        for wid, meta in load_registry(force=True).items():
            assert wid == meta["id"]

    def test_status_and_stage_vocab(self):
        for m in list_weapons():
            assert m["status"] in ("armed", "dormant"), m["id"]
            assert m["stage"] in ("cross-section", "deep"), m["id"]

    def test_lineage_and_limits_nonempty(self):
        # 入册门票: verified lineage; 精品四关: limits name failure
        # conditions. An empty lineage/limits entry is a ticket forgery.
        for m in list_weapons():
            assert (m.get("lineage") or {}).get("source"), m["id"]
            assert m.get("limits"), m["id"]

    def test_armed_modules_import_and_expose_run(self):
        for m in list_weapons(status="armed"):
            mod = importlib.import_module(
                f"polar_star.arsenal.{m['module']}")
            assert callable(getattr(mod, "run", None)), m["id"]

    def test_dormant_modules_also_expose_run(self):
        # dormant = waiting for data, not missing code; run() must
        # answer honestly (status dormant + wake condition).
        for m in list_weapons(status="dormant"):
            mod = importlib.import_module(
                f"polar_star.arsenal.{m['module']}")
            assert callable(getattr(mod, "run", None)), m["id"]

    def test_unknown_weapon_raises_with_known_ids(self):
        with pytest.raises(ValueError, match="unknown weapon"):
            get_weapon("no-such-weapon")


class TestStatsutil:
    def test_num_or_none(self):
        assert su.num_or_none("3.5") == 3.5
        assert su.num_or_none(float("nan")) is None
        assert su.num_or_none(float("inf")) is None
        assert su.num_or_none(None) is None
        assert su.num_or_none("abc") is None

    def test_xsec_pctl_within_market(self):
        df = pd.DataFrame({"market": ["A", "A", "US", "US"],
                           "v": [1.0, 2.0, 100.0, 200.0]})
        p = su.xsec_pctl(df["v"], df["market"])
        # percentiles are within-market: the A-share 2.0 and the US
        # 200.0 are both the top of their own universe
        assert p.tolist() == [50.0, 100.0, 50.0, 100.0]

    def test_zscore(self):
        s = pd.Series([1.0, 2.0, 3.0])
        z = su.zscore(s)
        assert abs(z.mean()) < 1e-12
        assert z.iloc[2] > 0 > z.iloc[0]

    def test_decile(self):
        s = pd.Series(range(100), dtype=float)
        d = su.decile(s)
        assert d.iloc[0] == 1 and d.iloc[99] == 10

    def test_ols_exact(self):
        x = pd.Series(range(50), dtype=float)
        y = 2.0 * x + 1.0
        out = su.ols(y, x)
        assert out["beta"] == pytest.approx(2.0)
        assert out["alpha"] == pytest.approx(1.0)
        assert out["r2"] == pytest.approx(1.0)
        assert out["resid"].abs().max() < 1e-9

    def test_ols_too_short(self):
        out = su.ols(pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]))
        assert out["beta"] is None and out["n"] == 2

    def test_ledoit_wolf_shrinks_toward_identity(self):
        import numpy as np
        cov = np.array([[0.04, 0.03], [0.03, 0.09]])
        shrunk, delta = su.ledoit_wolf_shrink(cov, n_obs=10)
        assert 0.0 <= delta <= 1.0
        assert shrunk[0, 1] <= cov[0, 1]  # off-diagonal pulled in
        assert np.all(np.linalg.eigvals(shrunk) > 0)

    def test_pert_sample_degenerate_and_bounds(self):
        import numpy as np
        rng = np.random.default_rng(0)
        pt = su.pert_sample(rng, 5.0, 5.0, 5.0, 100)
        assert (pt == 5.0).all()
        draws = su.pert_sample(rng, 1.0, 2.0, 5.0, 5000)
        assert draws.min() >= 1.0 and draws.max() <= 5.0
        # modified-PERT (Vose): with mu=(lo+4m+hi)/6=2.3333, the beta
        # mean is a/(a+b) = 2.3333/6, so E[draw] = lo + (hi-lo)*E[x]
        # = 1 + 4*0.38889 = 2.5556 (the (lo+4m+hi)/6 form is the PERT
        # approximation, not the exact beta mean — pinned behavior).
        assert draws.mean() == pytest.approx(2.5556, abs=0.05)

    def test_winsorize_clips_tails(self):
        s = pd.Series([0.0] * 98 + [1e6, -1e6])
        w = su.winsorize(s, 0.01, 0.99)
        assert w.max() < 1e6 and w.min() > -1e6


class TestArsenalCli:
    def test_list_json(self, capsys):
        assert main(["arsenal", "list", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["count"] == len(list_weapons())
        assert all("id" in w for w in out["weapons"])

    def test_list_filters(self, capsys):
        assert main(["arsenal", "list", "--status", "dormant",
                     "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert all(w["status"] == "dormant" for w in out["weapons"])

    def test_show_json(self, capsys):
        wid = list_weapons()[0]["id"]
        assert main(["arsenal", "show", wid, "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["id"] == wid

    def test_stats_json(self, capsys):
        assert main(["arsenal", "stats", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["total"] == len(list_weapons())
        assert set(out["by_status"]) <= {"armed", "dormant"}

    def test_dormant_run_is_honest(self):
        # a dormant weapon must say so (never fabricate a reading)
        for m in list_weapons(status="dormant"):
            out = weapon_runner(m["id"])({"snap": None, "master": None})
            assert out.get("status") == "dormant", m["id"]
            assert out.get("reason"), m["id"]
