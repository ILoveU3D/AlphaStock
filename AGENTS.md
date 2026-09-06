# AGENTS.md — Value Genie for AI Agents

You are operating **Value Genie**, a value-investment research toolkit
covering A-share, Hong Kong and US equities. This file tells you what
the toolkit can do, when to use what, and how to leave it smarter than
you found it.

## What this repo is

- `python -m value_genie fetch` builds a dated snapshot: full-market
  quotes + financials (Eastmoney / SEC EDGAR), funnel to ~200
  candidates per market, deep klines + HK F10, scored `master.csv`.
- **Watchlist redundancy**: user holdings that the funnel excludes
  (loss-makers, out-of-universe ETFs) still get quotes + klines +
  financials + pillar scores via per-source fallbacks (Tencent quotes,
  SEC companyconcept, A-share single-stock filters) into
  `watchlist.csv`; `holding list` / `recommend` read it as fallback
  when a holding is absent from `master.csv`.
- `python -m value_genie trade ...` manages the AI's own virtual
  portfolio (multi-season paper trading): CITIC/ZA-Bank fee models,
  T+1/T+2 settlement, board-lot checks, multi-currency cash with FX
  spread, daily NAV marking, withdrawal tracking and a review journal.
  Seasons live in git-tracked `trading/seasons/`; lessons accumulate in
  the `trading` skill Field Notes.
- Analysis commands read the latest snapshot (and live quotes where
  noted) — no LLM runs inside the toolkit; you write the prose.
- There is **no human UI**: the CLI is the only entry point and AI
  agents are the only operators. `README.md` describes the system
  (architecture / methodology); this file is your operating manual.

## Freshness contract (code-enforced)

- `ask`, `compare`, `overview`, `recommend`, `holding list`, and
  `trade buy/sell/fx/cash/nav/journal/status/dashboard` run a
  **freshness gate** before any output. The gate calls
  `doctor.run_checks()` internally:
  - **FAIL** (no snapshot / ancient data >7 days) → command prints
    `[FRESHNESS BLOCKED]` to stderr and exits with code 1. No output.
  - **WARN** (snapshot older than 24 hours, but usable) → command
    prints `[FRESHNESS WARN]` to stderr and proceeds. State the
    staleness (hours + kline lag) in your answer.
  - **PASS** (snapshot <24h old) → silent, proceed normally.
- Snapshot age is measured in **hours** (manifest mtime), not days —
  a next-day snapshot is already stale; recommend `fetch` when WARN.
- `--no-check` skips the gate (for automated pipelines / testing only).
- **Agent house rule (user-mandated 2026-09-03)**: every conversation
  starts by checking snapshot age; if older than **1 hour**, run
  `python -m value_genie fetch` first and answer from the new snapshot.
  The 24h/7d gates above are CLI defaults — the agent standard is
  1 hour. Never analyze on stale data without fetching.
- `ask` always pulls the LIVE quote for price/PE/PB; fundamentals and
  percentiles come from the latest snapshot. `recommend` /
  `holding list` price holdings live with a snapshot-price fallback.
- Never present snapshot-day numbers as "current" — cite the
  data-as-of line the commands print.

## Machine-readable output (`--json`)

- Every data command accepts `--json`: `ask`, `screen`, `compare`,
  `overview`, `recommend`, `holding list`, `doctor`.
- With `--json`, stdout is **pure JSON** — full float precision,
  NaN→null, no banner lines, no `wrote ...` chatter. `screen --json`
  also skips the CSV/Markdown side-effect files. Exit codes and the
  freshness gate are unchanged (`doctor --json` still exits 1 on FAIL).
- Console tables remain the default and are fine for composing prose;
  switch to `--json` when you must cite exact numbers (gate thresholds
  like PE×PB≤22.5, weights, P&L) or re-parse output programmatically.
  `ask X --json` is the canonical machine form of a single-stock view.

## Users, styles and holdings (per-user state)

Users live in `users/<id>.json` (top-level git-tracked dir, one file
per user; human-readable, CLI-maintained, atomic writes). A user
carries:

- **style**: six-pillar weights + optional hard gates (registry DSL:
  `>=`, `<=`, `pctl>=`, `pctl<=`) + preferred horizon. Styles are
  auto-registered as `kind="user"` strategies at CLI startup, so
  `screen --strategy <user_id>`, `strategy list` and `--horizon`
  combination all work unchanged.
- **holdings**: full positions (market/code in master.csv form, qty,
  per-share cost, currency, opened date).

Commands: `user create|list|show|set-style` (style can start from an
existing strategy via `--base buffett`), `holding add|update|remove|
list` (the stock argument goes through the normal resolve chain — any
name/code/ticker form works), and `recommend --user <id>` (freshness-
gated): screens the latest snapshot under the user's style, **excludes
stocks already held**, and prints a holdings health report (live P&L,
position weights in CNY via manifest FX — gaps stated, US positions
excluded when no USD rate, concentration observations verbatim).

## Routing table

| The human asks | Skill | Command |
|---|---|---|
| "你怎么看待X / what do you think of X" | single-stock-analysis | `python -m value_genie ask X` |
| "...but why / 证据" | single-stock-analysis | `python -m value_genie ask X --evidence` |
| "X和Y哪个好 / X vs Y" | compare-stocks | `python -m value_genie compare X Y` |
| "今天给我推荐股票（按我的风格、结合我的持仓）" | user-recommend | `python -m value_genie recommend --user me` |
| "设置/修改我的投资风格" | user-profile | `python -m value_genie user set-style me --base buffett --weight value=0.3` |
| "录入/修改/查看我的持仓" | user-portfolio | `python -m value_genie holding add|update|remove|list` |
| "审视我的持仓 / 深度分析持仓" | holding-deep-review | `holding list` 先看体检，再 `ask X --evidence` per holding + `screen --strategy <master>` (business model, moat, culture, earn/lose paths, two master frameworks) |
| "现在港股有什么机会 / what's attractive now" | market-overview | `python -m value_genie overview --markets HK` |
| "数据新鲜吗 / is the data current" | data-ops | `python -m value_genie doctor` |
| "巴菲特会怎么看X" | master-buffett | `python -m value_genie screen --strategy buffett` + `ask X --evidence` |
| "芒格会怎么看X / 反过来想" | master-munger | `python -m value_genie screen --strategy munger` + `ask X --evidence` |
| "格雷厄姆会怎么看X / 市场先生" | master-graham | `python -m value_genie screen --strategy graham` + `ask X --evidence` |
| "利弗莫尔会怎么看X / 趋势" | master-livermore | `python -m value_genie screen --strategy livermore` + `ask X --evidence` |
| "段永平会怎么选X" | master-duan | `python -m value_genie screen --strategy duan` + `ask X --evidence` |
| "孙宇晨会怎么看X / 热点股" | master-sheng | `python -m value_genie screen --strategy sheng` + `ask X --evidence` |
| Macro / gold / geopolitics | macro-themes | framework + `overview` / `ask --evidence` |
| "你的虚拟盘怎么样 / 你的资产情况" | trading | `python -m value_genie trade status` |
| "虚拟盘买入/卖出 X" | trading | `python -m value_genie trade buy/sell <season> X --qty N --note 理由` |
| "复盘虚拟盘 / 记教训" | trading | `python -m value_genie trade journal <season> --text ...` + `skill note trading "..."` |
| "看看你的战绩 / 更新看板" | trading | `python -m value_genie trade dashboard <season>` (writes `trading/dashboards/<id>.md`, commit it) |
| "短期内最推荐/最被低估的股票" | horizon-framework | `python -m value_genie screen --horizon short` |
| "超短线/短线有什么机会" | horizon-framework | `python -m value_genie screen --horizon ultrashort`（必须附短炒警示） |
| "X适合中长期持有吗" | horizon-framework | `python -m value_genie ask X`（四周期剖面）+ 14 号 playbook 质性层 |
| Philosophy / how to value | investment-philosophy | house voice for every answer |

## Investment masters

Six built-in master strategies, ordered by fame (this ordering is
code-enforced via the strategy registry's `order` field and mirrored
by the skill filenames 07-12):

| # | Master | id | Core focus | Key gates |
|---|---|---|---|---|
| 1 | Buffett | `buffett` | Franchise + owner earnings (evolved past cigar-butts) | ROE≥15%, 毛利率≥40%, 负债率≤60%, OCF yield≥5%, FCF yield≥4%, 借钱分红否决 |
| 2 | Munger | `munger` | Invert + latticework; wonderful at fair price | ROE≥20%, 毛利率≥40%, 负债率≤50%, 借钱分红否决 |
| 3 | Graham | `graham` | Margin of safety as arithmetic | PE×PB≤22.5 (派生列), 负债率≤50%, ROE≥10%, 借钱分红否决 |
| 4 | Livermore | `livermore` | Pivotal points + risk discipline; pure price | ret_60d≥0, 波动率市场内前50%, pos_52w≥60 |
| 5 | Duan Yongping | `duan` | Business model first, no stop-losses | ROE≥20%, 毛利率≥40%, 波动率市场内后40%（pctl≤60）, 借钱分红否决 |
| 6 | Justin Sun | `sheng` | Attention economics + narrative momentum | ret_60d≥0, 波动率市场内前40%（pctl≥60） |

`python -m value_genie strategy list` shows all strategies (presets +
masters). `screen --strategy <id>` applies the master's gates and
weights. Each master has a skill playbook in `skills/` — read it
before answering in that voice.

Playbooks live in `skills/` — read the relevant one before answering.
`python -m value_genie skill list` indexes them.

## Holding-period dimension

Four horizons (registry-backed, `python -m value_genie horizon list`):
ultrashort (1-10 交易日, ret_5d+ret_20d), short (10日-3月,
ret_20d+ret_60d), mid (3月-3年, 估值修复+业绩兑现), long (3年+,
商业模式+现金流). `screen --horizon H` screens under the horizon;
`--strategy X --horizon Y` keeps the master's weights/gates and swaps
only the momentum window; `ask X` prints a four-horizon suitability
profile. The value DNA of this toolkit: mid/long are the promoted
horizons; ultrashort/short answers must carry the caution line and
position-sizing discipline.

## Answer shape (hard rules)

1. Verdict first, one sentence. Then key numbers with units and the
   data-as-of line. Evidence tables only when asked.
2. Percentiles are within the stock's own market universe; say "12th
   percentile of the HK gated universe", not "12th percentile globally".
3. Report risk flags verbatim as observations; never soften them.
4. If resolution, data or coverage failed, say exactly what is missing
   — do not improvise numbers.

## Self-refinement protocol (leave the toolkit smarter)

After answering, if you hit a quirk or found a better procedure
(resolution trick, source failure workaround, ambiguity in a skill),
record it in one concrete line:

    python -m value_genie skill note single-stock-analysis "smartbox resolves names missing from snapshot after delistings"

Notes append to the skill's Field Notes; every future agent inherits
them. Body/trigger rewrites are the only human-supervised channel,
executed via `skill edit` on the CLI by the user's agent. Agents
never rewrite bodies on their own initiative — append-only keeps the
system trustworthy.

## Environment

- Python 3.10+; pandas + requests only, installed in the **global
  Python** (user-maintained). **Never vendor packages into the repo**
  (no `libs/` folder — user-mandated policy): if dependencies are
  missing, stop and ask the user to install them.
- Tests: `python -B -m pytest tests -q` (each file standalone).
- Data lives in `data/snapshots/YYYYMMDD/`; never edit snapshot files.
  `data/` as a whole is **regenerable run-time state — safe to wipe
  daily** (user-mandated policy; `fetch` rebuilds it). Per-user
  profiles live in the top-level git-tracked `users/` dir — modify
  them only through the `user` / `holding` CLI commands, never by
  hand.
