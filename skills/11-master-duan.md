---
id: master-duan
title: Master - Duan Yongping (Business Model First + Calm Mind)
order: 11
triggers:
  - 段永平会怎么选
  - 平常心
  - 本分
  - 不懂不做
  - 段永平视角
commands:
  - screen --strategy duan
  - ask --evidence
version: 2
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "段永平会怎么选X" with the Duan Yongping lens. The essence is
not "quality stocks" — it is a specific epistemology: if you truly
understand a business, price volatility stops being information, and
stop-losses become unnecessary.

## Duan's Framework

1. **不止损 — and why that is not recklessness** (his most
   misunderstood position): "如果你需要止损，说明你买的时候就不懂。"
   The discipline happens *before* entry — position size is set so
   that a 50% drawdown on a fully-understood business is tolerable.
   A stop-loss on a stock you understand converts your temporary
   informational advantage into a donation to Mr. Market. (The trade:
   this only works with real understanding. The screen's gates are
   the entry discipline; the AI must ask whether the *business* would
   be bought whole at this price.)

2. **商业模式优先 (business model before everything)**: the first
   question is "这门生意十年后会是什么样？" — 网易 in 2001 (cash per
   share near the share price), Apple in 2011-13 (ecosystem moat,
   bought while the market priced Steve Jobs' death as terminal),
   茅台 (brand + pricing power that survives management mistakes).
   The `gross_margin ≥ 40` gate is the pricing-power proxy — a
   business that can't hold margin doesn't have a model worth holding
   ten years.

3. **平常心 is an identity, not a technique**: hence the deliberately
   *loose* volatility gate (pctl ≤ 60 — calm is a byproduct, not a
   filter). He watched Apple fall 40%+ on his position without
   acting, because the business hadn't changed. Volatility is the
   market's mood; the moat is the company's.

4. **做对的事情，把事情做对**: first pick the right business (never
   frauds, never things outside understanding), then let time do the
   compounding. His concentration — 3-4 positions ever — is a
   *consequence* of how few businesses pass question 2, not risk
   appetite.

5. **Cash conversion as honesty check**: cash_conversion ≥100%
   (OCF ≥ net income) — profits that exist only as receivables are
   management's opinion, not the business's fact.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy duan --top 20
   ```
2. Apply the ten-year question to survivors; cut anything whose
   answer depends on a forecast (policy support, cycle timing, hype).
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict]. Business model: [one sentence on what this is and why it
> exists in ten years]. Pricing power: gross margin X%, ROE Y% —
> [real / rented]. Calm: volatility at Zth percentile ([tolerable /
> casino]). Honesty: cash conversion W%. Would he buy the whole
> company at this price? [yes / no / can't tell]. [Risk flags
> verbatim]. Data as of [snapshot date].

## Field Notes

- [2026-09-02 00:55] (ai) User mandate 2026-09-01: run screen --strategy duan yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
