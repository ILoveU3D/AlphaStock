---
id: single-stock-analysis
title: Single Stock Analysis
order: 1
triggers:
  - 你怎么看待X
  - What do you think of X
  - X值得买吗
  - Is X a buy
commands:
  - ask
version: 10
updated_at: 2026-09-06T23:18:01
---

# Playbook

Answer "what do you think of X" with a verdict first, evidence later.

1. Resolve the name (Chinese, code or ticker all work):
   `python -m value_genie ask 茶百道`
   The command prints the resolved label plus close alternative matches —
   if the resolution looks wrong, retry with a more specific name.
2. Read the brief output: verdict band, live price, three key numbers
   (PE percentile, revenue growth, ROE), a risk-flag count, and the
   four-horizon profile (超短线/短线/中线/长线 score + percentile per
   horizon).
3. Write the answer: lead with the verdict in one sentence, then the key
   numbers. State the data-as-of line verbatim. Do NOT dump the full
   metric table unless asked.
4. When the human asks "why" / "证据" / "reasons", run:
   `python -m value_genie ask 茶百道 --evidence`
   and walk through the metric/percentile table, pillar scores and risk
   flags in plain language.
5. For machine-readable consumption use `--json`.
6. When the question is horizon-scoped ("适合长期持有吗" /
   "短期怎么看"), use `ask X --horizon mid|long|short|ultrashort` for a
   single-horizon view, and follow skills/14-horizon-framework.md for
   the qualitative overlay.

## Interpretation

- Verdict bands (blended value/growth/quality/safety percentile vs the
  market's gated universe): outstanding >= 85, attractive >= 70,
  reasonable >= 40, unattractive >= 20, poor below that.
- "PE at 12th pctile" means cheaper than 88% of the comparable universe.
- Risk flags are hard observations (leverage > 70%, contracting revenue
  or profit, drawdown beyond -40%, high volatility), not opinions.
- The horizon profile is descriptive (no screening gates): it answers
  "at which holding period does this stock rank strongest", not "buy
  now". Weakest horizon is as informative as strongest — quote both
  when the question spans periods.

## Cautions

- If output says "live quote unavailable", prices come from the last
  snapshot — say so explicitly.
- New listings may have no kline history; momentum metrics show as "-".
- After answering, if you learned something reusable (a resolution
  quirk, a data gap workaround), append a field note:
  `python -m value_genie skill note single-stock-analysis "lesson"`

## Field Notes
- [2026-09-01 01:56] (ai) smoke test note: verified against 20260901 snapshot
- [2026-09-01 23:16] (ai) metric-table percentiles are oriented goodness-ranks (higher=better, code: percentile(lower_is_better)); skill body example 'PE 12th pctile = cheaper than 88%' is inverted vs code — verified via value pillar = mean(PE/PB/P_S pctiles) on NVDA/PDD/BRK
- [2026-09-01 23:16] (ai) resolution quirk: '伯克希尔' resolves first to leveraged HK ETF 07777; use full name '伯克希尔哈撒韦B' for BRK.B — BRK also has no SEC fundamentals in snapshot so verdict rests on value pillar only (PE/PB)
- [2026-09-02 01:00] (ai) peer frames rebuilt from quotes CSVs carry no kline factors; build_peer_set now backfills from the kline cache — before 20260902 ask always showed momentum/safety at the 100th pctile because the target ranked against itself
- [2026-09-02 01:06] (ai) HK peer frames carry F10 only for funnel candidates: ask growth/quality percentiles for HK names are self-ranked (100.0/50.0 signatures) - trust screen-internal comparisons and absolute PE/PB/dividend_yield instead
- [2026-09-03 17:44] (ai) US ticker code forms accept dot/underscore class suffixes (BRK.B -> Eastmoney BRK_B); snapshot us_quotes enrichment fills name+market_id even when smartbox returns non-JSON
- [2026-09-05 01:23] (ai) windfall-earnings trap: HK 00613 梧桐国际 ranked #1 by screen (PE 6.1) but 2026H1 revenue only 75.8M vs profit ~730M (net_margin 959%) - earnings are non-operating gains; check net_margin>100% or PE_dyn far below PE_static on tiny revenue before recommending
- [2026-09-06 23:18] (ai) fcf_yield = (年报经营现金流 - 资本开支)/市值 = DCF 一阶锚；capex_to_ocf = 再投资强度；borrowed_dividend=1 = 年报分红超过 FCF 且筹资净流入（A 股语境：保再融资资格的借钱分红，危险信号）
