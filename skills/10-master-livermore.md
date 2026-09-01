---
id: master-livermore
title: Master - Jesse Livermore (Trend + Discipline + Momentum)
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
version: 3
updated_at: 2026-09-01T17:59:43
---

# Playbook

Answer "利弗莫尔会怎么看X" with the Jesse Livermore lens: trend
trading, price discipline, and the iron rule of cutting losses.

## Livermore's Framework

1. **趋势是你的朋友** (The trend is your friend): Only trade in
   the direction of the market. The `livermore` strategy gates on
   ret_60d ≥ 0 — if the stock isn't going up, it's not a buy.
   Momentum weight is 0.60, the dominant factor.

2. **量价配合 (Volume-price confirmation)**: Active stocks with
   high volatility (pctl ≥50) are preferred — they have liquidity
   and participants. Dead stocks with low volatility are avoided.

3. **止损纪律 (Cut losses ruthlessly)**: "The big money is not
   in the buying and selling, but in the waiting." But when the
   trend breaks, exit immediately. Risk flags about drawdown
   should be reported as exit signals, not ignored.

4. **关键价位 (Pivotal points)**: Stocks breaking out of bases
   on volume are the classic Livermore setup. pos_52w near 100
   (near 52-week highs) is the breakout zone.

5. **不预测，只跟随** (Don't predict, follow): Livermore didn't
   forecast — he reacted. Value and cash flow matter little (weight
   0); the question is whether the tape confirms the move.

## Workflow

1. Run the Livermore screen for trend candidates:
   ```
   python -m value_genie screen --strategy livermore --markets A --top 20
   ```

2. For a specific stock:
   ```
   python -m value_genie ask <name> --evidence
   ```

3. In your answer, cite:
   - ret_60d (is the short-term trend up?)
   - pos_52w (is it near breakout highs?)
   - volatility percentile (is it active enough?)
   - drawdown_52w (how far from highs — risk context)
   - risk_flags as exit signals, not softeners

## Answer Template

> [Verdict]. 3-month return X% [trend up / flat / down]. Position at
> Yth percentile of 52-week range — [breakout zone / mid-range / near
> lows]. Volatility at Zth percentile ([active / quiet]). [Risk flags
> as exit discipline notes]. Data as of [date].

## Field Notes
- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run screen --strategy livermore yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
