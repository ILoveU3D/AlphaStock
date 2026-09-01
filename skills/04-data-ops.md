---
id: data-ops
title: Data Operations
order: 4
triggers:
  - 数据新鲜吗
  - update the data
  - why is fetching broken
commands:
  - doctor
  - fetch
version: 4
updated_at: 2026-09-01T20:07:04
---

# Playbook

Run `doctor` BEFORE answering price-sensitive questions when the last
known snapshot is older than one trading day:

    python -m value_genie doctor

- All PASS → proceed; data is fresh enough.
- WARN on snapshot age or kline lag → tell the human data may be stale,
  offer to refresh, and prefer live-quote commands (`ask`) meanwhile.
- FAIL (no snapshots / ancient data) → run fetch before answering:
  `python -m value_genie fetch` (A+HK+US, ~10 min, incremental).

## Source failure playbook (learned the hard way)

- Eastmoney push2 rate-limits: the client rotates mirror hosts
  (push2delay first) with cooldowns; partial quote pages are kept with
  a warning — check `manifest.json` `failures` for what is missing.
- Tencent klines: legacy fqkline/get returns HTTP 501; the client tries
  newfqkline/get and the proxy.finance.qq.com mirror automatically.
- US fundamentals come from SEC EDGAR frames (annual/quarterly, weeks
  of lag). If US financials are missing entirely, the pipeline SKIPS
  the US market rather than ranking garbage — say so, do not improvise.
- Long fetches can be killed mid-run; re-running resumes and reuses
  everything already saved to today's snapshot directory.

## Field Notes
- [2026-09-01 01:56] (ai) smartbox suggest endpoint returned non-JSON (JSONDecodeError) during 2026-09-01 smoke test; snapshot name search fallback resolved all names
- [2026-09-01 17:59] (ai) Env: libs/ vendors cp314 wheels for system Python 3.14; .venv is an empty shell (no pandas) — run with PYTHONPATH=libs, never trust .venv/Scripts/python.exe
- [2026-09-01 20:07] (ai) PDD present in us_quotes.csv but absent from 20260901 master.csv (SEC financials likely failed/skipped at build) - ask resolves it via fallback with live quote, but screen/master strategies cannot see it; re-run fetch or audit SEC coverage for mega-caps after any screen misses a famous name
