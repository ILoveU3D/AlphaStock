# Quant-Master Fusion (QMF) Design — 2026-09-15

## Problem

The GSL case (2026-09-15) exposed the split-brain problem: quantitative
screens rank GSL #1 (PE×PB=3.66), the 7-master qualitative layer vetoes
it 6:1 (cycle trap + insider selling). The user mandate: every
recommendation must output ONE "quant+master fused optimal" pick — no
case-by-case branching, no separate quant-best vs master-best answers.

## Design (approved: option B + cycle-trap codified)

Four-layer pipeline, layers 1-2 code-enforced, layers 3-4 AI-run per
skill 18:

### L1 Quant consensus (code) — `masters-vote` command

- New module `value_genie/strategy/consensus.py`, new CLI subcommand
  `python -m value_genie masters-vote [--markets ...] [--top N] [--json]`.
- Freshness-gated like `recommend` (recommendation-layer command).
- For each registered `kind="master"` strategy: `evaluate_gates(df,
  s.gates)` → boolean vote per stock. Output columns:
  - `vote_count` (0-7), `masters_passed` (comma list)
  - `mean_composite` = mean of the 7 masters' weighted composite
    (pillar scores from master.csv, weights from each master)
  - ranked by vote_count desc, mean_composite desc
- Derived factors (`pe_pb` etc.) added via `add_derived_factors`, same
  as `report.screen`.

### L2 Cycle-trap veto (code)

Snapshot-level flags for the whole pool:
- `profit_spike`: profit_yoy >= +200 (low-base / one-off rebound)
- Live forward-PE divergence pass on the top-N **A-share** rows (the
  only market with an EPS-consensus source, Eastmoney reportapi):
  - eps_ttm = price / pe_ttm (snapshot columns; price cancels)
  - eps_fwd = median(predictThisYearEps) over recent ratings
    (`fetch_stock_ratings`)
  - `pe_divergence` = eps_ttm / eps_fwd; >= 1.5 → `cycle_trap`
    (market expects EPS to fall ≥ 1/3; the GSL signature: TTM 4.30 vs
    fwd 8.41), >= 1.25 → `cycle_warn`
- HK/US: no consensus-EPS source → divergence stays null, gap declared
  (fail-open with explicit `data_gap` marker, never fabricated).

### L3 Master qualitative layer (AI, skill 18)

Survivors of L1+L2 get the 7-master vote table (business model /
culture / moat / earn-lose paths) per the deepened playbooks, fed by
`ask X --evidence` + `intel X`.

### L4 Fused verdict (AI, skill 18)

AI keeps decision authority (user principle: NOT a mechanical gate
intersection): fuses master consensus + user style + market conditions
into ONE recommendation + Duan position discipline (-50% test). Output
shape: verdict first, vote table, data gaps declared.

## Deliverables

1. `value_genie/strategy/consensus.py` (votes + flags + live pass)
2. `masters-vote` CLI subcommand (console + `--json`)
3. `skills/18-fused-quant-master.md` (QMF playbook, order 18)
4. AGENTS.md: routing row + answer-shape #5 rewrite (user mandate
   2026-09-15: fused flow is THE standard for every recommendation)
5. `tests/test_consensus.py` (unit: votes, flags, divergence math)

## Non-goals

- No LLM inside the toolkit (L3/L4 stay with the calling AI).
- No HK/US consensus-EPS scraping (sources absent; gap declared).
- `recommend --user` internals unchanged; QMF is the AI-side flow that
  wraps it at L4.
