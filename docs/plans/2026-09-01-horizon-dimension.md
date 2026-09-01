# Time-Horizon Dimension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a four-horizon holding-period dimension (ultrashort/short/mid/long) as an orthogonal registry + `--horizon` CLI parameter, with per-horizon scoring, a four-horizon profile in `ask`, and a qualitative skill playbook.

**Architecture:** Mirror the existing pluggable Strategy registry with a new Horizon registry (`value_genie/strategy/horizons.py`). Each horizon = pillar weights + momentum measurement window + optional gates. Horizon scoring recomputes the momentum pillar on the horizon's window, then reuses `apply_composite`. `ask` gains a four-horizon profile; `screen` gains `--horizon` (alone or combined with `--strategy`).

**Tech Stack:** Python 3.10+, pandas only. Tests: pytest (`python -B -m pytest tests -q`). On this host pandas is vendored — **every python command needs `$env:PYTHONPATH = "libs"` first** (PowerShell).

**Spec:** `docs/specs/2026-09-01-horizon-dimension-design.md`

**Key discovery baked into Task 4:** `ask` currently reports `momentum: 100.0` / `safety: 100.0` and kline-metric percentiles of exactly 50.0 — the peer frame is rebuilt from quotes CSVs which carry NO kline factor columns, so the target ranks against itself (verified live: `ask 贵州茅台 --json` on snapshot 20260901). Task 4 fixes this by backfilling peers from the snapshot's kline cache; without it the ultrashort/short profile would be fake percentiles.

**Commits:** one commit per task. Test command shorthand below: `pytest tests/test_horizons.py -q` means `$env:PYTHONPATH = "libs"; python -B -m pytest tests/test_horizons.py -q` run from the repo root.

---

### Task 1: Short-window kline factors

**Files:**
- Modify: `value_genie/strategy/factors.py` (function `kline_metrics`, after the `ret_60` block, lines ~65-77)
- Test: `tests/test_horizons.py` (new file)

- [ ] **Step 1: Write the failing test** — create `tests/test_horizons.py`:

```python
"""Tests for the time-horizon dimension (registry, scoring, CLI, ask)."""

import pandas as pd
import pytest

from value_genie.strategy.factors import kline_metrics


class TestShortWindowFactors:
    def test_ret_5d_ret_20d_vol_20d(self):
        closes = [100.0 * (1.01 ** t) for t in range(80)]
        m = kline_metrics(pd.DataFrame({"close": closes}))
        assert m["ret_5d"] == pytest.approx(((1.01 ** 5) - 1) * 100,
                                            rel=1e-9)
        assert m["ret_20d"] == pytest.approx(((1.01 ** 20) - 1) * 100,
                                             rel=1e-9)
        assert m["vol_20d"] > 0
        assert m["volatility"] > 0

    def test_flat_series_gives_zero_returns(self):
        m = kline_metrics(pd.DataFrame({"close": [100.0] * 80}))
        assert m["ret_5d"] == 0.0
        assert m["ret_20d"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL with `KeyError: 'ret_5d'`

- [ ] **Step 3: Implement** — in `value_genie/strategy/factors.py`, inside `kline_metrics`, replace:

```python
    ret_250 = _interval_return(close, 250)
    ret_60 = _interval_return(close, 60)
    if ret_250 is not None:
        out["ret_250d"] = ret_250
    if ret_60 is not None:
        out["ret_60d"] = ret_60

    if n >= MIN_BARS + 1:
        daily = close.pct_change().dropna()
        if len(daily) >= 20:
            out["volatility"] = float(daily.std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0
    return out
```

with:

```python
    ret_250 = _interval_return(close, 250)
    ret_60 = _interval_return(close, 60)
    ret_20 = _interval_return(close, 20)
    ret_5 = _interval_return(close, 5)
    if ret_250 is not None:
        out["ret_250d"] = ret_250
    if ret_60 is not None:
        out["ret_60d"] = ret_60
    if ret_20 is not None:
        out["ret_20d"] = ret_20
    if ret_5 is not None:
        out["ret_5d"] = ret_5

    if n >= MIN_BARS + 1:
        daily = close.pct_change().dropna()
        if len(daily) >= 20:
            out["volatility"] = float(daily.std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0
            out["vol_20d"] = float(daily.tail(20).std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_horizons.py tests/test_factors.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/strategy/factors.py tests/test_horizons.py
git commit -m "feat: add short-window kline factors ret_5d/ret_20d/vol_20d"
```

---

### Task 2: Horizon registry + master horizon annotations

**Files:**
- Modify: `value_genie/strategy/registry.py` (Strategy dataclass + new Horizon section)
- Modify: `value_genie/strategy/masters.py` (six one-line edits)
- Create: `value_genie/strategy/horizons.py` (registrations only; scoring comes in Task 3)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py`:

```python
from value_genie.strategy import horizons  # noqa: F401 — registration
from value_genie.strategy import masters   # noqa: F401
from value_genie.strategy.registry import (
    get_horizon,
    get_strategy,
    list_horizons,
)


class TestHorizonRegistry:
    def test_four_horizons_in_order(self):
        ids = [h.id for h in list_horizons()]
        assert ids[:4] == ["ultrashort", "short", "mid", "long"]

    def test_get_horizon_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown horizon"):
            get_horizon("nope")

    def test_ultrashort_shape(self):
        h = get_horizon("ultrashort")
        assert h.name == "超短线"
        assert h.momentum_cols == ("ret_5d", "ret_20d")
        assert h.weights["momentum"] == 0.70
        assert h.weights["value"] == 0
        ops = [(g[0], g[1]) for g in h.gates]
        assert ("volatility", "pctl>=") in ops
        assert ("ret_5d", ">=") in ops

    def test_short_shape(self):
        h = get_horizon("short")
        assert h.momentum_cols == ("ret_20d", "ret_60d")
        assert h.weights["momentum"] == 0.35
        assert ("ret_20d", ">=") in [(g[0], g[1]) for g in h.gates]

    def test_mid_shape(self):
        h = get_horizon("mid")
        assert h.gates == []
        assert h.weights["value"] == 0.30
        assert h.weights["growth"] == 0.30
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_long_shape(self):
        h = get_horizon("long")
        assert h.gates == []
        assert h.weights["quality"] == 0.35
        assert h.weights["cashflow"] == 0.20
        assert h.weights["momentum"] == 0
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_weights_sum_to_one(self):
        for h in list_horizons():
            assert sum(h.weights.values()) == pytest.approx(1.0)

    def test_masters_carry_natural_horizon(self):
        mapping = {"buffett": "long", "munger": "long", "graham": "mid",
                   "livermore": "short", "duan": "long",
                   "sheng": "ultrashort"}
        for mid, hz in mapping.items():
            assert get_strategy(mid).horizon == hz

    def test_presets_have_empty_horizon(self):
        assert get_strategy("balanced").horizon == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL on import (`ImportError: cannot import name 'get_horizon'`)

- [ ] **Step 3: Implement the registry** — in `value_genie/strategy/registry.py`:

3a. Extend the Strategy dataclass — after the `order: int = 99` line add:

```python
    horizon: str = ""                 # natural holding period (masters)
```

3b. After the `list_strategies` function (before the DataSource section), insert:

```python
# ---------------------------------------------------------------------------
# Horizon registry
# ---------------------------------------------------------------------------
@dataclass
class Horizon:
    """A holding-period lens over the six pillars.

    weights: pillar weights for standalone horizon screening.
    momentum_cols: return columns defining the horizon's momentum
    window (the default pillar momentum uses ret_60d/ret_250d).
    gates: hard filters applied before composite screening
    (ultrashort/short need the trend proven; mid/long rely on weights).
    """

    id: str
    name: str
    window: str                       # "1-10 交易日"
    weights: dict                     # {pillar: float}
    momentum_cols: tuple = ("ret_60d", "ret_250d")
    gates: list = field(default_factory=list)
    order: int = 99                   # ultrashort=1 ... long=4


_HORIZONS: dict[str, Horizon] = {}


def register_horizon(h: Horizon) -> Horizon:
    """Register a horizon; replaces if id exists."""
    _HORIZONS[h.id] = h
    return h


def get_horizon(horizon_id: str) -> Horizon:
    """Fetch a registered horizon; ValueError if unknown."""
    try:
        return _HORIZONS[horizon_id]
    except KeyError:
        known = ", ".join(sorted(_HORIZONS))
        raise ValueError(
            f"unknown horizon {horizon_id!r}; available: {known}") from None


def list_horizons() -> list[Horizon]:
    """All registered horizons, ultrashort -> long."""
    return sorted(_HORIZONS.values(), key=lambda h: h.order)
```

- [ ] **Step 4: Create `value_genie/strategy/horizons.py`** with the four registrations:

```python
"""Time-horizon dimension: holding-period lenses over the six pillars.

Four horizons (windows are trading time, weights are registry data —
tunable without code changes):

- ultrashort 超短线 (1-10 交易日): attention-driven, short-window
  momentum is the asset, growth numbers are narrative fuel (Sun-style)
- short     短线   (10日-3月): trend confirmation + repair starting
  (Livermore-style "the market proves the trend first")
- mid       中线   (3月-3年): valuation repair + earnings delivery
  (Graham-style statistical window)
- long      长线   (3年+): business model + owner earnings
  (Buffett/Duan-style "这门生意十年后会是什么样")

Each horizon also fixes the momentum measurement window; combined with
a strategy (`--strategy X --horizon Y`) the master's weights and gates
stay, only the momentum window swaps.
"""

from .registry import Horizon, register_horizon


def _register_horizons():
    """Register the four built-in horizons (ultrashort -> long)."""

    register_horizon(Horizon(
        id="ultrashort", name="超短线", window="1-10 交易日",
        weights={"value": 0, "growth": 0.25, "quality": 0.05,
                 "safety": 0, "momentum": 0.70, "cashflow": 0},
        momentum_cols=("ret_5d", "ret_20d"),
        gates=[("volatility", "pctl>=", 50), ("ret_5d", ">=", 0.0)],
        order=1,
    ))

    register_horizon(Horizon(
        id="short", name="短线", window="10日-3月",
        weights={"value": 0.20, "growth": 0.20, "quality": 0.10,
                 "safety": 0.15, "momentum": 0.35, "cashflow": 0},
        momentum_cols=("ret_20d", "ret_60d"),
        gates=[("ret_20d", ">=", 0.0)],
        order=2,
    ))

    register_horizon(Horizon(
        id="mid", name="中线", window="3月-3年",
        weights={"value": 0.30, "growth": 0.30, "quality": 0.20,
                 "safety": 0.10, "momentum": 0.10, "cashflow": 0},
        momentum_cols=("ret_60d", "ret_250d"),
        gates=[],
        order=3,
    ))

    register_horizon(Horizon(
        id="long", name="长线", window="3年+",
        weights={"value": 0.15, "growth": 0.20, "quality": 0.35,
                 "safety": 0.10, "momentum": 0, "cashflow": 0.20},
        momentum_cols=("ret_60d", "ret_250d"),
        gates=[],
        order=4,
    ))


_register_horizons()
```

- [ ] **Step 5: Annotate the masters** — in `value_genie/strategy/masters.py`, add one line to each registration (right after the `order=N,` line):

```python
        order=1,
        horizon="long",        # buffett: "he can afford to wait years"
```

```python
        order=2,
        horizon="long",        # munger: sit-on-your-ass investing
```

```python
        order=3,
        horizon="mid",         # graham: statistical repair window ~1-2y
```

```python
        order=4,
        horizon="short",       # livermore: pivotal points, 10% stops
```

```python
        order=5,
        horizon="long",        # duan: "这门生意十年后会是什么样"
```

```python
        order=6,
        horizon="ultrashort",  # sheng: "快进快出……never a hold"
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_horizons.py tests/test_masters.py tests/test_registry.py -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add value_genie/strategy/registry.py value_genie/strategy/masters.py value_genie/strategy/horizons.py tests/test_horizons.py
git commit -m "feat: add pluggable horizon registry with four horizons; annotate masters"
```

---

### Task 3: Horizon scoring engine

**Files:**
- Modify: `value_genie/strategy/horizons.py` (append scoring functions)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py`:

```python
from value_genie.strategy.horizons import (apply_horizon_score,
                                           recompute_momentum_score)


class TestMomentumWindow:
    def _frame(self):
        # ret_60d/ret_250d deliberately run OPPOSITE to ret_5d/ret_20d,
        # so a window switch must flip the ranking
        return pd.DataFrame({
            "market": ["A"] * 4,
            "ret_5d": [10.0, 5.0, 0.0, -5.0],
            "ret_20d": [20.0, 10.0, 0.0, -10.0],
            "ret_60d": [-5.0, 0.0, 5.0, 10.0],
            "ret_250d": [-10.0, 0.0, 10.0, 20.0],
            "value_score": [50.0] * 4, "growth_score": [50.0] * 4,
            "quality_score": [50.0] * 4, "safety_score": [50.0] * 4,
            "cashflow_score": [50.0] * 4,
        })

    def test_ultrashort_ranks_short_window(self):
        scored = apply_horizon_score(self._frame(),
                                     get_horizon("ultrashort"),
                                     min_pillars=1)
        cs = scored["composite_score"]
        assert cs.iloc[0] == cs.max()      # best short-window momentum
        assert cs.iloc[3] == cs.min()

    def test_mid_keeps_default_window(self):
        scored = apply_horizon_score(self._frame(), get_horizon("mid"),
                                     min_pillars=1)
        cs = scored["composite_score"]
        assert cs.iloc[3] == cs.max()      # best ret_60d/ret_250d wins

    def test_base_weights_override(self):
        scored = apply_horizon_score(
            self._frame(), get_horizon("long"),
            base_weights={"value": 0, "growth": 0, "quality": 1.0,
                          "safety": 0, "momentum": 0, "cashflow": 0},
            min_pillars=1)
        # quality-only weights: all rows equal, momentum window is noise
        assert scored["composite_score"].nunique() == 1

    def test_missing_cols_fall_back_with_warn(self, capsys):
        df = self._frame().drop(columns=["ret_5d", "ret_20d"])
        s = recompute_momentum_score(df, ("ret_5d", "ret_20d"))
        assert "falling back" in capsys.readouterr().err
        assert s.notna().all()

    def test_all_cols_missing_gives_nan(self):
        df = self._frame().drop(columns=["ret_5d", "ret_20d", "ret_60d",
                                         "ret_250d"])
        s = recompute_momentum_score(df, ("ret_5d", "ret_20d"))
        assert s.isna().all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL on import (`cannot import name 'apply_horizon_score'`)

- [ ] **Step 3: Implement** — append to `value_genie/strategy/horizons.py` (add imports at top: `import sys` and `import pandas as pd`, plus `from .composite import apply_composite`):

```python
import sys

import pandas as pd

from .composite import apply_composite
from .registry import Horizon, register_horizon

DEFAULT_MOMENTUM_COLS = ("ret_60d", "ret_250d")
```

(the `Horizon, register_horizon` import line replaces the old one; then append below `_register_horizons()`)

```python
# ---------------------------------------------------------------------------
# Horizon scoring
# ---------------------------------------------------------------------------
def recompute_momentum_score(df: pd.DataFrame, cols) -> pd.Series:
    """Momentum pillar score from the given return columns.

    Same recipe as ``add_pillar_scores``: per-market percentile rank,
    mean of available sub-factors. When none of ``cols`` exist in the
    frame (old snapshots), falls back to the default window with a
    WARN; when no return column exists at all, returns all-NaN (the
    momentum weight then renormalizes away inside apply_composite).
    """
    available = [c for c in cols if c in df.columns]
    if not available:
        available = [c for c in DEFAULT_MOMENTUM_COLS if c in df.columns]
        if available:
            print(f"[WARN] horizon momentum columns missing; falling "
                  f"back to {'+'.join(available)}", file=sys.stderr)
    if not available:
        return pd.Series(float("nan"), index=df.index)
    subs = []
    for col in available:
        s = pd.to_numeric(df[col], errors="coerce")
        subs.append(s.groupby(df["market"]).rank(pct=True) * 100.0)
    return pd.concat(subs, axis=1).mean(axis=1)


def apply_horizon_score(df: pd.DataFrame, horizon, base_weights=None,
                        min_pillars: int = 3) -> pd.DataFrame:
    """Composite under a horizon lens.

    Momentum is measured on the horizon's window; weights come from the
    horizon itself, or from ``base_weights`` when combined with a
    strategy (the master's taste measured at the horizon's clock).
    Gates are NOT applied here — screening callers filter separately
    before calling this; the ask horizon profile is descriptive.
    """
    out = df.copy()
    out["momentum_score"] = recompute_momentum_score(
        out, horizon.momentum_cols)
    weights = (dict(base_weights) if base_weights is not None
               else dict(horizon.weights))
    return apply_composite(out, weights, min_pillars=min_pillars)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_horizons.py tests/test_composite.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/strategy/horizons.py tests/test_horizons.py
git commit -m "feat: horizon scoring engine with per-horizon momentum windows"
```

---

### Task 4: Pipeline columns + peer kline backfill (fixes momentum-100 distortion)

**Files:**
- Modify: `value_genie/fetch/pipeline.py` (MASTER_COLUMNS, KLINE_FEATURES, new `backfill_kline_factors`)
- Modify: `value_genie/analyze.py` (`build_peer_set` uses backfill)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py` (needs `from pathlib import Path` and `from value_genie import analyze as az`, `from value_genie.fetch.pipeline import backfill_kline_factors`, `from value_genie.resolve import Match` at the top of the file):

```python
# ---------------------------------------------------------------------------
# Varied-slope snapshot: three peers with clearly different kline trends
# ---------------------------------------------------------------------------
def _write_kline(snap: Path, market: str, code: str, slope: float):
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(),
                           periods=300)
    close = pd.Series([100.0 * ((1.0 + slope) ** t) for t in range(300)])
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "close": close,
        "high": close * 1.01, "low": close * 0.99,
        "volume": [1e6] * 300, "amount": [1e8] * 300,
    }).to_csv(snap / "kline" / f"{market}_{code}.csv", index=False)


def make_varied_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "20260901"
    (snap / "kline").mkdir(parents=True)
    codes = ["600001", "600002", "600003"]
    quotes = pd.DataFrame({
        "market": "A", "code": codes,
        "name": ["Alpha Co", "Beta Co", "Gamma Co"],
        "market_id": "1", "industry": "food",
        "price": [10.0, 20.0, 30.0],
        "pe_ttm": [10.0, 20.0, 30.0], "pb": [1.0, 2.0, 3.0],
        "market_cap": [5e10, 6e10, 7e10],
    })
    quotes.to_csv(snap / "a_quotes.csv", index=False)
    fins = pd.DataFrame({
        "code": codes,
        "report_date": ["2026-06-30"] * 3,
        "revenue": [1e10, 2e10, 3e10],
        "rev_yoy": [10.0, 20.0, 5.0],
        "profit": [1e9, 2e9, 3e9],
        "profit_yoy": [15.0, 25.0, -5.0],
        "roe": [15.0, 20.0, 10.0],
        "gross_margin": [30.0, 40.0, 20.0],
    })
    fins.to_csv(snap / "a_financials.csv", index=False)
    for code, slope in [("600001", 0.000),   # flat: worst momentum
                        ("600002", 0.002), ("600003", 0.004)]:
        _write_kline(snap, "A", code, slope)
    return snap


class TestPeerBackfill:
    def test_build_peer_set_carries_kline_factors(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        peers = az.build_peer_set(snap, "A")
        for col in ("ret_5d", "ret_20d", "vol_20d", "ret_60d",
                    "ret_250d", "volatility"):
            assert col in peers.columns
        assert peers["ret_5d"].notna().all()

    def test_missing_kline_stays_nan(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        (snap / "kline" / "A_600003.csv").unlink()
        peers = az.build_peer_set(snap, "A")
        flat = peers["code"].astype(str) == "600003"
        assert peers.loc[flat, "ret_5d"].isna().all()
        assert peers.loc[~flat, "ret_5d"].notna().all()

    def test_backfill_unit(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        df = pd.DataFrame({"market": ["A", "A"],
                           "code": ["600001", "600002"]})
        out = backfill_kline_factors(df, snap)
        assert out["ret_60d"].notna().all()
        assert "vol_20d" in out.columns

    def test_flat_target_not_100th_pctile_momentum(self, tmp_path,
                                                   monkeypatch):
        """Regression: peers now carry kline factors, so a flat target
        must NOT rank itself 100th percentile on momentum."""
        snap = make_varied_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", lambda s: pd.DataFrame(
            [{"market": "A", "code": "600001", "name": "Alpha Co",
              "market_id": "1", "price": 10.5, "pct_chg": 1.2,
              "pe_ttm": 10.0, "pb": 1.1, "market_cap": 5.2e10}]))
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        r = az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                             snapshot_dir=snap)
        mom = r["scores"]["momentum"]
        assert mom is None or mom < 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL (`KeyError: 'ret_5d'` in build_peer_set test; import error for `backfill_kline_factors`)

- [ ] **Step 3: Implement in `value_genie/fetch/pipeline.py`**

3a. In `MASTER_COLUMNS`, change the line:

```python
    "pos_52w", "drawdown_52w", "ret_250d", "ret_60d", "volatility",
```

to:

```python
    "pos_52w", "drawdown_52w", "ret_250d", "ret_60d", "volatility",
    "ret_5d", "ret_20d", "vol_20d",
```

3b. Change `KLINE_FEATURES` to:

```python
KLINE_FEATURES = ("pos_52w", "drawdown_52w", "ret_250d", "ret_60d",
                  "volatility", "ret_5d", "ret_20d", "vol_20d")
```

3c. After the `kline_features` function (line ~221), add:

```python
def backfill_kline_factors(df: pd.DataFrame, snap_dir: Path) -> pd.DataFrame:
    """Add kline-derived factor columns from the snapshot's kline cache.

    Peer frames rebuilt from quotes CSVs lack kline metrics (those live
    only in master.csv); without this, a target ranks its momentum
    against itself and always shows the 100th percentile. Rows without
    a cached kline stay NaN — pandas ranks skip NaN.
    """
    import sys

    if df is None or df.empty:
        return df
    missing = [c for c in KLINE_FEATURES if c not in df.columns]
    if not missing:
        return df
    out = df.copy()
    for col in missing:
        out[col] = float("nan")
    filled = 0
    for i, row in out.iterrows():
        feats = kline_features(snap_dir, row["market"], str(row["code"]))
        if not feats:
            continue
        filled += 1
        for col in missing:
            v = feats.get(col)
            if v is not None:
                out.at[i, col] = v
    if filled:
        print(f"[INFO] backfilled kline factors for {filled} rows "
              f"from kline cache", file=sys.stderr)
    return out
```

- [ ] **Step 4: Wire into `analyze.py`** — in `value_genie/analyze.py`, change the import:

```python
from .fetch.pipeline import apply_gates, merge_a_financials, \
    merge_us_financials
```

to:

```python
from .fetch.pipeline import apply_gates, backfill_kline_factors, \
    merge_a_financials, merge_us_financials
```

and in `build_peer_set`, change the final line:

```python
    return apply_gates(df, market)
```

to:

```python
    gated = apply_gates(df, market)
    return backfill_kline_factors(gated, snap)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_horizons.py tests/test_analyze.py tests/test_pipeline.py -q`
Expected: all PASS (existing analyze tests unaffected — their fixture caches klines for all peers)

- [ ] **Step 6: Commit**

```bash
git add value_genie/fetch/pipeline.py value_genie/analyze.py tests/test_horizons.py
git commit -m "fix: backfill peer kline factors from cache; ask momentum no longer self-ranked 100th pctile"
```

---

### Task 5: screen --horizon

**Files:**
- Modify: `value_genie/report.py` (`screen()` gains `horizon` + `snap_dir` params)
- Modify: `value_genie/__main__.py` (screen parser + cmd_screen)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py` (needs `from value_genie import report` and `from value_genie.__main__ import main`):

```python
# ---------------------------------------------------------------------------
# screen --horizon
# ---------------------------------------------------------------------------
def _horizon_master() -> pd.DataFrame:
    """Three A-shares; value scores and short-window momentum are
    deliberately anti-correlated so weight choices flip the ranking."""
    rows = []
    for i, code in enumerate(["600001", "600002", "600003"]):
        rows.append({
            "market": "A", "code": code, "name": f"S{i}", "industry": "x",
            "price": 10.0, "market_cap": 1e11, "pe_ttm": 10.0 + i,
            "pb": 1.0, "ps": 1.0, "dividend_yield": 1.0,
            "rev_yoy": 10.0, "profit_yoy": 10.0, "roe": 15.0,
            "gross_margin": 40.0, "net_margin": 10.0, "debt_ratio": 40.0,
            "ret_5d": [10.0, 2.0, -3.0][i],
            "ret_20d": [20.0, 5.0, -8.0][i],
            "ret_60d": [30.0, 10.0, -5.0][i],
            "ret_250d": [40.0, 15.0, -10.0][i],
            "volatility": [50.0, 30.0, 20.0][i],
            "pos_52w": [80.0, 50.0, 20.0][i],
            "drawdown_52w": [-5.0, -15.0, -40.0][i],
            "report_date": "2026-06-30",
            "value_score": [40.0, 60.0, 50.0][i],
            "growth_score": [50.0, 50.0, 50.0][i],
            "quality_score": [50.0, 50.0, 50.0][i],
            "safety_score": [50.0, 50.0, 50.0][i],
            "momentum_score": [50.0, 50.0, 50.0][i],
            "cashflow_score": float("nan"),
            "data_completeness": 1.0,
        })
    return pd.DataFrame(rows)


class TestScreenHorizon:
    def test_horizon_alone_weights_and_gates(self):
        # ultrashort gates: vol pctl>=50 (rows 0,1) and ret_5d>=0
        # (rows 0,1) -> 600003 excluded; momentum 0.70 ranks 600001 first
        top = report.screen(_horizon_master(), horizon="ultrashort",
                            top_n=5)
        assert list(top["code"]) == ["600001", "600002"]

    def test_horizon_recomputes_momentum(self):
        # momentum-only weights on the ultrashort window: order follows
        # ret_5d/ret_20d (600001 best), NOT the stored momentum_score tie
        top = report.screen(_horizon_master(), weights={"momentum": 1.0},
                            horizon="ultrashort", top_n=5)
        assert list(top["code"])[0] == "600001"

    def test_strategy_plus_horizon_keeps_strategy_weights(self):
        # buffett has momentum weight 0 -> ranking driven by value_score
        # (600002 has 60) even though momentum is measured on short window
        top = report.screen(_horizon_master(), strategy="buffett",
                            horizon="short", top_n=5)
        assert list(top["code"])[0] == "600002"

    def test_no_horizon_unchanged(self):
        top = report.screen(_horizon_master(), top_n=5)
        assert list(top["code"])[0] == "600002"   # balanced: value-heavy


class TestScreenCliHorizon:
    def _snap(self, tmp_path):
        snap = tmp_path / "snapshots" / "20260201"
        snap.mkdir(parents=True)
        _horizon_master().to_csv(snap / "master.csv", index=False)
        return tmp_path

    def test_screen_horizon_flag(self, tmp_path):
        data_dir = self._snap(tmp_path)
        out_dir = tmp_path / "out"
        rc = main(["screen", "--data-dir", str(data_dir),
                   "--out-dir", str(out_dir), "--horizon", "short",
                   "--top", "5"])
        assert rc == 0
        assert (out_dir / "20260201_short.csv").exists()

    def test_screen_strategy_horizon_combo(self, tmp_path):
        data_dir = self._snap(tmp_path)
        out_dir = tmp_path / "out"
        rc = main(["screen", "--data-dir", str(data_dir),
                   "--out-dir", str(out_dir), "--strategy", "buffett",
                   "--horizon", "short", "--top", "5"])
        assert rc == 0
        assert (out_dir / "20260201_buffett-short.csv").exists()

    def test_screen_rejects_unknown_horizon(self, tmp_path):
        data_dir = self._snap(tmp_path)
        with pytest.raises(SystemExit):
            main(["screen", "--data-dir", str(data_dir),
                  "--horizon", "decade"])
```

Note: `test_no_horizon_unchanged` — balanced weights are value 0.35 / growth 0.25 / quality 0.30; value_score 60 for 600002 wins over 600001 (40) since growth/quality are tied. Buffett's `ocf_yield` gate is skipped with a WARN (column absent) — acceptable and consistent with existing gate-skip behavior.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL (`TypeError: screen() got an unexpected keyword argument 'horizon'`)

- [ ] **Step 3: Implement `report.screen`** — in `value_genie/report.py`:

3a. Add import at top:

```python
from .strategy.horizons import recompute_momentum_score
```

3b. Replace the whole `screen` function with:

```python
def screen(master: pd.DataFrame, strategy=None, preset=None, weights=None,
           horizon=None, snap_dir=None, top_n=None,
           markets=None) -> pd.DataFrame:
    """Apply a strategy/horizon to a master frame; return ranked rows.

    ``strategy`` is a registry id (presets + masters); ``preset`` is a
    backward-compatible alias. ``weights`` (custom pillar weights) takes
    precedence when given (gates are then skipped, as before).

    ``horizon`` adds the holding-period lens:
    - horizon alone (no strategy/preset/weights): the horizon IS the
      strategy — its weights and gates are used.
    - strategy + horizon: the strategy's weights and gates stay; only
      the momentum measurement window switches to the horizon's.
    - weights + horizon: custom weights (no gates), horizon window.
    ``snap_dir`` enables short-window factor backfill from the
    snapshot's kline cache for old snapshots.
    """
    from pathlib import Path as _Path

    from .strategy.factors import PILLARS, add_derived_factors, \
        add_pillar_scores
    from .strategy.registry import evaluate_gates, get_horizon, \
        get_strategy

    top_n = top_n or config.DEFAULT_TOP_N
    h = get_horizon(horizon) if horizon else None
    if weights:
        profile = normalize_weights(weights)
        gates = []
    elif h and not (strategy or preset):
        profile = normalize_weights(h.weights)
        gates = h.gates or []
    else:
        sid = strategy or preset or config.DEFAULT_PRESET
        s = get_strategy(sid)
        profile = normalize_weights(s.weights)
        gates = s.gates or []

    # Backfill missing pillar score columns from available raw factors
    # (old snapshots; see git history for the original 4-pillar case).
    missing_scores = [f"{p}_score" for p in PILLARS
                      if f"{p}_score" not in master.columns]
    if missing_scores:
        import sys
        recomputable = ("ret_60d" in master.columns
                        and "ret_250d" in master.columns)
        if recomputable:
            print(f"[WARN] backfilling pillar scores from raw factors "
                  f"(missing: {', '.join(missing_scores)})",
                  file=sys.stderr)
            master = add_pillar_scores(master)
        else:
            print(f"[WARN] snapshot missing score columns and raw kline "
                  f"factors; weights will normalize to available pillars "
                  f"(missing: {', '.join(missing_scores)})",
                  file=sys.stderr)

    # Old snapshots lack ret_5d/ret_20d/vol_20d; refill from kline cache
    # when screening on a horizon that needs them.
    if h is not None and snap_dir is not None:
        from .fetch.pipeline import backfill_kline_factors
        master = backfill_kline_factors(master, _Path(snap_dir))

    # Gate inputs derived from existing columns (e.g. Graham's pe_pb).
    master = add_derived_factors(master)

    if h is not None:
        master = master.copy()
        master["momentum_score"] = recompute_momentum_score(
            master, h.momentum_cols)

    if gates:
        master = master[evaluate_gates(master, gates)]

    scored = apply_composite(master, profile,
                             min_pillars=config.MIN_PILLARS)
    top = rank_top(scored, top_n, markets=markets)
    out = top.reset_index(drop=True).reindex(columns=REPORT_COLUMNS)
    out["rank"] = range(1, len(out) + 1)
    return out
```

- [ ] **Step 4: Implement the CLI** — in `value_genie/__main__.py`:

4a. In `build_parser`, change the registry-import line to include horizons:

```python
    from .strategy import registry, presets, masters, horizons  # noqa: F401
    from .strategy.registry import list_horizons, list_strategies
    strategy_ids = [s.id for s in list_strategies()]
    horizon_ids = [h.id for h in list_horizons()]
```

4b. In the `screen` parser block, after the `--preset` argument add:

```python
    ps.add_argument("--horizon", default=None, choices=horizon_ids,
                    help="holding-period lens: ultrashort|short|mid|long "
                         "(see `horizon list`)")
```

4c. Replace `cmd_screen` with:

```python
def cmd_screen(args) -> int:
    weights = _parse_weights(args.set)
    markets = _parse_markets(args.markets)
    try:
        snap_dir = report.resolve_snapshot(args.data_dir, args.snapshot)
        master = report.load_master(snap_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None

    from .strategy.registry import get_horizon, get_strategy

    strategy = args.strategy or args.preset
    explicit_strategy = (bool(args.strategy)
                         or args.preset != config.DEFAULT_PRESET)
    horizon_only = bool(args.horizon) and not explicit_strategy \
        and not weights

    try:
        top = report.screen(
            master,
            strategy=None if (horizon_only or weights) else strategy,
            weights=weights or None,
            horizon=args.horizon,
            snap_dir=snap_dir,
            top_n=args.top,
            markets=markets)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if top.empty:
        raise SystemExit("no stocks passed the strategy; try another one")

    if weights:
        profile = report.normalize_weights(weights)
        label = "custom"
    elif horizon_only:
        profile = report.normalize_weights(
            get_horizon(args.horizon).weights)
        label = args.horizon
    else:
        s = get_strategy(strategy)
        profile = report.normalize_weights(s.weights)
        label = (f"{strategy}-{args.horizon}" if args.horizon
                 else strategy)

    print(f"== Value Genie screen ==")
    print(f"snapshot : {snap_dir.name}")
    print(f"strategy : {label} ({report.describe_weights(profile)})")
    if args.horizon:
        h = get_horizon(args.horizon)
        print(f"horizon  : {h.name} ({h.window}), momentum on "
              f"{'+'.join(h.momentum_cols)}")
    print(f"markets  : {', '.join(markets or config.MARKETS)}")
    print()
    print(report.format_console(top))

    out_dir = Path(args.out_dir) if args.out_dir else config.OUTPUT_DIR
    stem = f"{snap_dir.name}_{label}"
    csv_path = report.export_csv(top, out_dir / f"{stem}.csv")
    md_path = report.export_markdown(
        top, out_dir / f"{stem}.md",
        title=f"Value Genie - {snap_dir.name} - {label}",
        meta={"snapshot": snap_dir.name, "strategy": label,
              "weights": report.describe_weights(profile),
              "markets": ", ".join(markets or config.MARKETS),
              "stocks": len(top)})
    print(f"\nwrote {csv_path}")
    print(f"wrote {md_path}")
    return 0
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_horizons.py tests/test_report.py tests/test_cli.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add value_genie/report.py value_genie/__main__.py tests/test_horizons.py
git commit -m "feat: screen --horizon (alone, or combined with --strategy)"
```

---

### Task 6: ask four-horizon profile

**Files:**
- Modify: `value_genie/analyze.py` (analyze_stock, renderers, to_json)
- Modify: `value_genie/__main__.py` (ask parser + cmd_ask)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py`:

```python
class TestAskHorizonProfile:
    def _result(self, tmp_path, monkeypatch, horizon=None):
        snap = make_varied_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", lambda s: pd.DataFrame(
            [{"market": "A", "code": "600001", "name": "Alpha Co",
              "market_id": "1", "price": 10.5, "pct_chg": 1.2,
              "pe_ttm": 10.0, "pb": 1.1, "market_cap": 5.2e10}]))
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        return az.analyze_stock(
            Match("A", "600001", "Alpha Co", 100.0, "1"),
            snapshot_dir=snap, horizon=horizon)

    def test_profile_has_four_horizons(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        assert set(r["horizon_profile"]) == {"ultrashort", "short",
                                             "mid", "long"}
        for v in r["horizon_profile"].values():
            assert 0 <= v["score"] <= 100
            assert 0 <= v["percentile"] <= 100

    def test_flat_stock_scores_low_on_momentum_horizons(self, tmp_path,
                                                        monkeypatch):
        # Alpha's flat kline is the worst of three -> ultrashort (0.70
        # momentum) must rank it lower than long (momentum weight 0)
        r = self._result(tmp_path, monkeypatch)
        assert (r["horizon_profile"]["ultrashort"]["percentile"]
                < r["horizon_profile"]["long"]["percentile"])

    def test_brief_contains_profile(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_brief(r)
        assert "horizon profile" in text
        assert "ultrashort" in text and "long" in text

    def test_single_horizon_view(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch, horizon="mid")
        assert r["horizon"] == "mid"
        text = az.render_brief(r)
        assert "horizon lens" in text and "中线" in text
        assert "ultrashort" not in text

    def test_json_contains_profile(self, tmp_path, monkeypatch):
        import json
        r = self._result(tmp_path, monkeypatch, horizon="short")
        data = json.loads(az.to_json(r))
        assert data["horizon"] == "short"
        assert "mid" in data["horizon_profile"]
        assert "ultrashort" in data["horizon_profile"]

    def test_evidence_contains_profile(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_evidence(r)
        assert "horizon profile" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL (`TypeError: analyze_stock() got an unexpected keyword argument 'horizon'`)

- [ ] **Step 3: Implement in `value_genie/analyze.py`**

3a. Extend imports:

```python
from .strategy.horizons import apply_horizon_score, list_horizons
from .strategy.registry import get_horizon, get_strategy
```

3b. Change `analyze_stock` signature and add the profile computation. New signature:

```python
def analyze_stock(match: Match, snapshot_dir=None, live: bool = True,
                  horizon: str | None = None) -> dict:
```

Inside, after `result = {"match": match, ...}` add `"horizon": horizon,` to the dict literal:

```python
    result = {"match": match,
              "snapshot": snap.name if snap else None,
              "horizon": horizon,
              "warnings": []}
```

Then, still inside the `else:` branch of the peers block (after the `for col, _label, lower in EVIDENCE_METRICS:` loop ends, still inside `else:`), append:

```python
            # Four-horizon suitability profile (descriptive: screening
            # gates do not apply; momentum measured per horizon window)
            prof = {}
            for hz in list_horizons():
                scored_h = apply_horizon_score(frame, hz, min_pillars=1)
                comp = scored_h.iloc[-1].get("composite_score")
                if comp is None or pd.isna(comp):
                    continue
                prof[hz.id] = {
                    "score": round(float(comp), 1),
                    "percentile": round(float(
                        (scored_h["composite_score"] < comp).mean()
                        * 100.0), 1),
                }
```

and after the whole `if snap is not None:` block (next to the other `result[...] = ...` lines):

```python
    result["horizon_profile"] = prof if snap is not None else {}
```

Note: `prof` must be initialized before the `if snap is not None:` block: add `prof = {}` right after the `pct, scores, composite_pct = {}, {}, None` line.

3c. Add the renderer helper (before `render_brief`):

```python
def _horizon_lines(result: dict) -> list[str]:
    """The four-horizon (or single-horizon) profile block."""
    prof = result.get("horizon_profile") or {}
    if not prof:
        return []
    m = result["match"]
    only = result.get("horizon")
    names = {h.id: h.name for h in list_horizons()}
    order = [h.id for h in list_horizons()]
    entries = [(hid, prof[hid]) for hid in order if hid in prof]
    if only:
        entries = [(hid, v) for hid, v in entries if hid == only]
    weakest = (min(prof, key=lambda k: prof[k]["percentile"])
               if len(prof) > 1 else None)
    lines = [f"horizon profile (vs {m.market} gated universe):"]
    for hid, v in entries:
        mark = "   <- weakest" if hid == weakest else ""
        lines.append(f"  {hid:<11}{names.get(hid, ''):<6}"
                     f"{v['score']:>6.1f}  ({v['percentile']:.0f}th "
                     f"pctile){mark}")
    return lines
```

3d. In `render_brief`, after the key-numbers for-loop (`for col, label in (("pe_ttm", "PE"), ...)`), insert:

```python
    h = result.get("horizon")
    if h:
        hh = get_horizon(h)
        lines.append(f"horizon lens: {hh.name} ({hh.window})")
    lines += _horizon_lines(result)
```

3e. In `render_evidence`, after the `blended composite` line, insert:

```python
    h = result.get("horizon")
    if h:
        hh = get_horizon(h)
        lines.append(f"horizon lens: {hh.name} ({hh.window})")
    lines += _horizon_lines(result)
```

3f. In `to_json`, add to the payload dict (after `"composite_percentile"`):

```python
        "horizon": result.get("horizon"),
        "horizon_profile": result.get("horizon_profile"),
```

- [ ] **Step 4: Implement the CLI** — in `value_genie/__main__.py`:

4a. In the `ask` parser block, add:

```python
    pa.add_argument("--horizon", default=None, choices=horizon_ids,
                    help="single-horizon view (default: all four)")
```

4b. In `cmd_ask`, change the call:

```python
    result = az.analyze_stock(m, horizon=args.horizon)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_horizons.py tests/test_analyze.py tests/test_cli.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add value_genie/analyze.py value_genie/__main__.py tests/test_horizons.py
git commit -m "feat: ask emits four-horizon suitability profile; --horizon single view"
```

---

### Task 7: horizon list + strategy list horizon column

**Files:**
- Modify: `value_genie/__main__.py` (cmd_horizon_list, cmd_strategy_list, parser)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py` (needs `from value_genie.__main__ import build_parser` — merge with the existing `main` import):

```python
class TestHorizonCli:
    def test_horizon_list(self, capsys):
        rc = main(["horizon", "list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "ultrashort" in out and "超短线" in out
        assert "long" in out and "长线" in out
        assert "ret_5d+ret_20d" in out

    def test_strategy_list_shows_horizons(self, capsys):
        rc = main(["strategy", "list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "ultrashort" in out and "long" in out

    def test_ask_accepts_horizon_flag(self):
        p = build_parser()
        args = p.parse_args(["ask", "X", "--horizon", "mid"])
        assert args.horizon == "mid"
        args = p.parse_args(["screen", "--horizon", "short"])
        assert args.horizon == "short"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL (`horizon list` → argparse SystemExit: invalid choice)

- [ ] **Step 3: Implement** — in `value_genie/__main__.py`:

3a. Add `cmd_horizon_list` after `cmd_strategy_list`:

```python
def cmd_horizon_list(args) -> int:
    """List all registered horizons."""
    from .strategy.factors import PILLARS
    from .strategy.registry import list_horizons
    items = list_horizons()
    if not items:
        print("no horizons registered")
        return 1
    print(f"{'id':<12} {'name':<8} {'window':<12} weights")
    print("-" * 96)
    for h in items:
        w = " / ".join(f"{p}={h.weights.get(p, 0):.2f}"
                       for p in PILLARS if h.weights.get(p, 0) > 0)
        mom = f"  momentum: {'+'.join(h.momentum_cols)}"
        gates = f"  gates: {len(h.gates)}" if h.gates else ""
        print(f"{h.id:<12} {h.name:<8} {h.window:<12} {w}{mom}{gates}")
    return 0
```

3b. Change the strategy-list table in `cmd_strategy_list` to include the horizon column:

```python
    print(f"{'id':<16} {'kind':<8} {'horizon':<11} {'name':<44} weights")
    print("-" * 110)
    for s in items:
        w = " / ".join(f"{p}={s.weights.get(p, 0):.2f}"
                       for p in PILLARS if s.weights.get(p, 0) > 0)
        gates = f"  gates: {len(s.gates)}" if s.gates else ""
        hz = s.horizon or "-"
        print(f"{s.id:<16} {s.kind:<8} {hz:<11} {s.name:<44} {w}{gates}")
```

3c. In `build_parser`, after the `strategy` subparser block add:

```python
    phz = sub.add_parser("horizon", help="list registered horizons")
    phz_sub = phz.add_subparsers(dest="cmd")
    phz_sub.add_parser("list", help="list all horizons (default)")
    phz.set_defaults(func=cmd_horizon_list)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_horizons.py tests/test_cli.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/__main__.py tests/test_horizons.py
git commit -m "feat: horizon list command; strategy list shows natural horizon"
```

---

### Task 8: Skill playbook + AGENTS.md routing

**Files:**
- Create: `skills/14-horizon-framework.md` (13 is taken by holding-deep-review)
- Modify: `AGENTS.md` (routing table + horizon paragraph)
- Test: `tests/test_horizons.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_horizons.py`:

```python
class TestSkillFile:
    def test_horizon_skill_loads(self):
        from value_genie import config, skills as sk
        items, errors = sk.load_skills(config.SKILLS_DIR)
        ids = {s.id for s in items}
        assert "horizon-framework" in ids
        assert not any("14-horizon" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_horizons.py -q`
Expected: FAIL (`'horizon-framework' not in ids`)

- [ ] **Step 3: Create `skills/14-horizon-framework.md`**:

```markdown
---
id: horizon-framework
title: Time-Horizon Framework (超短线/短线/中线/长线)
order: 13
triggers:
  - 短期内最推荐
  - 短期内最被低估
  - 适合中长期持有
  - 适合长期持有吗
  - 超短线
  - 短线有什么机会
  - 中线
  - 长线
  - 持有几年
commands:
  - screen --horizon ultrashort|short|mid|long
  - ask X [--horizon H]
version: 1
updated_at: 2026-09-01T12:00:00
---

# Playbook

Answer holding-period-scoped questions with the horizon lens. The
toolkit measures; you judge. The quantitative layer (factor weights +
momentum windows per horizon) is only half the answer — the other half
is the qualitative overlay below, which no factor table can produce.

## The four horizons

| id | window | weights essence | momentum window |
|---|---|---|---|
| ultrashort | 1-10 交易日 | 注意力/动量为王 | ret_5d+ret_20d |
| short | 10日-3月 | 趋势确认+修复启动 | ret_20d+ret_60d |
| mid | 3月-3年 | 估值修复+业绩兑现 | ret_60d+ret_250d |
| long | 3年+ | 商业模式+现金流 | （权重为0） |

Master mapping (each master has a natural horizon): Buffett/Munger/Duan
→ long, Graham → mid, Livermore → short, Sun → ultrashort. When the
user asks "X 会怎么看 Y", answer within that master's natural horizon.

## Commands

1. "短期内最推荐/最被低估的股票是什么？"
   `python -m value_genie screen --horizon short --top 20`
   (最被低估 → add `--set value=0.4 momentum=0.3` or screen value-heavy
   then check short-window momentum on survivors via `ask --evidence`.)
2. "超短线有什么机会？"
   `python -m value_genie screen --horizon ultrashort --top 20`
3. "X 适合中长期持有吗？"
   `python -m value_genie ask X` — read the four-horizon profile, then
   apply the qualitative overlay below, then commit to a judgment.
4. "过巴菲特门槛的股票里短线动量最好的是谁？"
   `python -m value_genie screen --strategy buffett --horizon short`

## Qualitative overlay (the part factors cannot see)

- ultrashort/short: 事件、情绪、地缘政治、流动性、注意力周期。
  `ret_5d`/`ret_20d`/`vol_20d` 来自 ask --json 的 metrics。
  **每条回答必须带警示**：本工具箱的价值基因不提倡超短线/短线
  交易；给出仓位纪律与退出条件（利弗莫尔的 −10% 线或注意力高潮
  退出），并明确说明短周期受不可预测的突发事件支配。
- mid: 业绩兑现节奏（未来 4-8 个季度）、催化剂（回购/分红/政策/
  行业拐点）、行业景气位置、估值修复的路线（为什么市场会纠错、
  什么事件触发纠错）。
- long: 商业模式耐久性、护城河（毛利率/ROE 的持续性而非水平）、
  技术路线之争、时代趋势。寒武纪模板：中期（3年）AI 推理需求
  爆发是可量化的（growth 因子强）；长期（10年）NPU 路线 vs 通用
  计算/机器人等新场景的路线风险是质性判断 —— 两层结论可以不同，
  "适合中线持有但不适合长线持有"是合法且常见的答案。

## Answer template (per-horizon suitability)

> [单句结论：X 在 H 周期适合/不适合持有]. Horizon profile（vs 本市场
> gated universe）：超短线 S1（P1 百分位）/ 短线 S2（P2）/ 中线 S3
> （P3）/ 长线 S4（P4）—— [最弱周期是 Hw，因为…]. 质性层：[按上面
> checklist 逐项判断，量化覆盖不了的部分明确说"这是我的判断"].
> [风险旗标 verbatim]. Data as of [snapshot date].

## Field Notes
```

- [ ] **Step 4: Update `AGENTS.md`** — in the routing table, after the macro row, add:

```markdown
| "短期内最推荐/最被低估的股票" | horizon-framework | `python -m value_genie screen --horizon short` |
| "超短线/短线有什么机会" | horizon-framework | `python -m value_genie screen --horizon ultrashort`（必须附短炒警示） |
| "X适合中长期持有吗" | horizon-framework | `python -m value_genie ask X`（四周期剖面）+ 13 号 playbook 质性层 |
```

And after the "Investment masters" section heading paragraph, add:

```markdown
## Holding-period dimension

Four horizons (registry-backed, `python -m value_genie horizon list`):
ultrashort (1-10 交易日, ret_5d+ret_20d), short (10日-3月,
ret_20d+ret_60d), mid (3月-3年, 估值修复+业绩兑现), long (3年+,
商业模式+现金流). `screen --horizon H` screens under the horizon;
`--strategy X --horizon Y` keeps the master's weights/gates and swaps
only the momentum window; `ask X` prints a four-horizon suitability
profile. The value DNA of this toolkit: mid/long are the promoted
horizons; ultrashort/short answers must carry the caution line and
position-sizing discipline.
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_horizons.py tests/test_skills.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add skills/14-horizon-framework.md AGENTS.md tests/test_horizons.py
git commit -m "feat: horizon-framework skill playbook + AGENTS.md routing"
```

---

### Task 9: Full regression + live smoke + self-refinement note

**Files:** none new (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `$env:PYTHONPATH = "libs"; python -B -m pytest tests -q`
Expected: all PASS, zero failures (existing tests must be unchanged)

- [ ] **Step 2: Live smoke — horizon list**

Run: `$env:PYTHONPATH = "libs"; python -m value_genie horizon list`
Expected: four rows, ultrashort → long, weights and momentum windows printed

- [ ] **Step 3: Live smoke — ask profile (real snapshot 20260901)**

Run (non-blocking, redirect to file):
`$env:PYTHONPATH = "libs"; python -m value_genie ask 贵州茅台 --json 2>$null | Out-File -Encoding utf8 tmp_ask_moutai.json`
Expected in output: `"horizon_profile"` with all four ids; `momentum` score NOT 100.0 (distortion fixed); ret_60d percentile NOT 50.0

- [ ] **Step 4: Live smoke — screen --horizon short (real snapshot)**

Run: `$env:PYTHONPATH = "libs"; python -m value_genie screen --horizon short --top 5`
Expected: header shows `horizon  : 短线 (10日-3月), momentum on ret_20d+ret_60d`; output CSV/MD under `output/20260901_short.*`

- [ ] **Step 5: Record the lesson (self-refinement protocol)**

Run: `$env:PYTHONPATH = "libs"; python -m value_genie skill note single-stock-analysis "peer frames rebuilt from quotes CSVs carry no kline factors; build_peer_set now backfills from the kline cache — before 20260902 ask always showed momentum/safety at the 100th pctile because the target ranked against itself"`

Expected: `noted on single-stock-analysis (v4): ...`

- [ ] **Step 6: Clean up smoke-test temp files** — delete `tmp_ask_moutai.json` if created, plus any pre-existing `tmp_scr_*.txt`/`tmp_ask_*` leftovers only if they were created by this session.

- [ ] **Step 7: Final commit (if any temp/docs changes remain)**

```bash
git status
```

If clean except intended artifacts, done. Otherwise commit leftovers appropriately.

---

## Self-review checklist (run after writing, before execution)

1. **Spec coverage** — §3 definitions → Task 2; §4 window switching → Tasks 2/3; §5 CLI → Tasks 5/7; §6 profile → Task 6; §7 skill → Task 8; §8 data flow/backfill → Tasks 1/4; §9 testing → every task + Task 9; §10 files → all touched. ✓
2. **Placeholders** — none; every step carries complete code or exact commands. ✓
3. **Type consistency** — `recompute_momentum_score(df, cols)`, `apply_horizon_score(df, horizon, base_weights=None, min_pillars=3)`, `backfill_kline_factors(df, snap_dir)`, `build_peer_set(snapshot_dir, market)`, `Horizon(id, name, window, weights, momentum_cols, gates, order)`, `Strategy.horizon` — used consistently across tasks. ✓
4. **Behavior risk** — Task 4 changes existing `ask` output values (momentum/safety percentiles become real instead of degenerate 100/50). This is a deliberate bug fix, documented in the spec discovery note and in Task 9's expected smoke output. ✓
