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
version: 12
updated_at: 2026-09-04T18:37:58
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
- [2026-09-01 22:21] (ai) Sandbox file-sync bug: Edit tool can report success while the change is lost on disk - always re-verify edits with an independent Grep/Read before committing
- [2026-09-01 22:55] (ai) same-day reuse can serve stale-schema hk_f10.csv/us_financials.csv (no ocf column) from runs before the cashflow feature; buffett screen then returns 0 stocks silently — move stale files to a backup dir outside snapshots/ and re-run fetch to restore ocf_yield coverage (A 100%/US 98%/HK ~61%, interim reports often lack NETCASH_OPERATE)
- [2026-09-02 11:52] (ai) 2026-09-02 用户指令：新鲜度契约须按小时粒度计量而非按天——隔日快照（如 doctor 显示 1 day）不得视为新鲜/PASS；价格敏感回答前先报告快照的小时年龄（含 US klines 的滞后天数），并主动建议刷新快照
- [2026-09-02 12:15] (ai) fetch 全量刷新 20260902 实测约 15.5 分钟（930.6s）：US SEC financials 是最慢一步约 10 分钟，其次三市场行情约 5 分钟，K线/F10 从前一日快照复用——按小时更新指令执行前先预估此成本
- [2026-09-03 10:43] (ai) host python has no pandas: set PYTHONPATH to repo libs/ dir before any python -m value_genie command, else ModuleNotFoundError on import pandas
- [2026-09-04 18:37] (ai) US class shares live under 3 symbol forms (SEC hyphen BRK-B / EM underscore BRK_B / Tencent dot usBRK.B.N); normalize_us_ticker + tx dot-variants handle all, kline needs the dot form on Tencent
- [2026-09-04 18:37] (ai) PDD-style gross_margin gap: SEC GrossProfit tag discontinued after CY2022; derive from (Revenue - CostOfRevenue) in derive_us_metrics, and companyconcept per-stock fallback fills NaN derived columns in batch rows without overwriting
- [2026-09-04 18:37] (ai) Watchlist pipeline: user holdings excluded by funnel gates (e.g. loss-makers fail pe>0) or outside EM_FS universe (ETFs like 588060, 5-prefix = Shanghai funds) still get quotes+kline+financials via watchlist.csv; quote fallback is Tencent, US financials fallback is SEC companyconcept
