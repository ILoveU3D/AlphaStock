---
id: master-buffett
title: Master - Warren Buffett (Franchise + Owner Earnings)
order: 7
triggers:
  - 巴菲特会怎么看
  - Buffett style
  - 现金流
  - 能力圈
  - 安全边际
  - 巴菲特视角
commands:
  - screen --strategy buffett
  - ask --evidence
version: 4
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "巴菲特会怎么看X" with the Buffett lens. Not the caricature of a
static value grandpa — the real man is an *evolver* whose edge compounded
across three distinct eras.

## The Real Buffett (three eras, one engine)

1. **1956-1972, Graham's apprentice**: cigar-butts, workouts, net-nets.
   Cheapness was the entire thesis. He made money but chafed at owning
   mediocre businesses.

2. **1972, See's Candies — the conversion**: paying 3x book for a candy
   company was heresy to Graham. See's taught him that an unregulated
   franchise with pricing power compounds *through* the owner. Charlie
   Munger pushed; the data convinced. From here: "It's far better to buy
   a wonderful company at a fair price than a fair company at a
   wonderful price."

3. **1967-onward, the float era**: the real engine most commentary
   misses. Insurance float is leverage at *negative* cost — Berkshire
   is not anti-leverage, it is anti-*expensive* leverage. Meanwhile a
   giant T-bill reservoir enforces discipline: he only swings at fat
   pitches because he can afford to wait years.

## Framework (what the screen encodes)

1. **Owner earnings, not accounting profit** (1986 letter: net income
   + D&A − maintenance capex). Proxies: `ocf_yield` (OCF/market cap,
   gate ≥5%) and `cash_conversion` (OCF/net income). Accounting
   earnings are an opinion; cash is a fact.

2. **Franchise quality** (the See's lesson): ROE ≥15%, gross margin
   ≥40% (pricing power), debt ratio ≤60%. High margins without pricing
   power get competed away.

3. **Margin of safety on the price paid** — but for a *wonderful*
   business "fair" is enough. Value weight 0.25, not 0.50 (that would
   be Graham).

4. **Circle of competence**: he passes on what he can't project ten
   years out. He missed all of tech's winners for 30 years and slept
   fine.

## Known gaps (state these honestly)

- **Moats erode**: he owned newspapers into their terminal decline and
  sold IBM at a loss. "Forever" applies to *wonderful* businesses only;
  he sells mistakes (airlines, Tesco, most of Kraft Heinz's pain).
  The screen cannot see moat durability — the AI must judge it.
- Old snapshots without `ocf_yield` skip that gate with a warning;
  say so, and require manual cash-flow verification before conviction.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy buffett --top 20
   ```
2. Overlay policy / geopolitics / market regime / sentiment on the top
   names; cut or downgrade with reasons stated.
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict in one sentence]. Owner earnings check: ocf_yield X%,
> cash conversion Y% — [cash is real / accrual-heavy]. Franchise check:
> ROE Z%, gross margin W% — [moat / no moat]. Price vs quality: PE
> Nth percentile of the [market] gated universe — [fair for the
> quality / no margin of safety]. Moat durability: [one sentence of
> human judgment]. [Risk flags verbatim]. Data as of [snapshot date].

## Field Notes

- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run screen --strategy buffett yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
