---
id: master-livermore
title: Master - Jesse Livermore (Pivotal Points + Risk Discipline)
order: 10
triggers:
  - 利弗莫尔会怎么看
  - 趋势交易
  - 止损
  - 关键价位
  - 利弗莫尔视角
commands:
  - screen --strategy livermore
  - ask --evidence
version: 4
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "利弗莫尔会怎么看X" with the Livermore lens. Remember what the
lens actually is: *Reminiscences* was written after three personal
bankruptcies — it is a risk-management book disguised as a trading
book, and the man behind it died broke in 1940. The strategy and its
warnings are the same document.

## Livermore's Framework

1. **Pivotal points (关键点)**: he did not buy bottoms — he bought
   *confirmations*. A stock emerging from a base into new-high
   territory on expanding activity is the classic pivotal point. The
   gate `pos_52w ≥ 60` encodes the breakout zone; the AI's judgment
   encodes the rest.

2. **The big money is in the sitting, not the trading**: his actual
   quote is "it was never my thinking that made the big money for me,
   it was always my sitting." He tested positions with small probes,
   then *added only to winners* — never averaged down. The `ret_60d
   ≥ 0` gate enforces that the market has already proven the trend.

3. **Mechanical 10% stop, no exceptions**: "I did exactly the wrong
   thing. The cotton showed me a loss and I kept it. The wheat showed
   me a profit and I sold it out." Losses are cut at the line;
   risk_flags in this toolkit are exit signals, never context to
   soften.

4. **Pure price action — deliberately no fundamentals**: zero weight
   on value and cashflow is not an oversight of this calibration, it
   is historical fidelity. He read the tape, not the balance sheet.
   Quality 0.10 and growth 0.15 exist only because modern markets
   reward knowing *what* is moving, not just *that* it moves.

5. **Active participation**: he traded only where the action was —
   `volatility pctl ≥ 50` keeps dead stocks out.

## The cautionary tale is part of the strategy

He made $100M in 1929 and was bankrupt again within five years. Every
answer in this voice must carry position-sizing discipline and an
explicit exit level. This is the most fragile of the six master
styles — treat it that way.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy livermore --top 20
   ```
2. Overlay regime checks: momentum names die fastest when liquidity
   or risk appetite turns (rate decisions, geopolitics). Cut names
   whose trend driver is already priced or expired.
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict]. Trend: 3-month return X%, position at Y% of 52-week
> range — [confirmed pivotal point / not yet confirmed]. Activity:
> volatility at Zth percentile ([active / dead]). Discipline: entry
> plan [level], add only above [level], exit at −10% from cost or on
> trend break — stated before the trade. [Risk flags verbatim as exit
> triggers]. Data as of [snapshot date].

## Field Notes

- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run screen --strategy livermore yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
