# Value Genie — Time-Horizon Dimension (Design)

Date: 2026-09-01
Status: approved
Depends on: `2026-09-01-ai-research-toolkit-design.md` (Phase 2: ask/compare/overview, skills),
`2026-09-01-master-registry-system.md` (pluggable strategy/data-source registries)

## 1. Problem

The toolkit scores stocks on six pillars but has no concept of *holding
period*. The user asks horizon-scoped questions the system cannot answer
quantitatively:

- "短期内最被低估的股票是哪一只？" (short-window mispricing that
  corrects fast)
- "寒武纪适合中长期持有吗？" (per-horizon suitability of one stock)

The user's own analysis illustrates the gap: Cambricon is (in their
view) a **mid-term** hold — AI-inference demand explodes for ~3 years —
but not a **long-term** hold, because its NPU路线 may lose to broader
AI application trends (robotics etc.) over 10 years. That judgment
combines a quantifiable layer (growth factors) with a qualitative layer
(technology-roadmap reasoning) — the toolkit must support both.

Verified against the six master playbooks, holding periods span the
spectrum and the user's value-investing intuition holds:

| Master | Natural horizon | Playbook evidence |
|---|---|---|
| Buffett | long | "he can afford to wait years" |
| Munger | long | "sit-on-your-ass investing" |
| Duan | long | "这门生意十年后会是什么样" |
| Graham | mid | statistical repair window (~1-2y) |
| Livermore | short | pivotal points, 10% stops |
| Sun | ultrashort | "快进快出……never a hold" |

## 2. Goals

1. Four horizons as a pluggable registry (mirrors Strategy registry):
   `ultrashort` (1-10 trading days), `short` (10 days-3 months),
   `mid` (3 months-3 years), `long` (3+ years).
2. `--horizon` as an orthogonal CLI parameter on `screen` and `ask`.
3. `ask <name>` outputs a four-horizon suitability profile by default
   (score + within-market percentile per horizon).
4. New short-window kline factors: `ret_5d`, `ret_20d`, `vol_20d`.
5. Each master strategy annotated with its natural horizon.
6. A new skill playbook (`13-horizon-framework.md`) carries the
   qualitative layer: per-horizon reasoning checklists, master-horizon
   mapping, answer templates, and the mandatory short-horizon caution.
7. Full backward compatibility: no `--horizon` → behavior identical.

Non-goals: app.py visualization changes (AI pipelines take priority);
`overview --horizon` (future extension); intraday data (kline remains
daily).

## 3. Horizon definitions

Registered as `Horizon` dataclass: `id, name, window, weights, gates,
momentum_cols, order`. Ordering is fixed ultrashort → long.

| id | name | window | value | growth | quality | safety | momentum | cashflow | gates |
|---|---|---|---|---|---|---|---|---|---|
| ultrashort | 超短线 | 1-10 交易日 | 0 | 0.25 | 0.05 | 0 | **0.70** | 0 | volatility pctl≥50, ret_5d≥0 |
| short | 短线 | 10日-3月 | 0.20 | 0.20 | 0.10 | 0.15 | **0.35** | 0 | ret_20d≥0 |
| mid | 中线 | 3月-3年 | **0.30** | **0.30** | 0.20 | 0.10 | 0.10 | 0 | — |
| long | 长线 | 3年+ | 0.15 | 0.20 | **0.35** | 0.10 | 0 | **0.20** | — |

Weight rationale: ultrashort is attention-driven (Sun-style: momentum
is the asset, growth numbers are narrative fuel); short is trend
confirmation + repair starting (Livermore-style); mid is repair +
earnings delivery (Graham-style); long is business model + owner
earnings (Buffett/Duan-style). Short horizons carry momentum gates
("the market must prove the trend first"); mid/long rely on weights
alone. Weights are registry data — tunable without code changes.

## 4. Momentum window switching

The momentum pillar currently = per-market percentile mean of
`ret_60d` + `ret_250d`. Per horizon the sub-factor set changes:

- ultrashort: `ret_5d` + `ret_20d`
- short: `ret_20d` + `ret_60d`
- mid: `ret_60d` + `ret_250d` (= status quo)
- long: `ret_60d` + `ret_250d` (default window; when long is used alone
  its momentum *weight* is 0, but the window still matters for
  combinations, e.g. livermore × long)

Implementation: `horizons.apply_horizon_score(df, horizon, base_weights)`
recomputes `momentum_score` from the horizon's columns, then runs the
existing `apply_composite` with the horizon's (or blended) weights.
Existing `PILLAR_FACTORS` and default pillar scores are untouched —
horizon scoring is an additive layer.

## 5. CLI semantics

```
screen --horizon short                      # horizon weights + gates
screen --strategy buffett --horizon short   # strategy weights + gates,
                                            # momentum measured on the
                                            # short window
ask 寒武纪                                   # brief now includes the
                                            # four-horizon profile
ask 寒武纪 --horizon mid                     # single-horizon detail
horizon list                                 # registry listing
```

Combination rule: `--strategy X --horizon Y` keeps X's weights and
gates (the master's taste) and swaps only the momentum measurement
window (the horizon's clock). `--horizon` alone uses the horizon's own
weights and gates. Without `--horizon`, nothing changes.

`strategy list` shows each master's natural horizon (new `horizon`
field on Strategy, default empty for presets).

## 6. ask horizon profile

`analyze_stock` additionally computes four horizon scores (each vs the
stock's market gated universe) and includes them in brief / evidence /
JSON outputs:

```
horizon profile (vs A gated universe):
  ultrashort   62.3  (71st pctile)
  short        55.1  (58th pctile)
  mid          48.7  (44th pctile)
  long         31.2  (12th pctile)   ← weakest
```

Existing verdict, risk flags and evidence tables are unchanged; the
profile is an additive block. `--horizon H` renders the detailed
single-horizon view instead.

## 7. Qualitative layer: skills/13-horizon-framework.md

YAML frontmatter (id `horizon-framework`, triggers: 短线/中线/长线/
超短线/适合持有/持有几年/时间维度) + playbook body:

- Routing table: horizon-scoped questions → which commands to run.
- Per-horizon qualitative checklists:
  - ultrashort/short: events, sentiment, geopolitics, liquidity,
    attention cycle. **Every answer must carry the value-toolkit
    caution** (本工具箱的价值基因不提倡短炒) + position sizing and
    exit discipline.
  - mid: earnings delivery cadence, catalysts, industry cycle
    position, repair logic.
  - long: business-model durability, moat, technology-roadmap
    contests, era trends. Includes the Cambricon template: mid-term
    demand explosion (quantifiable via growth factors) vs long-term
    NPU-roadmap risk (qualitative judgment).
- Master-horizon mapping table (from §1).
- Answer templates per question type, including "X适合中长期持有吗"
  (per-horizon verdict + quantitative profile + AI qualitative
  overlay + explicit final judgment).
- Field Notes section, append-only, same evolution mechanism.

## 8. Data flow & old-snapshot compatibility

- `kline_metrics()` gains `ret_5d` / `ret_20d` / `vol_20d` (computed
  from the existing close series; pure addition).
- `fetch/pipeline.py`: the three factors join `KLINE_FEATURES` and
  `MASTER_COLUMNS` → new snapshots carry them automatically.
- Old snapshots: `screen --horizon ultrashort|short` backfills the
  missing short-window columns from the snapshot's kline cache via the
  existing `kline_features()` helper; if klines are also missing, fall
  back to the `ret_60d` window and print `[WARN]` (mirrors the
  established momentum-recalc degradation convention).
- `ask`: `target_kline_metrics` already computes live from klines, so
  the new factors are available immediately.

## 9. Testing

New `tests/test_horizons.py` (standalone, like the rest):

1. Registry: four horizons registered, fixed ordering, `horizon list`
   renders.
2. Momentum window: horizon momentum scores use the correct columns;
   default pillar scores unchanged when no horizon is applied.
3. Scoring: `apply_horizon_score` produces composite in 0-100 and
   respects missing-column degradation (weights renormalize).
4. Gates: ultrashort/short gates filter as specified.
5. CLI: `--horizon` on screen/ask; combination semantics
   (strategy+horizon keeps strategy weights, swaps momentum window);
   no `--horizon` → byte-identical behavior.
6. Masters: `horizon` annotations present and correct.
7. Profile: ask output (brief/evidence/json) contains the four-horizon
   block.

Existing test suite must pass unchanged.

## 10. Files touched

| File | Change |
|---|---|
| `value_genie/strategy/registry.py` | Horizon dataclass + registry; Strategy.horizon field |
| `value_genie/strategy/horizons.py` (new) | four horizon definitions, window recompute, scoring |
| `value_genie/strategy/factors.py` | kline_metrics: ret_5d / ret_20d / vol_20d |
| `value_genie/fetch/pipeline.py` | KLINE_FEATURES / MASTER_COLUMNS + backfill hook |
| `value_genie/analyze.py` | four-horizon profile in analyze_stock + renders |
| `value_genie/report.py` | screen() accepts horizon |
| `value_genie/__main__.py` | --horizon on screen/ask; horizon list |
| `skills/13-horizon-framework.md` (new) | qualitative playbook |
| `tests/test_horizons.py` (new) | coverage per §9 |
| `AGENTS.md` | routing-table rows for horizon questions |
