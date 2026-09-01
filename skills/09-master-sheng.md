---
id: master-sheng
title: Master - Justin Sun (Hot-Spot Sensitive + Momentum Follower)
order: 9
triggers:
  - 孙宇晨会怎么看
  - 热点股
  - 风口
  - 注意力经济
  - 孙宇晨视角
commands:
  - screen --strategy sheng
  - ask --evidence
version: 2
updated_at: 2026-09-02T00:55:05
---

# Playbook

Answer "孙宇晨会怎么看X" with the Justin Sun lens: attention
economics, hot-spot sensitivity, and momentum following.

## Sun's Framework

1. **注意力就是生产力** (Attention is productivity): Stocks with
   rising momentum (ret_60d > 0) are in the spotlight. Capital
   flows where attention goes. The `sheng` strategy gates on
   ret_60d ≥ 0 — no uptrend, no interest.

2. **热点敏感 (Hot-spot sensitive)**: Growth is the second filter.
   Revenue and profit growth capture whether the spotlight is
   justified by fundamentals or pure speculation. Weight growth
   at 0.35.

3. **动量跟随 (Momentum following)**: The core signal is momentum
   (weight 0.45). 3-month return captures the active trend; if
   the stock isn't moving up, don't force it.

4. **快速进出 (Fast in, fast out)**: Unlike Buffett's hold-forever,
   Sun's style is tactical. Valuation and safety matter little
   (weight 0.05 each) — the question is whether the trend is alive.

## Workflow

1. Run the Sun screen for momentum + growth candidates:
   ```
   python -m value_genie screen --strategy sheng --markets A --top 20
   ```

2. For a specific stock:
   ```
   python -m value_genie ask <name> --evidence
   ```

3. In your answer, cite:
   - ret_60d and ret_250d (is the trend alive?)
   - rev_yoy and profit_yoy (is growth real or speculative?)
   - momentum_score (how hot vs the market?)
   - risk_flags (especially volatility and drawdown)

## Answer Template

> [Verdict]. 3-month return X%, 12-month return Y% — [trend alive /
> fading]. Revenue growth Z% [fundamentals / speculation]. Momentum
> at Nth percentile of [market] universe. [Risk flags]. Data as of
> [date].

## Field Notes
- [2026-09-02 00:55] (ai) User mandate 2026-09-01: run screen --strategy sheng yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
