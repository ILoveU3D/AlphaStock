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
version: 19
updated_at: 2026-09-09T20:03:27
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
- [2026-09-07 00:02] (ai) git workflow lesson 2026-09-06: NEVER push origin main directly — repo has PR-required branch protection and the stored credential silently bypasses it; always create a feature branch and push ONLY the branch; gh CLI is not installed; the human opens/merges PRs on GitHub themselves
- [2026-09-08 12:12] (ai) fetch stdout 全缓冲：后台运行全程零输出直到 exit 才 flush（09-08 上午误判卡死而杀掉）；进度探针 = data/snapshots/<date>/ 文件清单增长（quotes→financials→kline→master→manifest）；重启 fetch 会 reuse 当日已完成文件，上午被杀的部分下午续跑 678s 成功。修正 09-08 早间 single-stock-analysis 的'fetch 卡死'判断
- [2026-09-08 22:13] (ai) Eastmoney datacenter 铁律: 字符串过滤值须双引号如 (SECURITY_CODE=688795), 单引号部分报表触发 ANTLR 错误; RPTA_WEB_GPHG 回购报表不能带 sortColumns; 不可过滤字段会让整个 filter 被静默忽略返回全表, 须校验返回行数; 已验证事件报表: 解禁=RPT_LIFT_STAGE(TOTAL_RATIO 小数占比), 减持=RPT_SHARE_HOLDER_INCREASE, 回购=RPTA_WEB_GPHG, 定增=RPT_SEO_DETAIL, 预告=RPT_PUBLIC_OP_NEWPREDICT, 披露预约=RPT_PUBLIC_BS_APPOIN
- [2026-09-09 00:51] (ai) intel radar P1 live check (2026-09-09): 655 events / 202 A stocks, zero source failures; DC filter quirk — dates MUST be single-quoted (double quotes -> 'filter字段中日期参数格式错误'), strings/booleans double-quoted (IS_LATEST='T' -> ANTLR InputMismatchException); success=false + code 9201 '返回数据为空' = valid empty window (e.g. appointment forward windows stay empty until late Sept), not a source failure
- [2026-09-09 02:11] (ai) intel P2 live check (2026-09-09): intel X verified on 688795 (Moore Threads - the stock that motivated the system: 12-07 unlock 39.6% of shares flagged 3 months ahead), 000001 (snapshot-outside stock: batch tables are full-market so events/eq still computed, radar row correctly declared missing), and ask red-flag path on 603162 (68.1% 30d unlock -> verdict suffix [intel red flag]); np-listapi success envelope is code==1 (not 0); reportapi ratingChange 3=maintain observed with rating==last_rating, 1=downgrade 2=upgrade per EM convention; indvAimPriceT/L target price usually EMPTY for A-shares - render dash, never fabricate; mTypeAndCode prefix == Match.market_id (1=SH, 0=SZ+BJ); SB smartbox JSONDecodeError seen once (rate limit?) - harmless when snapshot resolves first
- [2026-09-09 11:57] (ai) A股debt_ratio在master.csv全NaN(a_financials无负债字段,a_balance仅应收存货;HK来自F10/US来自SEC)——任何含debt_ratio闸门的策略对A股结构性失明:官方screen报0只时先怀疑此缺口,降级为手动预筛(roe/rev/动量三闸门+手写debt核验),并在note中标注负债率未验证
- [2026-09-09 20:03] (ai) 2026-09-09/10: searchapi.eastmoney.com suggest endpoint returned non-JSON (JSONDecodeError) on every A-share name resolution during holding review - non-blocking, fallback resolution succeeded; if name resolution ever fully fails, check SB endpoint health first
