---
id: compare-stocks
title: Compare Stocks
order: 2
triggers:
  - "X和Y哪个好"
  - "X vs Y"
  - "compare X and Y"
commands:
  - compare
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

1. Run with all names at once (2+ supported):
   `python -m value_genie compare 茶百道 古茗 奈雪的茶`
2. The table shows price, PE with peer percentile, revenue growth, ROE,
   blended composite percentile, verdict and risk count per name.
3. Structure the answer around the printed takeaways: which name is
   cheapest (lowest PE percentile), which grows fastest, which is
   safest — then add the blended rank as the tiebreaker.
4. Cross-market comparisons (A vs HK vs US) are valid: percentiles are
   computed within each market's own universe, so "12th pctile in HK"
   and "15th pctile in US" are comparable statements about relative
   cheapness.
5. If two names resolve to the same stock, drop the duplicate and say so.

## Cautions

- Percentiles need a snapshot; without one the command fails with
  "run fetch first" — run the data-ops skill first.

## Field Notes
