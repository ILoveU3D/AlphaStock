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
version: 2
updated_at: 2026-09-01T01:56:47
---

# Playbook

Answer "what do you think of X" with a verdict first, evidence later.

1. Resolve the name (Chinese, code or ticker all work):
   `python -m value_genie ask 茶百道`
   The command prints the resolved label plus close alternative matches —
   if the resolution looks wrong, retry with a more specific name.
2. Read the brief output: verdict band, live price, three key numbers
   (PE percentile, revenue growth, ROE) and a risk-flag count.
3. Write the answer: lead with the verdict in one sentence, then the key
   numbers. State the data-as-of line verbatim. Do NOT dump the full
   metric table unless asked.
4. When the human asks "why" / "证据" / "reasons", run:
   `python -m value_genie ask 茶百道 --evidence`
   and walk through the metric/percentile table, pillar scores and risk
   flags in plain language.
5. For machine-readable consumption use `--json`.

## Interpretation

- Verdict bands (blended value/growth/quality/safety percentile vs the
  market's gated universe): outstanding >= 85, attractive >= 70,
  reasonable >= 40, unattractive >= 20, poor below that.
- "PE at 12th pctile" means cheaper than 88% of the comparable universe.
- Risk flags are hard observations (leverage > 70%, contracting revenue
  or profit, drawdown beyond -40%, high volatility), not opinions.

## Cautions

- If output says "live quote unavailable", prices come from the last
  snapshot — say so explicitly.
- New listings may have no kline history; momentum metrics show as "-".
- After answering, if you learned something reusable (a resolution
  quirk, a data gap workaround), append a field note:
  `python -m value_genie skill note single-stock-analysis "lesson"`

## Field Notes
- [2026-09-01 01:56] (ai) smoke test note: verified against 20260901 snapshot
