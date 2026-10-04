# AGENTS.md — Value Genie for AI Agents

You are operating **Value Genie**, a value-investment research toolkit
covering A-share, Hong Kong and US equities. This file tells you what
the toolkit can do, when to use what, and how to leave it smarter than
you found it.

## What this repo is

- `python -m value_genie fetch` builds a dated snapshot: full-market
  quotes + financials (Eastmoney / SEC EDGAR), dual-lane funnel to
  ~200 candidates per market (lane A 错杀: cheap on pe/pb/ps; lane B
  复利机器: roe/gm/debt quality gates with no cheapness gate, so
  premium compounders are admitted), deep klines + HK F10, scored
  `master.csv` carrying the three equal-weight cores
  (`core_business` / `core_culture` / `core_dcf` → `core_score`,
  absolute anchors — the ONLY ranking keys; pillar scores are
  veto/display context).
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
- `python -m value_genie tower ...` manages the **cognitive tower**
  (认知巴别塔): philosophy bricks distilled from conversations,
  masters and 105+ books, with DCF as the single axiom. Bricks live
  in the git-tracked `tower/` dir — see the Cognitive tower section
  for the mandatory lookup/absorb loop.
- Analysis commands read the latest snapshot (and live quotes where
  noted) — no LLM runs inside the toolkit; you write the prose.
- There is **no human UI**: the CLI is the only entry point and AI
  agents are the only operators. `README.md` describes the system
  (architecture / methodology); this file is your operating manual.

## Freshness contract (code-enforced)

- `ask`, `compare`, `overview`, `recommend`, `holding list`, and
  `trade buy/sell/fx/cash/nav/journal/status` run a
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
  `overview`, `recommend`, `holding list`, `doctor`, and every
  `tower` / `thesis` / `profile` subcommand.
- With `--json`, stdout is **pure JSON** — full float precision,
  NaN→null, no banner lines, no `wrote ...` chatter. `screen --json`
  also skips the CSV/Markdown side-effect files. Exit codes and the
  freshness gate are unchanged (`doctor --json` still exits 1 on FAIL).
- Console tables remain the default and are fine for composing prose;
  switch to `--json` when you must cite exact numbers (gate thresholds
  like PE×PB≤22.5, weights, P&L) or re-parse output programmatically.
  `ask X --json` is the canonical machine form of a single-stock view.

## Users, styles and holdings (per-user state)

Users live in `users/<id>.json` (top-level LOCAL-ONLY dir — gitignored
and never pushed to any remote, user mandate 2026-10-03; one file per
user, human-readable, CLI-maintained, atomic writes). The session
pointer `users/.session` records who the AI is talking to. A user
carries:

- **style**: six-pillar weights + optional hard gates (registry DSL:
  `>=`, `<=`, `pctl>=`, `pctl<=`) + preferred horizon. Styles are
  auto-registered as `kind="user"` strategies at CLI startup, so
  `screen --strategy <user_id>`, `strategy list` and `--horizon`
  combination all work unchanged.
- **holdings**: full positions (market/code in master.csv form, qty,
  per-share cost, currency, opened date).

Commands: `user create|list|show|set-style|login|logout|whoami`
(`create` auto-logs-in; `show`/`set-style` accept an optional id —
default is the session's current user; style can start from an
existing strategy via `--base buffett`), `holding add|update|remove|
list` (the stock argument goes through the normal resolve chain — any
name/code/ticker form works; the user id is optional and defaults to
the session user), and `recommend [--user <id>]` (freshness-
gated): screens the latest snapshot under the user's style, **excludes
stocks already held**, and prints a holdings health report (live P&L,
position weights in CNY via manifest FX — gaps stated, US positions
excluded when no USD rate, concentration observations verbatim).

**Multi-user house rule (2026-10-03):** before any personal operation
(holdings / recommend / set-style), run `user whoami` to confirm who
you are talking to; when the human states their identity, `user login
<id>` first. Asset boundary: shared North-Star value (code / skills /
tower / theses / trading seasons / docs) is pushed to the remote;
user territory (`users/`) and AI judgment (`profiles/`, `models/`)
never leave the machine.

## Routing table

| The human asks | Skill | Command |
|---|---|---|
| "你怎么看待X / what do you think of X" | single-stock-analysis | `python -m value_genie ask X` |
| "...but why / 证据" | single-stock-analysis | `python -m value_genie ask X --evidence` |
| "X和Y哪个好 / X vs Y" | compare-stocks | `python -m value_genie compare X Y` |
| "今天给我推荐股票（按我的风格、结合我的持仓）" | user-recommend | `python -m value_genie recommend`（缺省取 session 当前用户） |
| "推荐/最被低估/量化+大师最优" | fused-quant-master | `python -m value_genie masters-vote`（L1 宽池=量化只否决、AI 从全池选深评名单 + core_score 唯一排序）+ L2 红旗 + L3 三核深评与大师定性 + L4 融合裁决，per skills/18 — user mandate 2026-09-15: 融合，不分情况讨论；2026-09-29: 三核（商业模式/企业文化/DCF）为唯一排序键，量化只否决 AI 做选择 |
| "短线/超短线有什么机会" | fused-quant-master | `python -m value_genie masters-vote --horizon short|ultrashort`（D4 战术模式：floor=真生意 core_business≥50 + 周K结构上行 + 无否决，甜点区=60日高点回撤 5-15%，同一融合管道 + 纪律块；塔砖 weekly-trend-daily-pullback） |
| "把塔砖断言的机器注入候选池 / 管理产业论点" | fused-quant-master | `python -m value_genie masters-vote --thesis <id>` + `thesis list|show|add|amend|retire`（见 Thesis pools 节） |
| "读公司原文 / 蒸馏商业模式与文化" | fused-quant-master | `python -m value_genie profile fetch|show|assess|list|status`（见 Company profiles 节——蒸馏回写后文化核恢复打分，profiles/ 本地-only 永不推送） |
| "建财务模型 / DCF估值 / 可比公司" | fused-quant-master | `python -m value_genie model gather|write|show|lint|status X`（AI 手工建模工作台：gather 聚合素材→AI 写理解层〔飞轮/文化/reverse-DCF 三件套+世界叙事+自由维度〕→lint 合格线〔信息量≥财报〕；估值层 fetch|build|set|list；触发条件见 skills/19；DCF 钩平行 D3 进 core_dcf；models/ 本地-only 永不推送） |
| "设置/修改我的投资风格" | user-profile | `python -m value_genie user set-style me --base buffett --weight value=0.3` |
| "录入/修改/查看我的持仓" | user-portfolio | `python -m value_genie holding add|update|remove|list` |
| "审视我的持仓 / 深度分析持仓" | holding-deep-review | `holding list` 先看体检，再 `ask X --evidence` per holding + `screen --strategy <master>` (business model, moat, culture, earn/lose paths, two master frameworks) |
| "X的舆情/解禁/公告/研报/财报解读" | intel | `python -m value_genie intel X`（A 全板块；HK 公告+新闻，研报无源；US EDGAR 披露+新闻+一致评级；含解释层：财报速读/公告含义〔…〕/新闻热度/研报汇总，user mandate 2026-09-09） |
| "现在港股有什么机会 / what's attractive now" | market-overview | `python -m value_genie overview --markets HK` |
| "数据新鲜吗 / is the data current" | data-ops | `python -m value_genie doctor` |
| "巴菲特会怎么看X" | master-buffett | `python -m value_genie screen --strategy buffett` + `ask X --evidence` |
| "芒格会怎么看X / 反过来想" | master-munger | `python -m value_genie screen --strategy munger` + `ask X --evidence` |
| "格雷厄姆会怎么看X / 市场先生" | master-graham | `python -m value_genie screen --strategy graham` + `ask X --evidence` |
| "利弗莫尔会怎么看X / 趋势" | master-livermore | `python -m value_genie screen --strategy livermore` + `ask X --evidence` |
| "段永平会怎么选X" | master-duan | `python -m value_genie screen --strategy duan` + `ask X --evidence` |
| "孙宇晨会怎么看X / 热点股" | master-sheng | `python -m value_genie screen --strategy sheng` + `ask X --evidence` |
| "散户乙会怎么看X / 免费股票/成本收回" | master-sanhuyi | `python -m value_genie screen --strategy sanhuyi` + `ask X --evidence` |
| Macro / gold / geopolitics | macro-themes | framework + `overview` / `ask --evidence` |
| "你的虚拟盘怎么样 / 你的资产情况" | trading | `python -m value_genie trade status` |
| "虚拟盘买入/卖出 X" | trading | `python -m value_genie trade buy/sell <season> X --qty N --note 理由` |
| "复盘虚拟盘 / 记教训" | trading | `python -m value_genie trade journal <season> --text ...` + `skill note trading "..."` |
| "看看你的战绩 / 总结赛季" | trading | `python -m value_genie trade status/nav/journal --json` → AI 成文总结（无 dashboard，AI 即看板；赛季全员共享） |
| "短期内最推荐/最被低估的股票" | horizon-framework | `python -m value_genie screen --horizon short` |
| "超短线/短线有什么机会" | horizon-framework | `python -m value_genie screen --horizon ultrashort`（必须附短炒警示） |
| "X适合中长期持有吗" | horizon-framework | `python -m value_genie ask X`（四周期剖面）+ 14 号 playbook 质性层 |
| Philosophy / 处世 / 人生问题 / how to value | cognitive-tower | `python -m value_genie tower search <query>` 查塔作答（见 Cognitive tower 节家规） |
| "新手 / 导航 / 这是什么 / 带我去X / 参观" | navigation | 无专用命令——按 skills/20-navigation 渐进讲解（AI 即导览，一次只讲一层，无状态） |

## Cognitive tower (认知巴别塔)

The tower is the canonical home for philosophy — every idea worth
keeping becomes a **brick**: one `tower/<id>.md` file (git-tracked
top-level dir, never inside the cleanable `data/`) with a one-line
`statement`, a `source` (`book:` / `master:` / `conversation:` /
`ai`), a cognitive `status` and typed links (`derives-from` /
`refines` / `contradicts` / `applies-to` / `tension`). The single
axiom is `dcf-universal-law` — everything else traces to it,
tensions included (marked, never resolved by deletion). Statuses:
`axiom > mission > law > principle > hypothesis > observation >
refuted`; migrations require a reason and are archived as Field
Notes; `refuted` bricks are never deleted (errors are assets).

- Commands: `python -m value_genie tower list|show|add|note|link|
  set|search|stats|seed` — all `--json`-capable. Tower commands do
  **not** run the freshness gate: the tower depends on no market
  snapshot.
- `tower stats` prints the honest cognitive-altitude report (laws
  verified by conversation vs principles borrowed from books,
  growth rate, scar count).
- The tower is **not a skill**: skills are behavior manuals (how to
  answer), the tower is the knowledge store (what we know). The
  former 06-investment-philosophy skill was dissolved into it
  (2026-09-18) — its universal laws live on as tower bricks.

**House rules — 双向强制循环 (user-mandated 2026-09-18):**

1. **查塔义务** — before answering any decision-grade question
   (value trade-offs, career/life choices, investment philosophy),
   `tower search` the relevant bricks first; verdicts must reconcile
   with axiom first, laws second, principles third. Cite the bricks
   you leaned on.
2. **入塔义务** — any conversation insight worth keeping becomes a
   brick (`tower add`, then `tower note` for refinements); books are
   absorbed as `principle` bricks and promoted to `law` only after
   our own verification (`tower set --status law --reason "..."`).
3. Answers stay non-evasive: brick × current reality = concrete
   judgment; a conditional verdict must state its conditions, not
   hedge.

## Thesis pools (论点喂池)

Theses are the tower→L1 pipeline: a brick's assertion about a
money-printing machine (e.g. "memory is being repriced from cyclical
to compute-input") becomes a named, member-carrying pool that
`masters-vote --thesis <id>` injects into the L1 candidate universe.
They live in the git-tracked `tower/theses/` dir (one JSON per
thesis, CLI-maintained, atomic writes — never inside `data/`); a
thesis is a tower artifact, so it lives where its brick lineage lives
(merged 2026-09-30).

A thesis carries: `brick` (tower lineage — the falsification trail
that motivated it), `statement`, `reason`, `features` (the three
window traits: new/unpriced, needed by a tech/demographic cycle,
skill-attention arbitrage), `falsification` (explicit kill
conditions), `members` (market:code list), `industry_hints`
(discovery aid), and `status` (active/retired).

- Commands: `python -m value_genie thesis list|show|add|amend|retire|
  remove` — all `--json`-capable; `show --discover` scans the
  snapshot for industry-hint matches not yet members. Thesis
  commands do **not** run the freshness gate.
- `masters-vote --thesis <id>`: pool = funnel ∪ thesis members (the
  machine competes alongside the whole pool, never in a thesis-only
  silo). Members missing from master.csv get rebuilt from the gated
  peer universe with live kline / HK F10 backfill and full pillar
  scores; members blocked by universe gates are listed as `excluded`
  with the reason. Retired theses hard-block the vote.
- **Seat, not a vote**: injection only buys a seat at the L1 table —
  all 7-master gates, L2 veto flags and L3/L4 judgment apply
  unchanged. A thesis member with zero master votes is a legitimate
  outcome (the machine assertion is mine, the gates are theirs).
- **House rule**: every thesis must name its brick lineage and
  falsification set at creation; when a falsification condition
  fires, `thesis retire <id> --reason "..."` immediately — retired
  theses are never deleted (like `refuted` bricks, they are assets).
  Cap: `THESIS_MAX = 40` members per pool build.

## Company profiles (公司画像, 本地-only)

Profiles are the L3 read-store: raw company source text on one side,
the AI's distilled business-model / culture assessment on the other.
They close the D3 loop — the culture core in `core_score` is
veto-only until a distillation activates it.

- **Storage split (user mandate 2026-09-29)**: raw fetches live under
  `data/profiles/raw/<market>/<code>.json` (cleanable, regenerable);
  assessments live in the top-level `profiles/<market>/<code>.json`
  dir which is **gitignored LOCAL-ONLY — never pushed to any remote**.
  The schema is stable (source / raw_hash / scores / argument texts)
  so the store can later become a portable dataset.
- Commands: `python -m value_genie profile fetch|show|assess|list|
  status` — all `--json`-capable. Profile commands do **not** run the
  freshness gate. Sources: A = 东财 F10 机构概况；HK = 东财 HKF10
  公司概况；US = SEC submissions meta + stockanalysis 简介.
- The loop (per L3 deep-review candidate): `profile fetch X` →
  `profile show X` + `intel X` （读原文） → three-core argumentation →
  `profile assess X --business-score N --culture-score N ...` → the
  D3 hook re-activates `core_culture` on the next `masters-vote` /
  `ask` run (`core_gaps` marks `CULTURE_DISTILLED`).
- **Staleness**: the assessment pins the raw content hash; a
  refetched/changed raw marks it STALE and it drops out of scoring
  until re-distilled. `profile status` lists coverage + staleness.
- Never improvise a culture score from pillar data — no distillation
  means the culture core stays veto-only.

## Financial models (财务模型, 本地-only)

Models are the AI's cognitive dossiers, one per company (user mandate
2026-10-03): **AI models one company at a time — no batch pipeline;
scripts are the hands, never the modeler.** The dossier (`model.json`)
is the model's body: business flywheel / culture / reverse-DCF are the
machine-enforced three-piece minimum; world narratives (weight =
AI-estimated, `weight_basis` mandatory — a weight without its basis is
a placeholder) and freeform dimensions are open-ended. Quality bar:
information content >= the annual report's (`model lint`), else the
dossier is unqualified and stays out of scoring. Missing tools are
built as the campaign needs them; insights go straight into the tower
— modeling the whole market is how the quant tools, the tower and the
North-Star DCF get stronger.

- **Storage**: `models/<market>/<code>/` — `raw/` (gathered material:
  full listing-history statements, intel events, company profile text,
  peers; regenerable) / `model.json` (the AI-written dossier, THE
  asset) / history.json / assumptions.json / result.json (valuation
  layer). **gitignored LOCAL-ONLY — never pushed** (user mandate
  2026-10-02: the model is proprietary judgment).
- Commands: `python -m value_genie model gather|write|show|lint|status`
  (workbench) + `fetch|build|set|list` (valuation layer) — all
  `--json`-capable. Only `build` runs the freshness gate. `gather`
  aggregates raw material — full-history statements, annual-report
  texts (A: MD&A review + segment breakdown + core themes + sell-side
  consensus + exec bios; US: 10-K Item 1/7 slices; HK: PDF-only gap),
  disclosure full texts (A: cninfo annual-report + prospectus PDFs via
  pypdf — soft dependency, gap-declared when absent; HK/US gap),
  intel events, profile text, peers (pass `--peers` with AI-chosen
  comparables when the target is absent from master.csv); `write` records the
  understanding layer (`key=@file`, `--reason` mandatory changelog);
  `lint` enforces the quality bar (exit 1 when INCOMPLETE, `--json`
  included); `status` reports whole-market coverage.
- **Trigger conditions (AI-decided, skills/19)**: mandatory before L4
  verdicts on L3 shortlists, on holdings with thesis drift, and for
  keyhole quarterly falsification checks; never for funnel-wide scans
  or D4 tactical mode. Campaign order: keyholes/holdings → L3 →
  funnel candidates → industry by industry.
- **Staleness**: the result pins the history hash; a refetched history
  (new reporting period) marks it STALE and it drops out of scoring
  until rebuilt.
- Never fabricate missing statement fields (A shares count, HK capex) —
  declare gaps; say per-share is untrustworthy when it is.

## Investment masters

Six built-in master strategies, ordered by fame (this ordering is
code-enforced via the strategy registry's `order` field and mirrored
by the skill filenames 07-12), plus one user-introduced folk master
(散户乙, skill 17, user mandate 2026-09-10):

| # | Master | id | Core focus | Key gates |
|---|---|---|---|---|
| 1 | Buffett | `buffett` | Franchise + owner earnings (evolved past cigar-butts) | ROE≥15%, 毛利率≥40%, 负债率≤60%, OCF yield≥5%, FCF yield≥4%, 借钱分红否决 |
| 2 | Munger | `munger` | Invert + latticework; wonderful at fair price | ROE≥20%, 毛利率≥40%, 负债率≤50%, 借钱分红否决 |
| 3 | Graham | `graham` | Margin of safety as arithmetic | PE×PB≤22.5 (派生列), 负债率≤50%, ROE≥10%, 借钱分红否决 |
| 4 | Livermore | `livermore` | Pivotal points + risk discipline; pure price | ret_60d≥0, 波动率市场内前50%, pos_52w≥60 |
| 5 | Duan Yongping | `duan` | Business model first, no stop-losses | ROE≥20%, 毛利率≥40%, 波动率市场内后40%（pctl≤60）, 借钱分红否决 |
| 6 | Justin Sun | `sheng` | Attention economics + narrative momentum | ret_60d≥0, 波动率市场内前40%（pctl≥60） |
| 7 | 散户乙 (folk, user-added 2026-09-10) | `sanhuyi` | 赚免费股票：股息复利 + 成本收回（持有纪律层） | ROE≥15%, 负债率≤60%, OCF yield≥4%, 股息率≥2.5%, 借钱分红否决 |

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
5. Recommendation / holding analysis / trade decisions follow the
   **QMF fused pipeline** (user mandate 2026-09-15: 融合，不分情况
   讨论 — every recommendation outputs ONE quant+master-optimal pick).
   **Three-core mandate (user mandate 2026-09-29)**: 商业模式、企业
   文化、DCF 估值 are the three equal-weight cores and the ONLY
   ranking keys (`core_score`, absolute anchors, no percentiles);
   every other metric — pillar scores, composites, vote_count,
   mean_composite — can only be a reason NOT to pick (veto/display),
   never a ranking input:
   **L1** `masters-vote` (wide pool = vote_count≥1 & ~veto_hard where
   veto_hard = intel_red | borrowed_dividend | profit_spike; cycle_trap
   excluded post-live-pass; ranked by core_score only — never from a
   single strategy's top rank, never by vote count. 量化只否决、AI
   做选择: the AI reads the whole pool and picks the deep-review
   list; `--check` runs the live cycle-trap pass on that shortlist;
   `--top N` is a legacy shortlist, not a selection mechanism.
   `masters-vote --horizon short|ultrashort` runs the same fusion in
   D4 tactical mode: floor = real business (core_business≥50) +
   weekly uptrend structure + no veto, pullback-from-60d-high sweet
   spot (-15%,-5%), DCF downgraded to an honest "失败变持有" note,
   mandatory 短炒警示 discipline block) →
   **L2** veto flags (cycle_trap = pe_divergence ≥ 1.5, cycle_warn ≥
   1.25, profit_spike ≥ +200%, intel red flags: insider selling /
   解禁减持 / 粉饰 / 借钱分红) → **L3** AI three-core deep review with
   written argumentation duty (business model: moat + machine
   lifecycle; culture: founder + 本分审计, behavior-level evidence
   only; DCF: reverse-DCF implied expectations as the starting point)
   + 7-master qualitative vote on top (playbooks 07-12, 17) →
   **L4** AI fused verdict (user style + market
   conditions; NOT a mechanical gate intersection). Close with
   position discipline per Duan — enter only if a -50% drawdown on the
   fully-understood business is tolerable, and size the position
   accordingly. Raw factor tables alone are not a deliverable. Duan's
   principle governs evidence direction (user quote, 2026-09-06):
   数据只能成为我不买这个股票的理由，不能成为我买的理由；我买
   的理由一定是看未来现金流，而这必须从商业模式和企业文化出发。
   The GSL case (2026-09-15) is the calibration: quant #1 on two
   strategies, 6:1 master veto — the fusion must catch that BEFORE
   recommending (docs/analysis/20260915_undervalued_gsl.md).

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
  profiles live in the top-level LOCAL-ONLY `users/` dir (gitignored,
  never pushed) — modify them only through the `user` / `holding`
  CLI commands, never by hand.
