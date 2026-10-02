# 财务建模能力实施计划（financial modeling）

> **For agentic workers:** 按任务顺序执行；每任务 TDD（先写失败测试 → 跑挂 → 最小实现 → 跑过 → 本地提交）。Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Git 纪律（项目铁律）**：只做**本地提交**，永不 push；PR 由用户自己开。

**Goal:** 为 value_genie 增加"多年三表历史 + 可调假设驱动因子 FCFF DCF + 敏感性 + comps 表"的建模能力，并融合进 masters-vote / ask / 持仓深评流程（建模时机由 AI 按 skills/19 触发条件决定）。

**Architecture:** 新子包 `value_genie/model/`（history/engine/comps/store 四模块）+ 本地-only `models/` 目录（gitignored，同 profiles/ 规则）。引擎纯函数无 IO；history 网络入口模块级（monkeypatch 边界）；core_dcf 升级钩平行于 profile 的 D3 文化钩（overlay 函数，不改 cores.py 签名）。

**Tech Stack:** Python 3.10+, pandas + requests only（无新依赖）。Spec: `docs/plans/2026-10-02-financial-modeling.md`。

**关键既有模式（执行前必读）:**
- store 模式: `value_genie/profile.py` L45-120（路径/原子写/_load_json）与 L233-272（`apply_distilled_culture` overlay——dcf 钩照抄此形）
- CLI 模式: `value_genie/__main__.py` cmd_profile L1445-1600、parser 注册 L2083-2120、新鲜度闸门 `_check_freshness` L969-990、D3 钩接线 L205-213
- ask 三核块: `value_genie/analyze.py` L426-446
- US CIK: `value_genie/fetch/fundamentals.py` `load_sec_cik_map()` / `normalize_us_ticker()`
- datacenter 探针铁律: 日期单引号、字符串双引号、success=false + code 9201 = 合法空窗口
- 测试模式: `tests/test_profile.py`（monkeypatch config 目录到 tmp_path，文件独立）

---

### Task 1: config 常量 + .gitignore

**Files:**
- Modify: `value_genie/config.py`（PROFILES_DIR 块之后，L304 后）
- Modify: `.gitignore`（profiles/ 块之后）

- [ ] **Step 1: 修改 config.py**

在 `SA_PROFILE_URL_TMPL` 行之后追加：

```python
# ---------------------------------------------------------------------------
# Financial models (2026-10-02 design): driver-based FCFF DCF + comps,
# AI-triggered at L3 (skills/19). LOCAL-ONLY: MODELS_DIR is gitignored and
# NEVER pushed — the model is the user's proprietary judgment (same rule
# as PROFILES_DIR).
# ---------------------------------------------------------------------------
MODELS_DIR = BASE_DIR / "models"                 # assumptions/results, untracked
MODEL_HISTORY_YEARS = 5                          # annual statements per stock
MODEL_SCENARIOS = ("bear", "base", "bull")
MODEL_DEFAULT_PROBS = {"bear": 0.25, "base": 0.50, "bull": 0.25}
MODEL_SENSITIVITY_WACC = (0.08, 0.09, 0.10, 0.11, 0.12)
MODEL_SENSITIVITY_TG = (0.015, 0.02, 0.025, 0.03, 0.035)
# fallback driver ratios when history lacks the field (declared in gaps)
MODEL_FALLBACK_DA_PCT = 0.03
MODEL_FALLBACK_CAPEX_PCT = 0.05
MODEL_FALLBACK_NWC_PCT = 0.10
CORE_ANCHORS["model_upside"] = (-30.0, 50.0)     # model upside % -> 0..100
```

- [ ] **Step 2: 修改 .gitignore**

在 `profiles/` 块之后追加：

```gitignore
# Financial models are LOCAL-ONLY (2026-10-02 design): assumptions +
# valuation results are proprietary judgment — never pushed to any remote
models/
```

- [ ] **Step 3: 验证 import**

Run: `python -B -c "from value_genie import config; print(config.MODELS_DIR, config.CORE_ANCHORS['model_upside'])"`
Expected: 打印路径与 (-30.0, 50.0)

- [ ] **Step 4: Commit**

```bash
git add value_genie/config.py .gitignore
git commit -m "feat(model): config constants + gitignore for local-only models/"
```

---

### Task 2: model/store.py — 持久化 + 默认假设 + dcf overlay

**Files:**
- Create: `value_genie/model/__init__.py`
- Create: `value_genie/model/store.py`
- Test: `tests/test_model_store.py`

- [ ] **Step 1: 写失败测试** `tests/test_model_store.py`

```python
"""Tests for value_genie.model.store (local-only model persistence)."""

import pandas as pd
import pytest

from value_genie import config
from value_genie.model import store


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


def _history(fy=(2022, 2023, 2024)):
    years = [{"fy": y, "revenue": 100e8 * (1.1 ** (y - 2022)),
              "ebit": 15e8, "net_income": 12e8, "da": 3e8, "capex": 5e8,
              "ocf": 14e8, "cash": 20e8, "debt": 10e8, "shares": 1e8}
             for y in fy]
    return store.new_history("A", "600900", name="长江电力",
                             source="test", currency="CNY", years=years)


class TestHistory:
    def test_roundtrip_and_hash(self, mdir):
        h = _history()
        p = store.save_history(h)
        assert p.exists()
        assert p.parent.name == "a"
        loaded = store.load_history("A", "600900")
        assert loaded["years"][-1]["fy"] == 2024
        assert loaded["history_hash"] == h["history_hash"]
        assert len(h["history_hash"]) == 12

    def test_load_missing_returns_none(self, mdir):
        assert store.load_history("A", "000001") is None
        assert store.load_assumptions("A", "000001") is None
        assert store.load_result("A", "000001") is None

    def test_corrupt_raises(self, mdir):
        p = store.history_path("A", "600900")
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            store.load_history("A", "600900")


class TestDefaults:
    def test_default_assumptions_from_history(self, mdir):
        store.save_history(_history())
        a = store.default_assumptions("A", "600900")
        assert a["version"] == 1
        assert set(a["scenarios"]) == {"bear", "base", "bull"}
        probs = [s["prob"] for s in a["scenarios"].values()]
        assert abs(sum(probs) - 1.0) < 1e-9
        base = a["scenarios"]["base"]
        assert len(base["revenue_growth"]) == a["horizon_years"]
        # 历史中位增速 ~10% → base 首年增速应接近 0.10
        assert base["revenue_growth"][0] == pytest.approx(0.10, abs=0.02)
        assert a["wacc"] == config.DCF_DISCOUNT
        assert a["terminal_g"] == config.DCF_TERMINAL_G
        assert a["net_debt"] == pytest.approx(10e8 - 20e8)
        assert a["shares"] == pytest.approx(1e8)

    def test_missing_fields_declared_in_gaps(self, mdir):
        h = _history()
        for y in h["years"]:
            y["da"] = None
            y["capex"] = None
        store.save_history(h)
        a = store.default_assumptions("A", "600900")
        assert any("da" in g or "capex" in g for g in a["gaps"])
        assert a["scenarios"]["base"]["capex_pct_rev"] == \
            config.MODEL_FALLBACK_CAPEX_PCT


class TestSetAndResult:
    def test_set_appends_changelog(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        a = store.set_assumptions(
            "A", "600900",
            {"base.revenue_growth": [0.2, 0.18, 0.15, 0.12, 0.10],
             "wacc": 0.11}, reason="年报读后上调")
        assert a["wacc"] == 0.11
        assert a["scenarios"]["base"]["revenue_growth"][0] == 0.2
        assert len(a["changelog"]) == 2
        assert a["changelog"][0]["reason"] == "年报读后上调"
        # 持久化
        assert store.load_assumptions("A", "600900")["wacc"] == 0.11

    def test_set_requires_reason(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        with pytest.raises(ValueError):
            store.set_assumptions("A", "600900", {"wacc": 0.11}, reason="")

    def test_set_unknown_key_raises(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        with pytest.raises(ValueError):
            store.set_assumptions("A", "600900", {"bogus": 1}, reason="x")

    def test_result_stale_on_history_change(self, mdir):
        store.save_history(_history())
        r = {"id": "A:600900", "market": "A", "code": "600900",
             "history_hash": store.load_history("A", "600900")
                             ["history_hash"],
             "weighted_per_share": 30.0, "upside_pct": 12.0}
        store.save_result(r)
        assert not store.is_stale(store.load_result("A", "600900"),
                                  store.load_history("A", "600900"))
        store.save_history(_history(fy=(2023, 2024, 2025)))
        assert store.is_stale(store.load_result("A", "600900"),
                              store.load_history("A", "600900"))


class TestDcfOverlay:
    def _frame(self):
        return pd.DataFrame({
            "market": ["A", "A"], "code": ["600900", "000001"],
            "core_business": [80.0, 60.0], "core_culture": [70.0, 60.0],
            "core_dcf": [50.0, 40.0],
            "core_gaps": ["culture unscored", None]})

    def test_overlay_replaces_core_dcf(self, mdir):
        df = self._frame()
        out, n = store.apply_modeled_dcf(
            df, scores={"A:600900": 25.0})   # upside 25%
        assert n == 1
        lo, hi = config.CORE_ANCHORS["model_upside"]
        expect = (25.0 - lo) / (hi - lo) * 100.0
        assert out.loc[0, "core_dcf"] == pytest.approx(expect)
        assert out.loc[0, "core_score"] == pytest.approx(
            (80.0 + 70.0 + expect) / 3)
        assert store.DCF_MODELED in out.loc[0, "core_gaps"]
        # 无模型行不动
        assert out.loc[1, "core_dcf"] == 40.0

    def test_load_dcf_scores_skips_stale(self, mdir):
        store.save_history(_history())
        h = store.load_history("A", "600900")
        store.save_result({"id": "A:600900", "market": "A", "code": "600900",
                           "history_hash": h["history_hash"],
                           "weighted_per_share": 30.0, "upside_pct": 25.0})
        assert store.load_dcf_scores() == {"A:600900": 25.0}
        store.save_history(_history(fy=(2023, 2024, 2025)))
        assert store.load_dcf_scores() == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_store.py -q`
Expected: FAIL（`ModuleNotFoundError: value_genie.model`）

- [ ] **Step 3: 实现** `value_genie/model/__init__.py`

```python
"""Financial models: driver-based FCFF DCF + comps (design 2026-10-02).

AI-triggered at L3 (skills/19 trigger conditions); models/ is LOCAL-ONLY
and never pushed — the model is the user's proprietary judgment.
"""
```

- [ ] **Step 4: 实现** `value_genie/model/store.py`

```python
"""Model persistence: history / assumptions / result under models/ (LOCAL-
ONLY, untracked — same rule as profiles/). Also the DCF overlay hook
(D3-parallel): a built model's probability-weighted upside replaces the
reverse-DCF anchor in core_dcf for that row only.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import config
from ..users import normalize_code

SCHEMA_VERSION = 1

# marker written into core_gaps when a model supplies the dcf core
DCF_MODELED = "dcf modeled (model build)"

_SCENARIO_DRIVER_KEYS = ("revenue_growth", "ebit_margin", "da_pct_rev",
                         "capex_pct_rev", "nwc_pct_drev", "prob")
_TOP_KEYS = ("version", "horizon_years", "wacc", "terminal_g", "tax_rate",
             "net_debt", "shares", "currency")


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Paths & persistence
# ---------------------------------------------------------------------------
def models_dir() -> Path:
    return Path(config.MODELS_DIR)


def _stock_dir(market: str, code: str) -> Path:
    code = normalize_code(market, code)
    return models_dir() / market.lower() / code


def history_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "history.json"


def assumptions_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "assumptions.json"


def result_path(market: str, code: str) -> Path:
    return _stock_dir(market, code) / "result.json"


def raw_dir(market: str, code: str) -> Path:
    """Drop-in dir for audit-opinion / DD material text the AI reads."""
    return _stock_dir(market, code) / "raw"


def _hash_years(years: list) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(years, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:12]


def _load_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt {what} file {path}: {exc}") from None
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(
            f"corrupt {what} file {path}: top level must be an object "
            f"with an 'id'")
    return data


def _save(path: Path, data: dict) -> Path:
    from ..atomic import atomic_write_text
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def new_history(market: str, code: str, name: str = "", source: str = "",
                currency: str = "", years: list | None = None,
                gaps: list | None = None) -> dict:
    code = normalize_code(market, code)
    years = list(years or [])
    return {
        "id": f"{market}:{code}", "market": market, "code": code,
        "name": name, "fetched_at": _now(), "source": source,
        "currency": currency, "years": years,
        "history_hash": _hash_years(years), "gaps": list(gaps or []),
    }


def save_history(h: dict) -> Path:
    return _save(history_path(h["market"], h["code"]), h)


def load_history(market: str, code: str) -> dict | None:
    p = history_path(market, code)
    return _load_json(p, "model history") if p.exists() else None


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------
def _median(vals: list) -> float | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _pct(numer, denom) -> float | None:
    if numer is None or not denom:
        return None
    return numer / denom


def default_assumptions(market: str, code: str) -> dict:
    """Derive default drivers from history medians (last 3 years); missing
    fields fall back to config constants and are declared in gaps."""
    h = load_history(market, code)
    if h is None:
        raise ValueError(f"no history for {market}:{code} — "
                         f"run `model fetch` first")
    years = h["years"][-3:]
    gaps = []

    growths, margins, das, capexs, nwcs = [], [], [], [], []
    prev_rev = None
    for y in (h["years"][-4:] if len(h["years"]) >= 4 else h["years"]):
        rev = y.get("revenue")
        if prev_rev and rev:
            growths.append(rev / prev_rev - 1.0)
            nwcs.append(config.MODEL_FALLBACK_NWC_PCT)
        prev_rev = rev
        m = _pct(y.get("ebit"), rev)
        if m is not None:
            margins.append(m)
        d = _pct(y.get("da"), rev)
        if d is not None:
            das.append(d)
        c = _pct(y.get("capex"), rev)
        if c is not None:
            capexs.append(c)

    g0 = _median(growths)
    m0 = _median(margins)
    if g0 is None:
        g0 = 0.05
        gaps.append("no revenue history -> base growth defaults to 5%")
    if m0 is None:
        m0 = 0.15
        gaps.append("no ebit history -> base margin defaults to 15%")
    da = _median(das)
    if da is None:
        da = config.MODEL_FALLBACK_DA_PCT
        gaps.append("no da history -> fallback da_pct_rev")
    capex = _median(capexs)
    if capex is None:
        capex = config.MODEL_FALLBACK_CAPEX_PCT
        gaps.append("no capex history -> fallback capex_pct_rev")

    n = config.MODEL_HISTORY_YEARS
    fade = [round(g0 * (1 - 0.15 * i), 4) for i in range(n)]  # 逐年衰减15%
    margins_path = [round(m0, 4)] * n
    last = h["years"][-1]

    def _scenario(scale_g, scale_m, prob):
        return {"prob": prob,
                "revenue_growth": [round(g * scale_g, 4) for g in fade],
                "ebit_margin": [round(m * scale_m, 4) for m in margins_path],
                "da_pct_rev": round(da, 4), "capex_pct_rev": round(capex, 4),
                "nwc_pct_drev": _median(nwcs) or config.MODEL_FALLBACK_NWC_PCT}

    return {
        "id": h["id"], "market": h["market"], "code": h["code"],
        "version": SCHEMA_VERSION, "updated_at": _now(),
        "horizon_years": n, "wacc": config.DCF_DISCOUNT,
        "terminal_g": config.DCF_TERMINAL_G, "tax_rate": 0.15,
        "currency": h.get("currency") or "",
        "net_debt": (last.get("debt") or 0) - (last.get("cash") or 0)
        if last.get("debt") is not None or last.get("cash") is not None
        else None,
        "shares": last.get("shares"),
        "scenarios": {
            "bear": _scenario(0.5, 0.8, config.MODEL_DEFAULT_PROBS["bear"]),
            "base": _scenario(1.0, 1.0, config.MODEL_DEFAULT_PROBS["base"]),
            "bull": _scenario(1.5, 1.15, config.MODEL_DEFAULT_PROBS["bull"]),
        },
        "gaps": gaps, "changelog": [],
    }


def save_assumptions(a: dict) -> Path:
    return _save(assumptions_path(a["market"], a["code"]), a)


def load_assumptions(market: str, code: str) -> dict | None:
    p = assumptions_path(market, code)
    return _load_json(p, "model assumptions") if p.exists() else None


def set_assumptions(market: str, code: str, updates: dict,
                    reason: str) -> dict:
    """Apply dotted-key updates (e.g. 'base.revenue_growth', 'wacc');
    every change appends a changelog entry — reason is mandatory."""
    if not reason or not reason.strip():
        raise ValueError("--reason is required for every assumption change")
    a = load_assumptions(market, code)
    if a is None:
        raise ValueError(f"no assumptions for {market}:{code} — "
                         f"run `model build` first (defaults are generated)")
    for key, val in updates.items():
        parts = key.split(".")
        if parts[0] in config.MODEL_SCENARIOS:
            if len(parts) != 2 or parts[1] not in _SCENARIO_DRIVER_KEYS:
                raise ValueError(f"unknown assumption key: {key}")
            old = a["scenarios"][parts[0]][parts[1]]
            a["scenarios"][parts[0]][parts[1]] = val
        elif len(parts) == 1 and key in _TOP_KEYS and key != "version":
            old = a[key]
            a[key] = val
        else:
            raise ValueError(f"unknown assumption key: {key}")
        a.setdefault("changelog", []).append(
            {"at": _now(), "key": key, "from": old, "to": val,
             "reason": reason.strip()})
    a["updated_at"] = _now()
    save_assumptions(a)
    return a


# ---------------------------------------------------------------------------
# Results & staleness
# ---------------------------------------------------------------------------
def save_result(r: dict) -> Path:
    r = dict(r)
    r.setdefault("built_at", _now())
    return _save(result_path(r["market"], r["code"]), r)


def load_result(market: str, code: str) -> dict | None:
    p = result_path(market, code)
    return _load_json(p, "model result") if p.exists() else None


def is_stale(result: dict | None, history: dict | None) -> bool:
    """Result pins the history hash it was built from; a refetched/changed
    history (new reporting period) marks it STALE until rebuilt."""
    if result is None:
        return False
    if history is None:
        return True
    return result.get("history_hash") != history.get("history_hash")


def list_models() -> list:
    """Coverage + staleness report: one row per built model."""
    out = []
    d = models_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*/*/result.json")):
        try:
            r = _load_json(p, "model result")
        except ValueError:
            continue
        h = load_history(r["market"], r["code"])
        out.append({"id": r["id"], "built_at": r.get("built_at"),
                    "weighted_per_share": r.get("weighted_per_share"),
                    "upside_pct": r.get("upside_pct"),
                    "stale": is_stale(r, h)})
    return out


# ---------------------------------------------------------------------------
# DCF overlay hook (D3-parallel to profile.apply_distilled_culture)
# ---------------------------------------------------------------------------
def load_dcf_scores() -> dict:
    """{id: upside_pct} for built, non-stale models."""
    scores = {}
    for row in list_models():
        if row["stale"] or row["upside_pct"] is None:
            continue
        scores[row["id"]] = float(row["upside_pct"])
    return scores


def _anchor_upside(upside_pct: float) -> float:
    lo, hi = config.CORE_ANCHORS["model_upside"]
    v = (upside_pct - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, v))


def apply_modeled_dcf(df: pd.DataFrame, scores: dict | None = None) -> tuple:
    """Overlay modeled dcf scores onto a scored frame (D3-parallel hook).

    Rows WITH a built, non-stale model get ``core_dcf`` = anchored model
    upside, ``core_score`` recomputed, and DCF_MODELED in core_gaps.
    Rows without one keep the reverse-DCF anchor. Returns (frame, count).
    Pure display-layer transform — the stored snapshot is not modified.
    """
    if scores is None:
        scores = load_dcf_scores()
    if not scores or "market" not in df.columns \
            or "code" not in df.columns:
        return df, 0
    out = df.copy()
    ids = out["market"].astype(str) + ":" + out["code"].astype(str)
    mapped = pd.to_numeric(ids.map(scores), errors="coerce")
    has = mapped.notna()
    n = int(has.sum())
    if n == 0:
        return out, 0
    out.loc[has, "core_dcf"] = mapped[has].map(_anchor_upside)
    cols = [c for c in ("core_business", "core_culture", "core_dcf")
            if c in out.columns]
    out["core_score"] = out[cols].mean(axis=1, skipna=True)
    if "core_gaps" in out.columns:
        def _fix(g):
            tag = DCF_MODELED
            if not isinstance(g, str) or not g:
                return tag
            return g if tag in g else g + "; " + tag
        out.loc[has, "core_gaps"] = out.loc[has, "core_gaps"].map(_fix)
    return out, n
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_store.py -q`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add value_genie/model/__init__.py value_genie/model/store.py tests/test_model_store.py
git commit -m "feat(model): store — history/assumptions/result persistence + DCF overlay hook"
```

---

### Task 3: model/engine.py — 驱动因子 FCFF DCF（纯函数）

**Files:**
- Create: `value_genie/model/engine.py`
- Test: `tests/test_model_engine.py`

- [ ] **Step 1: 写失败测试** `tests/test_model_engine.py`

```python
"""Tests for value_genie.model.engine (pure driver-based FCFF DCF)."""

import pytest

from value_genie.model import engine


def _scenario(g=0.10, m=0.20, da=0.03, capex=0.05, nwc=0.10):
    return {"prob": 1.0, "revenue_growth": [g] * 5, "ebit_margin": [m] * 5,
            "da_pct_rev": da, "capex_pct_rev": capex, "nwc_pct_drev": nwc}


class TestFcffPath:
    def test_hand_computed_first_year(self):
        # rev0=100, g=10% -> rev1=110; ebit=22; nopat(税15%)=18.7
        # da=3.3; capex=5.5; dnwc=(110-100)*0.10=1.0 -> fcff=15.5
        rows = engine.fcff_path(100.0, _scenario(), 5, 0.15)
        r1 = rows[0]
        assert r1["revenue"] == pytest.approx(110.0)
        assert r1["ebit"] == pytest.approx(22.0)
        assert r1["fcff"] == pytest.approx(18.7 + 3.3 - 5.5 - 1.0)

    def test_growth_path_fades_with_short_lists(self):
        s = _scenario()
        s["revenue_growth"] = [0.20, 0.10]   # 之后沿用最后值
        rows = engine.fcff_path(100.0, s, 4, 0.15)
        assert rows[0]["revenue"] == pytest.approx(120.0)
        assert rows[1]["revenue"] == pytest.approx(132.0)
        assert rows[2]["revenue"] == pytest.approx(145.2)


class TestDcfValue:
    def test_hand_computed(self):
        # fcff=[10,10], wacc=10%, tg=2%:
        # pv = 10/1.1 + 10/1.21 = 17.3554
        # tv = 10*1.02/0.08 = 127.5; pv_tv = 127.5/1.21 = 105.372
        ev = engine.dcf_value([10.0, 10.0], 0.10, 0.02)
        assert ev == pytest.approx(17.3554 + 105.372, abs=1e-2)

    def test_invalid_when_wacc_le_terminal_g(self):
        assert engine.dcf_value([10.0], 0.02, 0.025) is None


class TestRunModel:
    def _history(self):
        return {"id": "A:600900", "market": "A", "code": "600900",
                "currency": "CNY", "history_hash": "abc123",
                "years": [{"fy": 2024, "revenue": 100.0, "ebit": 20.0,
                           "net_income": 15.0, "da": 3.0, "capex": 5.0,
                           "ocf": 18.0, "cash": 20.0, "debt": 10.0,
                           "shares": 10.0}]}

    def _assumptions(self):
        return {"id": "A:600900", "market": "A", "code": "600900",
                "horizon_years": 5, "wacc": 0.10, "terminal_g": 0.025,
                "tax_rate": 0.15, "net_debt": -10.0, "shares": 10.0,
                "currency": "CNY",
                "scenarios": {
                    "bear": {** _scenario(0.05, 0.15), "prob": 0.25},
                    "base": {** _scenario(0.10, 0.20), "prob": 0.50},
                    "bull": {** _scenario(0.15, 0.25), "prob": 0.25}}}

    def test_scenario_weighting_and_bridge(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=20.0)
        s = r["scenarios"]
        for k in ("bear", "base", "bull"):
            assert s[k]["per_share"] is not None
        # bull 增速/利润率更高 → 价值单调
        assert s["bull"]["per_share"] > s["base"]["per_share"] > \
            s["bear"]["per_share"]
        w = r["weighted_per_share"]
        expect = sum(s[k]["per_share"] * s[k]["prob"] for k in s)
        assert w == pytest.approx(expect)
        # upside 与加权价一致
        assert r["upside_pct"] == pytest.approx((w - 20.0) / 20.0 * 100.0)
        assert r["history_hash"] == "abc123"
        # equity bridge: net_debt=-10（净现金）→ equity = EV + 10
        base_rows = engine.fcff_path(100.0, _scenario(0.10, 0.20), 5, 0.15)
        ev = engine.dcf_value([x["fcff"] for x in base_rows], 0.10, 0.025)
        assert s["base"]["per_share"] == pytest.approx((ev + 10.0) / 10.0)

    def test_missing_shares_declares_gap(self):
        a = self._assumptions()
        a["shares"] = None
        r = engine.run_model(self._history(), a, price=20.0)
        assert r["weighted_per_share"] is None
        assert any("shares" in g for g in r["gaps"])

    def test_missing_price_gives_no_upside(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=None)
        assert r["weighted_per_share"] is not None
        assert r["upside_pct"] is None

    def test_sensitivity_monotonic_in_wacc(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=20.0)
        vals = r["sensitivity"]["values"]   # rows=wacc, cols=terminal_g
        for row in vals:
            assert all(v is not None for v in row)
        col0 = [row[0] for row in vals]
        assert col0 == sorted(col0, reverse=True)   # wacc 升 → 价值降
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_engine.py -q`
Expected: FAIL（`ModuleNotFoundError: value_genie.model.engine`）

- [ ] **Step 3: 实现** `value_genie/model/engine.py`

```python
"""Driver-based FCFF DCF engine — pure functions, no IO.

FCFF_t = EBIT_t x (1 - tax) + D&A_t - capex_t - dNWC_t, driven by explicit
revenue-growth and ebit-margin paths. Three scenarios x probabilities ->
probability-weighted per-share value (user mandate 2026-09-28: scenarios
replace point estimates). Reverse-DCF implied growth stays the cross-check
display line, never a ranking input here.
"""

from .. import config


def fcff_path(last_revenue: float, scenario: dict, years: int,
              tax_rate: float) -> list:
    """Forecast rows [{year, revenue, ebit, fcff}] for one scenario."""
    g, m = scenario["revenue_growth"], scenario["ebit_margin"]
    da_pct = scenario.get("da_pct_rev") or 0.0
    capex_pct = scenario.get("capex_pct_rev") or 0.0
    nwc_pct = scenario.get("nwc_pct_drev") or 0.0
    rows, prev = [], last_revenue
    for t in range(years):
        gt = g[t] if t < len(g) else g[-1]
        mt = m[t] if t < len(m) else m[-1]
        rev = prev * (1.0 + gt)
        ebit = rev * mt
        fcff = (ebit * (1.0 - tax_rate) + rev * da_pct
                - rev * capex_pct - (rev - prev) * nwc_pct)
        rows.append({"year": t + 1, "revenue": rev, "ebit": ebit,
                     "fcff": fcff})
        prev = rev
    return rows


def dcf_value(fcffs: list, wacc: float, terminal_g: float) -> float | None:
    """EV = PV(explicit FCFFs) + PV(Gordon terminal). None when the
    discount rate cannot support the terminal growth."""
    if not fcffs or wacc <= terminal_g:
        return None
    n = len(fcffs)
    pv = sum(f / (1.0 + wacc) ** (t + 1) for t, f in enumerate(fcffs))
    tv = fcffs[-1] * (1.0 + terminal_g) / (wacc - terminal_g)
    return pv + tv / (1.0 + wacc) ** n


def _per_share(ev: float | None, net_debt, shares) -> float | None:
    if ev is None or shares in (None, 0):
        return None
    nd = net_debt if net_debt is not None else 0.0
    return (ev - nd) / shares


def run_model(history: dict, assumptions: dict,
              price: float | None) -> dict:
    """Full model: scenarios + weighted value + sensitivity + gaps."""
    gaps = list(history.get("gaps") or []) + list(
        assumptions.get("gaps") or [])
    last_rev = history["years"][-1].get("revenue")
    years = int(assumptions.get("horizon_years")
                or config.MODEL_HISTORY_YEARS)
    wacc = float(assumptions.get("wacc") or config.DCF_DISCOUNT)
    tg = float(assumptions.get("terminal_g") or config.DCF_TERMINAL_G)
    tax = float(assumptions.get("tax_rate") or 0.15)
    net_debt = assumptions.get("net_debt")
    shares = assumptions.get("shares")
    if last_rev in (None, 0):
        raise ValueError("history has no revenue — cannot forecast")
    if shares in (None, 0):
        gaps.append("shares missing -> per-share value unavailable")

    scenarios, weighted, psum = {}, 0.0, 0.0
    for name, sc in (assumptions.get("scenarios") or {}).items():
        rows = fcff_path(last_rev, sc, years, tax)
        ev = dcf_value([r["fcff"] for r in rows], wacc, tg)
        ps = _per_share(ev, net_debt, shares)
        prob = float(sc.get("prob") or 0.0)
        scenarios[name] = {"prob": prob, "ev": ev, "per_share": ps,
                           "forecast": rows}
        if ps is not None:
            weighted += ps * prob
            psum += prob
    weighted_ps = weighted / psum if psum > 0 and shares else None
    if psum <= 0:
        gaps.append("scenario probabilities sum to zero")
    upside = ((weighted_ps - price) / price * 100.0
              if weighted_ps is not None and price else None)
    if price is None:
        gaps.append("no current price -> upside unavailable")

    base = (assumptions.get("scenarios") or {}).get("base")
    sens_vals = []
    for w in config.MODEL_SENSITIVITY_WACC:
        row = []
        for g in config.MODEL_SENSITIVITY_TG:
            if base is None:
                row.append(None)
                continue
            rows = fcff_path(last_rev, base, years, tax)
            row.append(_per_share(
                dcf_value([r["fcff"] for r in rows], w, g),
                net_debt, shares))
        sens_vals.append(row)

    return {
        "id": history["id"], "market": history["market"],
        "code": history["code"], "history_hash": history["history_hash"],
        "currency": assumptions.get("currency") or history.get("currency"),
        "price": price, "wacc": wacc, "terminal_g": tg, "tax_rate": tax,
        "scenarios": scenarios, "weighted_per_share": weighted_ps,
        "upside_pct": upside,
        "sensitivity": {"wacc": list(config.MODEL_SENSITIVITY_WACC),
                        "terminal_g": list(config.MODEL_SENSITIVITY_TG),
                        "values": sens_vals},
        "gaps": sorted(set(gaps)),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_engine.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add value_genie/model/engine.py tests/test_model_engine.py
git commit -m "feat(model): driver-based FCFF DCF engine (pure functions)"
```

---

### Task 4: model/comps.py — 可比公司估值表

**Files:**
- Create: `value_genie/model/comps.py`
- Test: `tests/test_model_comps.py`

- [ ] **Step 1: 写失败测试** `tests/test_model_comps.py`

```python
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
        # 目标市值 5e10 → 最近的三家是 8e10/7e10/6e10
        assert set(peers["code"]) == {"600008", "600007", "600006"}

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
        assert len(table) == 8
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
        # 中位数跳过缺失
        assert table["medians"]["pe_ttm"] == pytest.approx(14.5)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_comps.py -q`
Expected: FAIL（`ModuleNotFoundError: value_genie.model.comps`）

- [ ] **Step 3: 实现** `value_genie/model/comps.py`

```python
"""Trading comps: same-industry peers from the snapshot master frame,
median multiples -> implied value range for the target.

Discipline (DCF-first, user mandate 2026-09-28): comps are a cross-check
reference, never a buy argument. EV/EBITDA is best-effort — inputs missing
means the multiple is declared absent, never fabricated.
"""

import numpy as np
import pandas as pd

MULTIPLES = ("pe_ttm", "pb", "ps")


def select_peers(master: pd.DataFrame, market: str, code: str,
                 industry: str | None, limit: int = 10) -> pd.DataFrame:
    """Same-market, same-industry (when given), self excluded, closest by
    market cap, capped at `limit`."""
    df = master[master["market"].astype(str) == market]
    df = df[df["code"].astype(str) != str(code)]
    if industry and "industry" in df.columns:
        same = df[df["industry"].astype(str) == str(industry)]
        df = same if not same.empty else df
    tgt_cap = pd.to_numeric(
        master.loc[(master["market"].astype(str) == market)
                   & (master["code"].astype(str) == str(code),
                      )]["market_cap"], errors="coerce")
    cap = pd.to_numeric(df["market_cap"], errors="coerce")
    if len(tgt_cap) and tgt_cap.iloc[0] and tgt_cap.iloc[0] > 0:
        prox = (np.log(cap / float(tgt_cap.iloc[0]))).abs()
    else:
        prox = pd.Series(0.0, index=df.index)
    return df.assign(_prox=prox).sort_values("_prox").head(limit) \
             .drop(columns=["_prox"]).reset_index(drop=True)


def comps_table(peers: pd.DataFrame) -> dict:
    """Peer multiple rows + medians (NaN skipped)."""
    rows = []
    for _, p in peers.iterrows():
        rows.append({
            "code": str(p.get("code")), "name": p.get("name"),
            "market_cap": _num(p.get("market_cap")),
            **{m: _num(p.get(m)) for m in MULTIPLES}})
    medians = {}
    for m in MULTIPLES:
        vals = [r[m] for r in rows if r[m] is not None]
        medians[m] = float(np.median(vals)) if vals else None
    return {"rows": rows, "medians": medians}


def implied_range(target: pd.Series, medians: dict) -> dict:
    """Median peer multiple x target per-share base -> implied price.
    low/mid/high = min/median/max of available implied values."""
    price = _num(target.get("price"))
    out, vals = {}, []
    for m, label in (("pe_ttm", "by_pe"), ("pb", "by_pb"),
                     ("ps", "by_ps")):
        tgt_m = _num(target.get(m))
        med = medians.get(m)
        v = (med * price / tgt_m
             if med and price and tgt_m and tgt_m > 0 else None)
        out[label] = v
        if v is not None:
            vals.append(v)
    out["low"] = min(vals) if vals else None
    out["mid"] = float(np.median(vals)) if vals else None
    out["high"] = max(vals) if vals else None
    return out


def _num(v):
    try:
        f = float(v)
        return f if f == f and np.isfinite(f) else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_comps.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add value_genie/model/comps.py tests/test_model_comps.py
git commit -m "feat(model): trading comps — peer selection + implied range"
```

---

### Task 5: model/history.py — US（SEC companyconcept）

**Files:**
- Create: `value_genie/model/history.py`
- Test: `tests/test_model_history.py`

US 先行（数据源已验证存在）。`fetch_history_us(code)`：ticker→CIK 复用 `fetch/fundamentals.py` 的 `load_sec_cik_map()`；逐 concept 拉 companyconcept，过滤 `units.USD` 中 form∈{10-K,20-F}、fp=="FY"、duration 概念起止 ≥300 天，按 fy 去重（filed 最新者胜），取最近 `config.MODEL_HISTORY_YEARS` 年。

- [ ] **Step 1: 写失败测试** `tests/test_model_history.py`

```python
"""Tests for value_genie.model.history parsers (network monkeypatched)."""

import pytest

from value_genie.model import history as mh


def _concept_payload(fy_vals, unit="USD"):
    """fy_vals: [(fy, val)] — builds a companyconcept-shaped dict."""
    return {"entityName": "Test Co", "units": {unit: [
        {"fy": fy, "fp": "FY", "form": "10-K", "filed": f"{fy+1}-02-01",
         "start": f"{fy}-01-01", "end": f"{fy}-12-31", "val": val}
        for fy, val in fy_vals]}}


class TestUS:
    def test_parse_multi_year(self, monkeypatch):
        payloads = {
            "Revenues": _concept_payload([(2022, 90e9), (2023, 100e9),
                                          (2024, 110e9)]),
            "OperatingIncomeLoss": _concept_payload(
                [(2022, 18e9), (2023, 20e9), (2024, 22e9)]),
            "NetIncomeLoss": _concept_payload([(2024, 15e9)]),
            "NetCashProvidedByUsedInOperatingActivities":
                _concept_payload([(2024, 19e9)]),
            "PaymentsToAcquirePropertyPlantAndEquipment":
                _concept_payload([(2024, 5e9)]),
            "DepreciationDepletionAndAmortization":
                _concept_payload([(2024, 3e9)]),
            "CashAndCashEquivalentsAtCarryingValue":
                _concept_payload([(2024, 30e9)]),
            "LongTermDebt": _concept_payload([(2024, 10e9)]),
            "CommonStockSharesOutstanding":
                _concept_payload([(2024, 1e9)]),
        }
        monkeypatch.setattr(mh, "_us_concept",
                            lambda cik, concept: payloads.get(concept))
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert h is not None
        assert h["source"] == "sec_companyconcept"
        assert h["currency"] == "USD"
        assert [y["fy"] for y in h["years"]] == [2022, 2023, 2024]
        y24 = h["years"][-1]
        assert y24["revenue"] == 110e9
        assert y24["ebit"] == 22e9
        assert y24["capex"] == 5e9
        assert y24["debt"] == 10e9
        assert y24["shares"] == 1e9

    def test_quarterly_forms_excluded(self, monkeypatch):
        p = _concept_payload([(2024, 100e9)])
        p["units"]["USD"].append(
            {"fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-05-01",
             "start": "2024-01-01", "end": "2024-03-31", "val": 25e9})
        monkeypatch.setattr(mh, "_us_concept",
                            lambda cik, concept:
                            p if concept == "Revenues" else None)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert len(h["years"]) == 1
        assert h["years"][0]["revenue"] == 100e9

    def test_fail_closed_when_no_revenue(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_concept", lambda cik, concept: None)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        assert mh.fetch_history_us("TEST") is None

    def test_no_cik_returns_none(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_cik", lambda code: None)
        assert mh.fetch_history_us("TEST") is None


class TestParseHelpers:
    def test_num_and_report_date(self):
        assert mh._num("1234.5") == 1234.5
        assert mh._num("-") is None
        assert mh._num(None) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_history.py -q`
Expected: FAIL（`ModuleNotFoundError: value_genie.model.history`）

- [ ] **Step 3: 实现** `value_genie/model/history.py`（A/HK 为占位派发表，Task 6 填）

```python
"""Multi-year statement history, per stock, on demand (L3 modeling only).

- US: SEC companyconcept (multi-year XBRL), CIK via the existing ticker map
- A:  Eastmoney datacenter F10 statement reports (probe-finalized, Task 6)
- HK: Eastmoney HKF10 main indicators + probes (Task 6)

Network entry points are module-level (monkeypatch boundary); a source
failure returns None (fail-closed) and never clobbers an existing file.
"""

from datetime import date

from .. import config
from ..fetch.http import DC, SEC, num as _num
from . import store

# US XBRL concepts: primary with fallbacks (filers disagree on tags).
_US_CONCEPTS = {
    "revenue": ("Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "ebit": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "da": ("DepreciationDepletionAndAmortization",
           "DepreciationAmortizationAndAccretionNet"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "debt": ("LongTermDebt", "LongTermDebtNoncurrent"),
    "shares": ("CommonStockSharesOutstanding",
               "EntityCommonStockSharesOutstanding"),
}
_US_DURATION_MIN_DAYS = 300


def _us_cik(code: str) -> int | None:
    from ..fetch.fundamentals import load_sec_cik_map, normalize_us_ticker
    return load_sec_cik_map().get(normalize_us_ticker(code))


def _us_concept(cik: int, concept: str) -> dict | None:
    return SEC.get_json(
        config.SEC_CONCEPT_URL.format(cik=cik, concept=concept))


def _us_annual(payload: dict | None) -> dict:
    """companyconcept payload -> {fy: val}; annual FY rows only, latest
    filed wins on duplicates."""
    out = {}
    for e in ((payload or {}).get("units") or {}).get("USD", []):
        if e.get("form") not in ("10-K", "20-F") or e.get("fp") != "FY":
            continue
        start, end = e.get("start"), e.get("end")
        if start and end:
            try:
                d0 = date.fromisoformat(start)
                d1 = date.fromisoformat(end)
                if (d1 - d0).days < _US_DURATION_MIN_DAYS:
                    continue
            except ValueError:
                continue
        fy, val, filed = e.get("fy"), e.get("val"), e.get("filed", "")
        if fy is None or val is None:
            continue
        if fy not in out or filed > out[fy][0]:
            out[fy] = (filed, float(val))
    return {fy: v for fy, (_, v) in out.items()}


def fetch_history_us(code: str) -> dict | None:
    cik = _us_cik(code)
    if cik is None:
        return None
    series, name = {}, ""
    for field, concepts in _US_CONCEPTS.items():
        for concept in concepts:
            payload = _us_concept(cik, concept)
            if payload:
                name = name or payload.get("entityName") or ""
                s = _us_annual(payload)
                if s:
                    series[field] = s
                    break
    if "revenue" not in series:
        return None
    fys = sorted({fy for s in series.values() for fy in s})
    fys = fys[-config.MODEL_HISTORY_YEARS:]
    years = [{"fy": fy,
              **{f: series.get(f, {}).get(fy) for f in _US_CONCEPTS}}
             for fy in fys]
    gaps = [f"no us xbrl history for {f}"
            for f in _US_CONCEPTS if f not in series]
    return store.new_history("US", code, name=name,
                             source="sec_companyconcept",
                             currency="USD", years=years, gaps=gaps)


def fetch_history_a(code: str) -> dict | None:
    return _fetch_history_a_probe(code)   # Task 6


def fetch_history_hk(code: str) -> dict | None:
    return _fetch_history_hk_probe(code)  # Task 6


def _fetch_history_a_probe(code: str):
    raise NotImplementedError("A-share history lands in Task 6")


def _fetch_history_hk_probe(code: str):
    raise NotImplementedError("HK history lands in Task 6")


def fetch_history(market: str, code: str) -> dict | None:
    """Dispatch by market; None on source failure (fail-closed)."""
    fn = {"A": fetch_history_a, "HK": fetch_history_hk,
          "US": fetch_history_us}.get(market)
    return fn(code) if fn else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_history.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add value_genie/model/history.py tests/test_model_history.py
git commit -m "feat(model): US statement history via SEC companyconcept"
```

---

### Task 6: history.py — A 股与港股（探针先行）

**Files:**
- Create: `data/probe_model_history.py`（探针脚本，data/ 可清）
- Modify: `value_genie/model/history.py`（填 `_fetch_history_a_probe` / `_fetch_history_hk_probe`）
- Test: `tests/test_model_history.py`（追加 A/HK 解析测试）

**探针铁律**：日期值单引号，字符串/布尔值双引号；`success=false + code 9201` = 合法空窗口。

- [ ] **Step 1: 写探针脚本** `data/probe_model_history.py`

```python
"""Probe A/HK F10 history sources for model/history.py (delete-friendly).

探针铁律: 日期单引号, 字符串双引号; success=false + code 9201 = 合法空窗口.
Run: python -B data/probe_model_history.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from value_genie import config
from value_genie.fetch.http import DC


def probe(name, url, params):
    d = DC.get_json(url, params=params)
    ok = bool((d or {}).get("success"))
    code = ((d or {}).get("result") or {})
    rows = code.get("data") or []
    print(f"== {name}: success={ok} rows={len(rows)}")
    if rows:
        print(json.dumps(list(rows[0].keys()), ensure_ascii=False))
        print(json.dumps({k: rows[0][k] for k in list(rows[0])[:12]},
                         ensure_ascii=False, default=str))
    elif d:
        print(f"   code={d.get('code')} message={d.get('message')}")
    return rows


# A: 复用管线已验证 reportNames, per-stock filter, 近5个年报期
for rd in ("2024-12-31", "2023-12-31"):
    probe(f"A income RPT_LICO_FN_CPD {rd}", config.DC_WEB_URL, {
        "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
        "filter": f'(REPORTDATE=\'{rd}\')(SECUCODE="600900.SH")',
        "pageNumber": 1, "pageSize": 5, "source": "WEB", "client": "WEB"})
probe("A balance RPT_DMSK_FN_BALANCE 2024", config.DC_WEB_URL, {
    "reportName": "RPT_DMSK_FN_BALANCE", "columns": "ALL",
    "filter": '(REPORTDATE=\'2024-12-31\')(SECUCODE="600900.SH")',
    "pageNumber": 1, "pageSize": 5, "source": "WEB", "client": "WEB"})
probe("A cashflow RPT_DMSK_FN_CASHFLOW 2024", config.DC_WEB_URL, {
    "reportName": "RPT_DMSK_FN_CASHFLOW", "columns": "ALL",
    "filter": '(REPORTDATE=\'2024-12-31\')(SECUCODE="600900.SH")',
    "pageNumber": 1, "pageSize": 5, "source": "WEB", "client": "WEB"})

# HK: 已有 RPT_HKF10_FN_MAININDICATOR (per stock, latest 12 periods)
probe("HK main RPT_HKF10_FN_MAININDICATOR 00998", config.DC_SEC_URL, {
    "reportName": "RPT_HKF10_FN_MAININDICATOR", "columns": "ALL",
    "filter": '(SECUCODE="00998.HK")',
    "pageNumber": 1, "pageSize": 20, "source": "F10", "client": "PC"})
```

- [ ] **Step 2: 跑探针，定稿字段映射**

Run: `python -B data/probe_model_history.py`
Expected: 三个 A 表各返回字段清单（找：营收/营业利润/净利润、货币资金/有息负债或总负债、经营现金流/购建固定资产）；HK 表返回 12 期主指标字段。把字段名填入 Step 3 的映射常量；某表为空则在 history gaps 声明并继续。

- [ ] **Step 3: 追加 A/HK 解析测试**（追加到 tests/test_model_history.py）

```python
class TestA:
    def test_parse_from_rows(self, monkeypatch):
        # 字段名以探针定稿为准; 此处用映射常量的键构造 fixture
        income = [{"REPORTDATE": "2024-12-31",
                   mh.A_INCOME_FIELDS["revenue"]: 8.0e10,
                   mh.A_INCOME_FIELDS["ebit"]: 3.0e10,
                   mh.A_INCOME_FIELDS["net_income"]: 2.6e10}]
        cashflow = [{"REPORTDATE": "2024-12-31",
                     mh.A_CASHFLOW_FIELDS["ocf"]: 4.0e10,
                     mh.A_CASHFLOW_FIELDS["capex"]: 6.0e9}]
        balance = [{"REPORTDATE": "2024-12-31",
                    mh.A_BALANCE_FIELDS["cash"]: 5.0e10,
                    mh.A_BALANCE_FIELDS["debt"]: 1.0e10}]
        monkeypatch.setattr(mh, "_a_report",
                            lambda report, secucode, rd:
                            {"RPT_LICO_FN_CPD": income,
                             "RPT_DMSK_FN_CASHFLOW": cashflow,
                             "RPT_DMSK_FN_BALANCE": balance}.get(report))
        h = mh.fetch_history_a("600900")
        assert h is not None and h["currency"] == "CNY"
        y = h["years"][-1]
        assert y["revenue"] == 8.0e10
        assert y["ocf"] == 4.0e10
        assert y["debt"] == 1.0e10

    def test_empty_report_is_legal(self, monkeypatch):
        monkeypatch.setattr(mh, "_a_report",
                            lambda report, secucode, rd: None)
        assert mh.fetch_history_a("600900") is None


class TestHK:
    def test_parse_mainindicator(self, monkeypatch):
        rows = [{"REPORT_DATE": "2024-12-31",
                 mh.HK_MAIN_FIELDS["revenue"]: 2.0e11,
                 mh.HK_MAIN_FIELDS["net_income"]: 7.0e10}]
        monkeypatch.setattr(mh, "_hk_main", lambda secucode: rows)
        h = mh.fetch_history_hk("00998")
        assert h is not None and h["currency"] == "HKD"
        assert h["years"][-1]["revenue"] == 2.0e11
        assert any("ebit" in g or "capex" in g for g in h["gaps"])
```

- [ ] **Step 4: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_history.py -q`
Expected: FAIL（`AttributeError: ... A_INCOME_FIELDS`）

- [ ] **Step 5: 实现 A/HK fetch**（替换 history.py 中两个 NotImplementedError 桩）

```python
# --- A-share: per-stock annual rows from the pipeline-proven reports ----
# 字段名以 data/probe_model_history.py 探针定稿为准填写:
A_INCOME_REPORT = "RPT_LICO_FN_CPD"
A_INCOME_FIELDS = {"revenue": "TOTAL_OPERATE_INCOME",
                   "ebit": "OPERATE_PROFIT",
                   "net_income": "PARENT_NETPROFIT"}
A_CASHFLOW_FIELDS = {"ocf": "NETCASH_OPERATE",
                     "capex": "CONSTRUCT_LONG_ASSET"}
A_BALANCE_FIELDS = {"cash": "MONETARYFUNDS", "debt": "TOTAL_LIABILITIES"}


def _a_report(report: str, secucode: str, rd: str) -> list | None:
    d = DC.get_json(config.DC_WEB_URL, params={
        "reportName": report, "columns": "ALL",
        "filter": f'(REPORTDATE=\'{rd}\')(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 5, "source": "WEB", "client": "WEB"})
    return ((d or {}).get("result") or {}).get("data") or None


def _fetch_history_a_probe(code: str) -> dict | None:
    from ..fetch.profiles import _a_secucode
    secucode = _a_secucode(code)
    this_year = date.today().year
    # 最近 5 个可能的年报期（今年年报可能尚未披露, 9201 空窗口合法跳过）
    rds = [f"{y}-12-31" for y in range(this_year - 1,
                                       this_year - 1 - config.MODEL_HISTORY_YEARS - 1, -1)]
    by_fy: dict = {}
    name = ""
    for rd in rds:
        fy = int(rd[:4])
        inc = _a_report(A_INCOME_REPORT, secucode, rd)
        if not inc:
            continue
        row = inc[0]
        name = name or row.get("SECURITY_NAME_ABBR") or ""
        y = by_fy.setdefault(fy, {"fy": fy})
        for f, col in A_INCOME_FIELDS.items():
            y[f] = _num(row.get(col))
        cf = _a_report("RPT_DMSK_FN_CASHFLOW", secucode, rd)
        if cf:
            for f, col in A_CASHFLOW_FIELDS.items():
                y[f] = _num(cf[0].get(col))
        bs = _a_report("RPT_DMSK_FN_BALANCE", secucode, rd)
        if bs:
            for f, col in A_BALANCE_FIELDS.items():
                y[f] = _num(bs[0].get(col))
        # 股本: 业绩报表无; 用市值/价近似不可信——声明缺口, 由 assumptions 手填
    if not by_fy:
        return None
    years = [by_fy[fy] for fy in sorted(by_fy)][-config.MODEL_HISTORY_YEARS:]
    gaps = ["a-share statements carry no shares/da fields — set "
            "assumptions.shares manually (F10 股本) before trusting "
            "per-share output"]
    return store.new_history("A", code, name=name,
                             source="eastmoney_datacenter_f10",
                             currency="CNY", years=years, gaps=gaps)


# --- HK: HKF10 main indicators (12 periods) ------------------------------
# 字段名以探针定稿为准:
HK_MAIN_FIELDS = {"revenue": "TOTAL_OPERATE_INCOME",
                  "net_income": "PARENT_NETPROFIT"}


def _hk_main(secucode: str) -> list | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_REPORT_NAME, "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 30, "source": "F10", "client": "PC"})
    return ((d or {}).get("result") or {}).get("data") or None


def _fetch_history_hk_probe(code: str) -> dict | None:
    secucode = code if "." in code else f"{code}.HK"
    rows = _hk_main(secucode)
    if not rows:
        return None
    annual = {}
    for r in rows:
        rd = str(r.get("REPORT_DATE") or "")[:10]
        if not rd.endswith("12-31"):
            continue
        fy = int(rd[:4])
        y = annual.setdefault(fy, {"fy": fy})
        for f, col in HK_MAIN_FIELDS.items():
            y[f] = _num(r.get(col))
    if not annual:
        return None
    years = [annual[fy] for fy in sorted(annual)][-config.MODEL_HISTORY_YEARS:]
    gaps = ["hk main indicators lack ebit/da/capex/cash/debt/shares — "
            "fallback ratios used; set assumptions manually for rigor"]
    name = rows[0].get("SECURITY_NAME_ABBR") or ""
    return store.new_history("HK", code, name=name,
                             source="eastmoney_hkf10_mainindicator",
                             currency="HKD", years=years, gaps=gaps)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_history.py -q`
Expected: 9 passed

- [ ] **Step 7: 真机验证一次**（网络允许时）

Run: `python -B -c "from value_genie.model import history as mh; h=mh.fetch_history('A','600900'); print(h['years'][-1] if h else None)"`
Expected: 打印长江电力最近年报年的科目 dict（或 None + stderr warn，则回 Step 2 校字段）

- [ ] **Step 8: Commit**

```bash
git add value_genie/model/history.py tests/test_model_history.py
git commit -m "feat(model): A/HK statement history via eastmoney F10 (probe-finalized)"
```

---

### Task 7: CLI `model` 子命令

**Files:**
- Modify: `value_genie/__main__.py`（cmd_model 加在 cmd_profile 后；parser 块加在 ppf 块后 L2120 前）
- Test: `tests/test_model_cli.py`

- [ ] **Step 1: 写失败测试** `tests/test_model_cli.py`

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_cli.py -q`
Expected: FAIL（argparse error: invalid choice 'model'）

- [ ] **Step 3: 实现 cmd_model + parser**（`value_genie/__main__.py`）

cmd_model 加在 cmd_profile 函数之后：

```python
def _model_master(args):
    """Latest snapshot master frame for comps; None when unavailable."""
    from . import report
    try:
        snap = report.resolve_snapshot(getattr(args, "data_dir", None))
    except FileNotFoundError:
        return None
    from .report import load_master
    try:
        return load_master(snap)
    except Exception:
        return None


def _model_price(m, args) -> float | None:
    """Live quote first, snapshot price fallback (same contract as ask)."""
    from . import analyze as az
    try:
        q = az.live_quote(m)
        if q and q.get("price"):
            return float(q["price"])
    except Exception:
        pass
    master = _model_master(args)
    if master is not None:
        row = master[(master["market"].astype(str) == m.market)
                     & (master["code"].astype(str) == str(m.code))]
        if len(row):
            from .fetch.http import num
            return num(row.iloc[0].get("price"))
    return None


def cmd_model(args) -> int:
    """Financial models (2026-10-02 design): driver-based FCFF DCF +
    comps, AI-triggered at L3. models/ is LOCAL-ONLY (never pushed).
    `build` is price-sensitive -> freshness-gated like ask; fetch/show/
    set/list are not gated (historical statements / local registry)."""
    import sys as _sys

    from .model import store as mst

    if args.model_cmd == "list":
        rows = mst.list_models()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if not rows:
            print(f"no models under {mst.models_dir()}")
            return 1
        for r in rows:
            stale = " STALE(history changed)" if r["stale"] else ""
            print(f"{r['id']:<14} weighted={r['weighted_per_share']} "
                  f"upside={r['upside_pct']}% "
                  f"{str(r.get('built_at'))[:10]}{stale}")
        return 0

    m = _resolve_stock_or_exit(args.stock)

    if args.model_cmd == "fetch":
        from .model import history as mh
        if mst.load_history(m.market, m.code) and not args.force:
            print(f"history exists for {m.label()} (--force to refetch)")
            return 0
        h = mh.fetch_history(m.market, m.code)
        if h is None:
            print(f"history fetch failed for {m.label()} "
                  f"(source returned nothing; fail-closed)",
                  file=_sys.stderr)
            return 1
        p = mst.save_history(h)
        if args.json:
            print(json.dumps(h, ensure_ascii=False, indent=2,
                             default=str))
        else:
            print(f"wrote {p}")
            print(f"{h['id']} {h.get('name')}: "
                  f"{len(h['years'])} years "
                  f"({h['years'][0]['fy']}..{h['years'][-1]['fy']}) "
                  f"{h['currency']}")
            for g in h.get("gaps") or []:
                print(f"  gap: {g}")
        return 0

    if args.model_cmd == "set":
        updates = {}
        for pair in args.sets:
            if "=" not in pair:
                raise SystemExit(f"bad set pair {pair!r}; want key=value")
            k, v = pair.split("=", 1)
            v = v.strip()
            updates[k.strip()] = (
                [float(x) for x in v.split(",")] if "," in v
                else float(v))
        try:
            a = mst.set_assumptions(m.market, m.code, updates,
                                    reason=args.reason or "")
        except ValueError as exc:
            print(str(exc), file=_sys.stderr)
            return 1
        if args.json:
            print(json.dumps(a, ensure_ascii=False, indent=2,
                             default=str))
        else:
            print(f"assumptions updated for {m.label()}: "
                  f"{', '.join(updates)}")
        return 0

    if args.model_cmd == "show":
        r = mst.load_result(m.market, m.code)
        if r is None:
            print(f"no model for {m.label()} — build one with "
                  f"`model build {m.market}:{m.code}`")
            return 1
        h = mst.load_history(m.market, m.code)
        stale = mst.is_stale(r, h)
        if args.json:
            out = dict(r)
            out["stale"] = stale
            print(json.dumps(out, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        cur = r.get("currency") or ""
        print(f"{r['id']} model ({str(r.get('built_at'))[:10]}"
              + (" STALE — history changed, rebuild" if stale else "")
              + ")")
        print(f"price {r.get('price')} {cur} | weighted "
              f"{r.get('weighted_per_share')} {cur} | upside "
              f"{r.get('upside_pct')}%")
        for name, s in (r.get("scenarios") or {}).items():
            print(f"  {name:<5} p={s.get('prob')}: "
                  f"{s.get('per_share')} {cur}")
        for g in r.get("gaps") or []:
            print(f"  gap: {g}")
        return 0

    if args.model_cmd == "build":
        if not _check_freshness(args):
            return 1
        h = mst.load_history(m.market, m.code)
        if h is None:
            print(f"no history for {m.label()} — run "
                  f"`model fetch {m.market}:{m.code}` first",
                  file=_sys.stderr)
            return 1
        a = mst.load_assumptions(m.market, m.code)
        if a is None:
            a = mst.default_assumptions(m.market, m.code)
            mst.save_assumptions(a)
        from .model import engine, comps as mcomps
        price = _model_price(m, args)
        r = engine.run_model(h, a, price=price)
        master = _model_master(args)
        if master is not None:
            industry = None
            row = master[(master["market"].astype(str) == m.market)
                         & (master["code"].astype(str) == str(m.code))]
            if len(row):
                industry = row.iloc[0].get("industry")
                peers = mcomps.select_peers(master, m.market, m.code,
                                            industry)
                table = mcomps.comps_table(peers)
                r["comps"] = {**table,
                              "implied": mcomps.implied_range(
                                  row.iloc[0], table["medians"])}
        else:
            r["comps"] = None
        mst.save_result(r)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        cur = r.get("currency") or ""
        print(f"{r['id']} 模型 ({str(r.get('built_at'))[:10]}, "
              f"data-as-of history {h['years'][-1]['fy']})")
        print(f"加权内在价值 {r.get('weighted_per_share')} {cur} vs "
              f"现价 {price} {cur} -> upside {r.get('upside_pct')}%")
        for name, s in (r.get("scenarios") or {}).items():
            print(f"  {name:<5} p={s.get('prob')}: "
                  f"{s.get('per_share')} {cur}")
        if r.get("comps") and r["comps"].get("implied"):
            imp = r["comps"]["implied"]
            print(f"comps 隐含区间 [{imp.get('low')}, "
                  f"{imp.get('high')}] {cur} (中位 {imp.get('mid')})")
        for g in r.get("gaps") or []:
            print(f"  gap: {g}")
        return 0

    raise SystemExit(f"unknown model subcommand {args.model_cmd}")
```

parser 块（加在 `ppf.set_defaults(func=cmd_profile)` 之后、`return parser` 之前）：

```python
    pmo = sub.add_parser(
        "model", help="financial models: driver-based FCFF DCF + comps "
                      "(models/, LOCAL-ONLY — never pushed; AI-triggered "
                      "at L3 per skills/19)")
    pmo_sub = pmo.add_subparsers(dest="model_cmd", required=True)
    pmo_fetch = pmo_sub.add_parser(
        "fetch", help="fetch multi-year statement history (on-demand)")
    pmo_fetch.add_argument("stock")
    pmo_fetch.add_argument("--force", action="store_true",
                           help="refetch even if history exists")
    pmo_fetch.add_argument("--json", action="store_true")
    pmo_build = pmo_sub.add_parser(
        "build", help="run the model: scenarios + sensitivity + comps "
                      "(freshness-gated, price-sensitive)")
    pmo_build.add_argument("stock")
    pmo_build.add_argument("--data-dir", default=None)
    pmo_build.add_argument("--no-check", action="store_true")
    pmo_build.add_argument("--json", action="store_true")
    pmo_show = pmo_sub.add_parser("show", help="show the last result")
    pmo_show.add_argument("stock")
    pmo_show.add_argument("--json", action="store_true")
    pmo_set = pmo_sub.add_parser(
        "set", help="adjust assumptions (dotted key=value, repeatable)")
    pmo_set.add_argument("stock")
    pmo_set.add_argument("sets", nargs="+", metavar="KEY=VALUE",
                         help="e.g. base.revenue_growth=0.2,0.18 wacc=0.11")
    pmo_set.add_argument("--reason", default=None,
                         help="mandatory: why this change (changelog)")
    pmo_set.add_argument("--json", action="store_true")
    pmo_list = pmo_sub.add_parser("list", help="coverage + staleness")
    pmo_list.add_argument("--json", action="store_true")
    pmo.set_defaults(func=cmd_model)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_cli.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add value_genie/__main__.py tests/test_model_cli.py
git commit -m "feat(model): CLI model fetch|build|show|set|list (--json, build freshness-gated)"
```

---

### Task 8: masters-vote 接线 + ask 集成（融合层）

**Files:**
- Modify: `value_genie/__main__.py`（D3 钩后 L213 附近）
- Modify: `value_genie/analyze.py`（cores 块 L426-446 + 渲染处）
- Test: `tests/test_model_overlay.py`

- [ ] **Step 1: 写失败测试** `tests/test_model_overlay.py`

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_model_overlay.py -q`
Expected: FAIL（`AttributeError: module 'value_genie.analyze' has no attribute 'model_summary'`）

- [ ] **Step 3: analyze.py 加 model_summary + cores 块集成**

在 `_core_val` 之后（L456 附近）新增：

```python
def model_summary(market: str, code: str) -> dict | None:
    """Built-model summary for the ask output; None when no model exists.
    Staleness is declared, never hidden (history hash pin, D3-parallel)."""
    from .model import store as mst
    r = mst.load_result(market, code)
    if r is None:
        return None
    h = mst.load_history(market, code)
    return {
        "weighted_per_share": r.get("weighted_per_share"),
        "upside_pct": r.get("upside_pct"),
        "price": r.get("price"), "currency": r.get("currency"),
        "scenarios": {k: {"prob": v.get("prob"),
                          "per_share": v.get("per_share")}
                      for k, v in (r.get("scenarios") or {}).items()},
        "comps_implied": ((r.get("comps") or {}).get("implied")
                          if r.get("comps") else None),
        "built_at": r.get("built_at"),
        "stale": mst.is_stale(r, h),
    }
```

cores 块（L435-446）内，`result["cores"] = {...}` 之前插入 overlay：

```python
    cr = cores.add_core_scores(
        pd.DataFrame([core_row]),
        culture=pd.Series([_culture]) if _culture is not None
        else None)
    # DCF hook (D3-parallel): a built, non-stale model replaces the
    # reverse-DCF anchor with the modeled probability-weighted upside.
    from .model import store as _mst
    cr, _n_modeled = _mst.apply_modeled_dcf(cr)
    cr = cr.iloc[0]
```

并在 `result["cores"] = {...}` 之后加：

```python
    result["model"] = model_summary(match.market, match.code)
```

渲染层：在 analyze.py 渲染函数中找 cores 打印处（搜 `"dcf_implied_g"` 或 `cores`），在其后加模型摘要行（stale 时标注 `STALE — rebuild with model build`）。样式：

```
model    : weighted 30.0 CNY vs price 24.0 -> upside +25.0% (built 2026-10-02)
           bear/base/bull: 22.5 / 30.0 / 37.5 CNY; comps implied [21.0, 33.0]
```

- [ ] **Step 4: __main__.py masters-vote 接线**

在 L213 `df, n_distilled = _prof.apply_distilled_culture(df)` 之后插入：

```python
    # DCF hook (D3-parallel, 2026-10-02): built models replace the
    # reverse-DCF anchor with modeled upside for those rows only
    from .model import store as _mstore
    df, n_modeled = _mstore.apply_modeled_dcf(df)
```

并在 L348 附近打印 distilled 计数处追加：

```python
    if n_modeled:
        print(f"  dcf core: {n_modeled} stock(s) modeled "
              f"(models/; DCF hook active)")
```

（先读 L340-350 确认确切上下文再插入。）

- [ ] **Step 5: 跑测试确认通过**

Run: `python -B -m pytest tests/test_model_overlay.py tests/test_analyze.py -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add value_genie/__main__.py value_genie/analyze.py tests/test_model_overlay.py
git commit -m "feat(model): fusion layer — masters-vote DCF hook + ask model summary"
```

---

### Task 9: skills/19 + AGENTS.md 路由

**Files:**
- Create: `skills/19-financial-modeling.md`
- Modify: `AGENTS.md`（路由表 + Company profiles 节后加 Financial models 节）

- [ ] **Step 1: 读既有 skill 定 frontmatter 格式**

Read: `skills/16-intel.md` 前 20 行（frontmatter 键名照抄，order=19）。

- [ ] **Step 2: 写 skills/19-financial-modeling.md**

frontmatter 照 Step 1 格式；正文：

```markdown
# 19 · Financial Modeling（财务建模）

Triggers: 建模 / 财务模型 / DCF / 估值模型 / comps / 可比公司 / model X

## 何时建模（AI 自律触发条件）

- **必建**: masters-vote / recommend 的 L3 深评短名单候选，进 L4 裁决前
- **必建**: holding-deep-review 中论点漂移或大幅波动的持仓；钥匙孔季度证伪检查
- **选建**: 用户问"评价 X"且无模型或模型 STALE
- **不建**: 漏斗宽池扫描；D4 战术/短炒模式（DCF 已降级为"失败变持有"注记）

## 工作流

1. `python -m value_genie model fetch X` 拉多年三表（history.json，缺科目看 gaps）
2. 读材料：`profile show X` + `intel X` + `models/<mkt>/<code>/raw/` 中的审计意见/尽调投喂
3. 首次 `model build X` 生成默认假设（历史中位数）；读材料后用
   `model set X base.revenue_growth=0.25,0.22,0.18,0.15,0.12 wacc=0.11 --reason "读年报审计意见后上调"`
   调整（--reason 必填，进 changelog）
4. `model build X` 重算 → 三情景×概率加权价值 + 敏感性 + comps 隐含区间
5. 论证纪律：DCF 第一（reverse-DCF 隐含预期为起点）；comps 只作参照互证，不作买入论证
6. STALE（新报告期）→ 重新 fetch + 复核假设 + build；模型结果经 DCF 钩进入 core_dcf（core_gaps 标 DCF_MODELED）

## 红线

- 缺科目（A股股本、HK capex/现金负债）绝不编造——gaps 声明，per-share 不可信时说不可信
- A 股模型必手填 assumptions.shares（F10 股本）后才可信 per-share 输出
- models/ 是本地-only 专有判断，永不推送
```

- [ ] **Step 3: AGENTS.md 更新**

路由表 `"读公司原文 / 蒸馏商业模式与文化"` 行后插入：

```markdown
| "建财务模型 / DCF估值 / 可比公司" | fused-quant-master | `python -m value_genie model fetch|build|show|set|list X`（L3 建模：多年三表 + 驱动因子FCFF三情景概率加权 + 敏感性 + comps；触发条件见 skills/19；DCF 钩平行 D3 进 core_dcf；models/ 本地-only 永不推送） |
```

`## Company profiles` 节后新增一节：

```markdown
## Financial models (财务模型, 本地-only)

Models are the L3 valuation store: multi-year statement history on one
side, the AI's adjustable driver assumptions + scenario DCF result on the
other. They close the DCF loop — the reverse-DCF anchor in `core_dcf` is
the default; a built, non-stale model's probability-weighted upside
replaces it (D3-parallel hook, `core_gaps` marks `DCF_MODELED`).

- **Storage**: `models/<market>/<code>/` — history.json /
  assumptions.json (changelog mandatory) / result.json / raw/ (audit
  opinions, DD material). **gitignored LOCAL-ONLY — never pushed**
  (user mandate 2026-10-02: the model is proprietary judgment).
- Commands: `python -m value_genie model fetch|build|show|set|list` —
  all `--json`-capable. Only `build` runs the freshness gate
  (price-sensitive: comps + upside); fetch/show/set/list do not.
- **Trigger conditions (AI-decided, skills/19)**: mandatory before L4
  verdicts on L3 shortlists, on holdings with thesis drift, and for
  keyhole quarterly falsification checks; never for funnel-wide scans
  or D4 tactical mode.
- **Staleness**: the result pins the history hash; a refetched history
  (new reporting period) marks it STALE and it drops out of scoring
  until rebuilt.
- Never fabricate missing statement fields (A shares count, HK capex) —
  declare gaps; say per-share is untrustworthy when it is.
```

- [ ] **Step 4: Commit**

```bash
git add skills/19-financial-modeling.md AGENTS.md
git commit -m "docs(model): skills/19 trigger conditions + AGENTS.md routing"
```

---

### Task 10: 全量回归 + 收尾

- [ ] **Step 1: 全量测试**

Run: `python -B -m pytest tests -q`
Expected: 全部通过（含既有 626+ 用例无回归）

- [ ] **Step 2: CLI 冒烟**（需有效快照）

Run: `python -B -m value_genie model list --json`
Expected: `[]`
Run: `python -B -m value_genie model fetch US:NVDA --json | python -c "import json,sys; d=json.load(sys.stdin); print(d['id'], len(d['years']))"`
Expected: `US:NVDA 5`（或源失败的明确报错，fail-closed）

- [ ] **Step 3: skill note 记录实施坑**

Run: `python -B -m value_genie skill note data-ops "model history 探针结论: <Task 6 定稿的字段映射一行总结>"`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(model): financial modeling capability — design 2026-10-02 complete"
```

---

## Self-Review 记录

- **Spec 覆盖**：spec §3.1→Task5/6；§3.2→Task3；§3.3→Task4；§3.4→Task2；§4.1/4.4→Task9；§4.2/4.3→Task8；§5→Task7；§6→Task1；§7→各 Task 测试 + Task10；§8→Task7/8/9。审计 PDF 自动解析按 spec 明确留后续。
- **类型一致性**：`new_history/save_history/load_history`、`default_assumptions/set_assumptions`、`run_model`、`select_peers/comps_table/implied_range`、`apply_modeled_dcf/load_dcf_scores`、`model_summary` 在测试与实现中签名一致；`_fetch_history_a_probe`/`_fetch_history_hk_probe` 为 Task5 桩、Task6 填实，命名一致。
- **已知留白（实施时按探针定稿，非占位符）**：`A_INCOME_FIELDS`/`A_CASHFLOW_FIELDS`/`A_BALANCE_FIELDS`/`HK_MAIN_FIELDS` 的具体字段名由 Task 6 Step 2 探针输出决定——这是探针铁律的要求，测试 fixture 引用常量而非硬编码字段名，字段名变化不改测试。
- **EV/EBITDA**：依赖 history 的 debt/cash + ebitda 拼装，首版 comps 只用 PE/PB/PS（spec §3.3 允许"缺项声明"）；EV/EBITDA 待 history 字段稳定后在 Task 6 真机验证时评估，可信则加 `ev_ebitda` 到 `comps_table`。
