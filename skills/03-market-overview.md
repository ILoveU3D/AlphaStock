---
id: market-overview
title: Market Overview
order: 3
triggers:
  - 现在港股有什么机会
  - What looks attractive in market X now
  - 市场概览
commands:
  - overview
version: 3
updated_at: 2026-09-01T17:59:36
---

# Playbook

1. Run: `python -m value_genie overview --markets A,HK --top 10`
   (omit --markets for all three).
2. Per market you get: candidate count, median PE/PB/revenue growth,
   breadth (% of candidates above their 52-week midpoint), top sectors
   among the top-50 names, and the top-10 table.
3. Answer pattern: start with the market's valuation level (medians) and
   breadth, then name 2-3 standout stocks from the top table with their
   one-line thesis (cheap + growing + profitable).
4. Snapshot age matters for overviews — quote the snapshot date and run
   the data-ops skill if it is stale.

## Cautions

- The overview ranks only the ~200 candidates per market that passed
  the funnel gates; it is a curated shortlist, not the raw universe.

## Field Notes
- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run overview yourself and overlay policy/geopolitics/market/sentiment checks on the output before naming opportunities; never just hand the user a script to run.
