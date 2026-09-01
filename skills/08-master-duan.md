---
id: master-duan
title: Master - Duan Yongping (Calm Mind + Quality First)
order: 8
triggers:
  - 段永平会怎么选
  - 平常心选股
  - 本分
  - 不懂不做
  - 段永平视角
commands:
  - screen --strategy duan
  - ask --evidence
version: 1
updated_at: 2026-09-01
---

# Playbook

Answer "段永平会怎么选X" with the Duan Yongping lens: calm mind,
quality first, and the discipline of "不懂不做" (don't invest in
what you don't understand).

## Duan's Framework

1. **买股票就是买公司** (Buying a stock is buying a company): Focus
   on business quality first. ROE ≥20% is the floor — if a company
   can't earn 20% on equity, it's not exceptional enough.

2. **平常心 (Calm mind)**: Don't chase volatility. Stocks with
   volatility in the lower half of the market (pctl ≤50) are
   preferred. High volatility often signals speculation, not value.

3. **不懂不做** (Don't do what you don't understand): If the business
   model isn't clear, pass. Duan held few positions for years —
   concentration comes from understanding, not from luck.

4. **本分 (Doing the right thing)**: Prefer companies with honest
   management and transparent reporting. Cash conversion ≥100%
   (OCF ≥ net income) signals the earnings are trustworthy.

## Workflow

1. Run the Duan screen for quality-first candidates:
   ```
   python -m value_genie screen --strategy duan --markets A --top 20
   ```

2. For a specific stock:
   ```
   python -m value_genie ask <name> --evidence
   ```

3. In your answer, cite:
   - ROE (is it ≥20%?)
   - volatility percentile (is it calm?)
   - cash_conversion (is the money real?)
   - gross_margin (is there pricing power?)

## Answer Template

> [Verdict]. ROE Z% (quality: [exceptional / good / mediocre]),
> volatility at Nth percentile ([calm / volatile]). Cash conversion
> X%. [Quality judgment]. Data as of [date].

## Field Notes
- [2026-09-02 00:55] (ai) User mandate 2026-09-01: run screen --strategy duan yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
