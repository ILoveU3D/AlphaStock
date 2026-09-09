---
id: holding-deep-review
title: Holding Deep Review (Business-First, Data-as-Evidence)
order: 13
triggers:
  - 审视我的持仓
  - 持仓深度分析
  - 该拿住还是卖
  - 结合大师视角分析
  - deep review my holdings
commands:
  - ask --evidence
  - screen --strategy <master>
version: 11
updated_at: 2026-09-09T16:12:31
---

# Playbook

Answer holding-review questions business-first, with data as evidence.
Created at explicit user request 2026-09-02: the user rejected
data-first answers ("不要直接 ask 数据然后一通分析") and asked for
master-grade depth on fundamentals.

## Mandate (user's requirements, binding)

1. Data is the evidence layer, never the answer layer. Run
   `ask <name> --evidence` per holding for the factual base
   (valuation percentiles, risk flags, data gaps) and cite numbers as
   footnote-style support, not as the argument itself.
2. Every holding MUST be covered on five dimensions:
   - 商业模式: how does it actually make money — one sentence clear
     enough to explain to a non-investor. Include what the company
     is really selling (e.g. Berkshire sells capital allocation,
     not insurance).
   - 护城河: name the mechanism (cost, network, brand, switching,
     license/system) AND where it is shallowest. No moat is uniform.
   - 企业文化与管理层: who allocates capital, what they optimize
     for, key-man risk, how they treat minority shareholders, and
     whether the culture survives the founder.
   - 赚钱路径: the bull case with a nameable reason (not a forecast),
     through the business lens.
   - 亏钱路径: the bear case, ranked by probability — Munger
     inversion: articulate how this business dies or gets repriced
     before arguing why it lives.
3. Answer in at least two masters' frameworks, chosen for fit with
   the business (BRK → Buffett/Munger; consumer-internet China →
   Duan; AI/tech → Munger/Duan/Livermore). Read the master playbook
   first; report which holdings pass/fail each master's screen gates
   and WHY (including data-gap failures, which must be labeled as
   data gaps, not economic verdicts).
4. Geopolitics/policy must be traced as a transmission chain
   (policy → business variable → P&L line → valuation), never
   name-dropped as a one-word risk factor.
5. Portfolio layer (mandatory): shared-risk-factor exposure across
   holdings (seemingly diversified books that lose to the same macro
   event), the behavioral test (could you hold each name through
   -50%? has it happened before?), and position size vs depth of
   understanding (Duan's standard: size matches understanding, not
   screen scores).
6. Honesty rules: state data gaps verbatim (e.g. BRK has no SEC
   fundamentals in the snapshot so the toolkit's verdict rests on
   PE/PB only; PDD's gross margin is missing from SEC frames so
   master screens cut it on data availability, not economics). No
   price targets. Say 不知道 explicitly when a dimension cannot be
   judged. Always state the data-as-of line.

## Workflow

1. Freshness gate runs automatically on ask/screen; state the
   data-as-of line in the answer.
2. Per holding: `python -m value_genie ask <name> --evidence`
   (factual base; resolution quirk: use 伯克希尔哈撒韦B for BRK.B).
3. Run `screen --strategy <master>` for the 2-3 masters that fit the
   holdings; report gate pass/fail per holding.
4. Write the five-dimension analysis per holding, then the portfolio
   layer. Verdict sentence first for each holding; metric tables only
   when asked.

## Field Notes
- [2026-09-02 04:30] (human) 用户要求原话大意：不喜欢"直接 ask 数据然后一通分析"；要结合投资大师们的风范谨慎回答；持仓分析必须覆盖基本面、商业模式、企业文化、后续赚钱还是亏钱；地缘因素要深入；请把要求写进 skills 做成新的功能倾向。
- [2026-09-03 11:41] (ai) holdings now persist per-user (data/users/<id>.json); run holding list <user> first for live P&L/weights/concentration facts, then ask X --evidence per holding
- [2026-09-03 17:44] (ai) master.csv stores pillar scores only (no composite_score) - compute it from pillar scores with user weights; quotes CSVs carry industry for holdings outside the master pool; A-share ETFs (5xxxxx) are SSE market_id 1, absent from a_quotes - set display name via holding update --name
- [2026-09-04 18:38] (ai) Holdings missing from master.csv (funnel-gated or out-of-universe like ETFs) are served by snapshot watchlist.csv with full pillar scores; holding list/health reads it as fallback, so cite watchlist rows for those names
- [2026-09-06 23:17] (ai) 四问测试 + DCF 三问（未来现金流从哪来/多少/什么折现率）+ borrowed_dividend 检查（年报分红超 FCF 且筹资净流入 = 借钱分红，一票否决）
- [2026-09-06 23:50] (ai) MANDATE 2026-09-06: every holding analysis must show per-holding master evaluation (gates + business model / culture / earn-lose paths prose); quantitative-only output is invalid
- [2026-09-06 23:53] (ai) Update 2026-09-06: master-evaluation mandate softened by user to standard-flow-not-enforced; position discipline added (Duan: enter only if -50% drawdown tolerable); Duan's principle — data is only ever a reason NOT to buy, the buy reason must be future cash flows from business model + culture
- [2026-09-07 10:47] (ai) master screens only cover the master.csv pool; watchlist holdings (e.g. PDD/NVDA/BRK_B outside the 200-candidate funnel) never appear in screen output - evaluate their gates manually from ask --evidence metrics and label the absence as pool coverage, not a gate rejection
- [2026-09-07 12:00] (ai) crash-day routine: diff last kline close vs live quote to detect limit moves (519.35 vs 415.48 = -20% STAR limit-down, 2026-09-07 Moore Threads), then web-search same-day news for the catalyst (unlock/earnings/policy) before writing any review prose - the catalyst reframes the whole holding review
- [2026-09-08 23:58] (ai) ETF holdings (e.g. 588060 科创50ETF): web-resolve tracking index + top-10 weights before writing review prose - hidden overlap with single-stock holdings and index-inclusion unlock traps (2026-09-08: 科创50 top-10 all semis; Dec Moore Threads 39.55% unlock doubles float -> index inclusion forces passive buying)
- [2026-09-09 16:12] (ai) 舆情强制参与铁律(2026-09-09用户确立): 持仓复盘/单股分析必须跑 intel X 获取舆情情报(解禁/减持/财报粉饰/公告/评级/新闻)，舆情红旗(如大股东减持)作为否决信号纳入仓位决策；只跑 ask --evidence 不跑 intel 的分析视为不完整，AI 不得遗漏
