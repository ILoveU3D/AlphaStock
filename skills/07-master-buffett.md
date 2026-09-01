---
id: master-buffett
title: Master - Warren Buffett (Cash Flow + Quality + Margin of Safety)
order: 7
triggers:
  - 巴菲特会怎么看
  - Buffett style
  - 现金流折算
  - 能力圈
  - 安全边际
  - 巴菲特视角
commands:
  - screen --strategy buffett
  - ask --evidence
version: 3
updated_at: 2026-09-01T17:59:40
---

# Playbook

Answer "巴菲特会怎么看X" with the Buffett lens: cash flow quality,
durable competitive advantage, and margin of safety.

## Buffett's Framework

1. **Cash flow is king**: A business is worth the discounted cash it
   will generate. Use `ocf_yield` (operating cash flow / market cap) as
   a static proxy for cash flow return. High `cash_conversion` (OCF /
   net income) proves earnings are real, not accruals.

2. **Durable competitive advantage (moat)**: Look for ROE consistently
   ≥15%, gross margin ≥40% (pricing power), and low leverage (debt
   ratio ≤60%). These gates are built into the `buffett` strategy.

3. **Margin of safety**: Price must be below intrinsic value. Use
   `value_score` and PE/PB percentiles as valuation anchors.

4. **Circle of competence**: If the business model is unclear or the
   industry is outside what you can understand, say so — Buffett
   passes rather than guesses.

## Workflow

1. Run the Buffett screen to find candidates that pass all gates:
   ```
   python -m value_genie screen --strategy buffett --markets A --top 20
   ```

2. For a specific stock, get the evidence:
   ```
   python -m value_genie ask <name> --evidence
   ```

3. In your answer, lead with the verdict, then cite:
   - ocf_yield and cash_conversion (is the cash real?)
   - ROE and gross_margin (is there a moat?)
   - PE/PB percentile vs market (is there a margin of safety?)
   - risk_flags (what could go wrong?)

## Answer Template

> [Verdict in one sentence]. OCF yield X% (cash conversion Y%), ROE
> Z%, gross margin W% — [moat / no moat]. Valuation at PE Nth
> percentile of the [market] universe is [cheap / fair / rich].
> [Risk flags as observations]. Data as of [snapshot date].

## Field Notes

_(AI-appended lessons go here. Humans promote good ones to the body.)_
- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run screen --strategy buffett yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
