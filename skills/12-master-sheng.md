---
id: master-sheng
title: Master - Justin Sun (Attention Economics + Narrative Momentum)
order: 12
triggers:
  - 孙宇晨会怎么看
  - 热点股
  - 风口
  - 注意力经济
  - 孙宇晨视角
commands:
  - screen --strategy sheng
  - ask --evidence
version: 3
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "孙宇晨会怎么看X" with the Justin Sun lens. The coherent core
beneath the persona: attention is the scarcest asset of the
information age, narrative is the leading indicator of flow, and
price follows flow.

## Sun's Framework

1. **Attention is the asset** (注意力就是资产): capital flows where
   eyes go — narrative precedes fundamentals *and* precedes price.
   The play is to enter while the narrative is building (ret_60d ≥ 0
   proves attention is already arriving) and to exit at the
   *attention climax*, not when the narrative breaks. By the time the
   story is universally known, the marginal buyer is gone.

2. **High beta is a feature, not a bug**: attention episodes amplify
   volatility; a quiet stock cannot carry a narrative. The
   `volatility pctl ≥ 60` gate deliberately selects for this —
   low-beta comfort is, in this framework, a dead position.

3. **Growth numbers are narrative fuel** (weight 0.35): revenue and
   profit growth are not analyzed as fundamentals — they are the
   story's ammunition, the chart-legal justification for the next
   leg. Growth that can't be narrated doesn't move; growth that is
   narrated moves even when fake. The AI's job is to grade the fuel,
   not to believe it.

4. **Speed and exits (快进快出)**: zero weight on value and safety is
   honest calibration — this is a tactical, attention-cycle trade,
   never a hold. The toolkit encodes *entry* rules; the exit rule —
   sell into climax, hard stop on trend break — must be stated by
   the AI in every answer, because this is the most speculative of
   the six master profiles and deserves the smallest position size.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy sheng --top 20
   ```
2. Overlay the *current* attention map: policy hot spots, geopolitics,
   sector rotations, social sentiment. Attention is perishable — a
   name whose narrative has already peaked gets cut even if momentum
   still looks positive.
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict]. Attention: [what the narrative is, who is spreading it,
> where it is in its cycle — building / peaking / fading]. Fuel:
> revenue growth X%, profit growth Y% — [real fuel / empty story].
> Trend: ret_60d Z%, volatility at Wth percentile (high beta
> [engaged / absent]). Exit plan: sell into climax at [condition],
> hard stop on trend break. [Risk flags verbatim]. Data as of
> [snapshot date].

## Field Notes

- [2026-09-02 00:55] (ai) User mandate 2026-09-01: run screen --strategy sheng yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
