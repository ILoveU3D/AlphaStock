# AGENTS.md — Polar Star for AI Agents

You are operating **Polar Star**, a value-investment research toolkit
covering A-share, Hong Kong and US equities. This file tells you what
the toolkit can do, when to use what, and how to leave it smarter than
you found it.

## What this repo is

- `python -m polar_star fetch` builds a dated snapshot: full-market
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
- `python -m polar_star trade ...` manages the AI's own virtual
  portfolio (multi-season paper trading): CITIC/ZA-Bank fee models,
  T+1/T+2 settlement, board-lot checks, multi-currency cash with FX
  spread, daily NAV marking, withdrawal tracking and a review journal.
  Seasons live in git-tracked `trading/seasons/`; lessons accumulate in
  the `trading` skill Field Notes.
- `python -m polar_star tower ...` manages the **cognitive tower**
  (认知巴别塔): philosophy bricks distilled from conversations,
  masters and 105+ books, with DCF as the single axiom. Bricks live
  in the git-tracked `polar_star/tower/bricks/` dir (inside the
  package since 2026-10-13) — see the Cognitive tower section
  for the mandatory lookup/absorb loop.
- `python -m polar_star arsenal ...` runs the **quant arsenal**
  (量化武器库): every quantitative algorithm in the toolkit — one
  weapon = one module + one registry entry, each carrying verified
  lineage. Modules and the JSON registry live in
  `polar_star/arsenal/`; `strategy/` holds strategy *declarations*
  only. See the Quant arsenal section for the dual-track doctrine
  and the usage discipline.
- Analysis commands read the latest snapshot (and live quotes where
  noted) — no LLM runs inside the toolkit; you write the prose.
- There is **no human UI**: the CLI is the only entry point and AI
  agents are the only operators. `README.md` describes the system
  (architecture / methodology); this file is your operating manual.

## Freshness contract (code-enforced)

- `ask`, `compare`, `overview`, `recommend`, `holding list`,
  `trade buy/sell/fx/cash/dividend/nav/journal/status`, and
  `arsenal run/scan/battery/screen` run a
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
- **Agent house rule (user-mandated 2026-09-03; calendar-aware since
  2026-10-08)**: every conversation starts with `doctor --json` and
  reads `agent_rule[market].needs_fetch` — the machine form of the
  1-hour iron rule: a closed market whose data sits at/after the last
  completed session's close needs **no** fetch (a holiday weekend is
  not staleness); an in-session market with data >1h old, or data
  older than the last close, does. Fetch only the markets you need.
  The 24h/7d CLI gates stay as backstops (kline lag counts trading
  days, so a Golden-Week gap no longer FAILs US answers). Never
  analyze on stale data without fetching.
- `fetch --markets US` (any subset of A/HK/US) fetches only those
  markets; the rest are **carried forward** from today's own dir or
  the prior snapshot — master.csv stays full-market, per-market
  `market_at` timestamps and FX inheritance are recorded in the
  manifest (`carried` tags surface in `doctor`).
- Quotes/kline sources are health-ordered and fail over automatically
  (registry + `data/source_health.json`, regenerable): a source with
  repeated connection errors cools down for 1h and yields its primary
  seat (e.g. EM push2 IP-blocked → Tencent takes quotes), recovering
  on the next success. A per-entity miss is never counted as an
  outage. Deep fetches (klines / HK F10) run on per-source worker
  pools (`config.FETCH_WORKERS`).
- `ask` always pulls the LIVE quote for price/PE/PB; fundamentals and
  percentiles come from the latest snapshot. `recommend` /
  `holding list` price holdings live with a snapshot-price fallback.
- Never present snapshot-day numbers as "current" — cite the
  data-as-of line the commands print.

## Machine-readable output (`--json`)

- Every data command accepts `--json`: `ask`, `screen`, `compare`,
  `overview`, `recommend`, `holding list`, `doctor`, and every
  `tower` / `thesis` / `profile` / `arsenal` subcommand.
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
| "你怎么看待X / what do you think of X" | single-stock-analysis | `python -m polar_star ask X` |
| "...but why / 证据" | single-stock-analysis | `python -m polar_star ask X --evidence` |
| "X和Y哪个好 / X vs Y" | compare-stocks | `python -m polar_star compare X Y` |
| "今天给我推荐股票（按我的风格、结合我的持仓）" | user-recommend | `python -m polar_star recommend`（缺省取 session 当前用户） |
| "推荐/最被低估/量化+大师最优" | fused-quant-master | `python -m polar_star masters-vote`（L1 宽池=量化只否决、AI 从全池选深评名单 + core_score 唯一排序）+ L2 红旗 + L3 三核深评与大师定性 + L4 融合裁决，per skills/18 — user mandate 2026-09-15: 融合，不分情况讨论；2026-09-29: 三核（商业模式/企业文化/DCF）为唯一排序键，量化只否决 AI 做选择 |
| "短线/超短线有什么机会" | fused-quant-master | `python -m polar_star masters-vote --horizon short|ultrashort`（D4 战术模式：floor=真生意 core_business≥50 + 周K结构上行 + 无否决，甜点区=60日高点回撤 5-15%，同一融合管道 + 纪律块；塔砖 weekly-trend-daily-pullback） |
| "全市场武器齐射 / 证据矩阵选股" | fused-quant-master | `python -m polar_star arsenal screen --market US`（轨A：全部 armed 透镜齐射 → 股票×透镜证据矩阵 + 收敛名单；与轨B 加权排序双轨呈报，见 Quant arsenal 节——换管 masters-vote 需单独授权） |
| "用某件武器横扫市场 / 查武器库" | fused-quant-master | `python -m polar_star arsenal scan <id> --market US [--top N]` + `arsenal list|show|stats`（注册表读取不过新鲜度门） |
| "单股武器解剖 / 深度简报" | fused-quant-master | `python -m polar_star arsenal run <id> --on X [--param k=v]` / `arsenal battery --on X`（全部 armed 纵深兵器齐射单股，forensic-audit 排首；剑序见调用纪律 v2） |
| "把塔砖断言的机器注入候选池 / 管理产业论点" | fused-quant-master | `python -m polar_star masters-vote --thesis <id>` + `thesis list|show|add|amend|retire`（见 Thesis pools 节） |
| "读公司原文 / 蒸馏商业模式与文化" | fused-quant-master | `python -m polar_star profile fetch|show|assess|list|status`（见 Company profiles 节——蒸馏回写后文化核恢复打分，profiles/ 本地-only 永不推送） |
| "建财务模型 / DCF估值 / 可比公司" | fused-quant-master | `python -m polar_star model gather|write|show|lint|status X`（AI 手工建模工作台：gather 聚合素材→AI 写理解层〔飞轮/文化/reverse-DCF 三件套+世界叙事+自由维度〕→lint 合格线〔信息量≥财报〕；估值层 fetch|build|set|list；触发条件见 skills/19；DCF 钩平行 D3 进 core_dcf；models/ 本地-only 永不推送） |
| "设置/修改我的投资风格" | user-profile | `python -m polar_star user set-style me --base buffett --weight value=0.3` |
| "录入/修改/查看我的持仓" | user-portfolio | `python -m polar_star holding add|update|remove|list` |
| "审视我的持仓 / 深度分析持仓" | holding-deep-review | `holding list` 先看体检，再 `ask X --evidence` per holding + `screen --strategy <master>` (business model, moat, culture, earn/lose paths, two master frameworks) |
| "X的舆情/解禁/公告/研报/财报解读" | intel | `python -m polar_star intel X`（A 全板块；HK 公告+新闻，研报无源；US EDGAR 披露+新闻+一致评级；含解释层：财报速读/公告含义〔…〕/新闻热度/研报汇总，user mandate 2026-09-09） |
| "现在港股有什么机会 / what's attractive now" | market-overview | `python -m polar_star overview --markets HK` |
| "数据新鲜吗 / is the data current" | data-ops | `python -m polar_star doctor` |
| "巴菲特会怎么看X" | master-buffett | `python -m polar_star screen --strategy buffett` + `ask X --evidence` |
| "芒格会怎么看X / 反过来想" | master-munger | `python -m polar_star screen --strategy munger` + `ask X --evidence` |
| "格雷厄姆会怎么看X / 市场先生" | master-graham | `python -m polar_star screen --strategy graham` + `ask X --evidence` |
| "利弗莫尔会怎么看X / 趋势" | master-livermore | `python -m polar_star screen --strategy livermore` + `ask X --evidence` |
| "段永平会怎么选X" | master-duan | `python -m polar_star screen --strategy duan` + `ask X --evidence` |
| "孙宇晨会怎么看X / 热点股" | master-sheng | `python -m polar_star screen --strategy sheng` + `ask X --evidence` |
| "散户乙会怎么看X / 免费股票/成本收回" | master-sanhuyi | `python -m polar_star screen --strategy sanhuyi` + `ask X --evidence` |
| Macro / gold / geopolitics | macro-themes | framework + `overview` / `ask --evidence` |
| "你的虚拟盘怎么样 / 你的资产情况" | trading | `python -m polar_star trade status` |
| "虚拟盘买入/卖出 X" | trading | `python -m polar_star trade buy/sell <season> X --qty N --note 理由` |
| "复盘虚拟盘 / 记教训" | trading | `python -m polar_star trade journal <season> --text ...` + `skill note trading "..."` |
| "看看你的战绩 / 总结赛季" | trading | `python -m polar_star trade status/nav/journal --json` → AI 成文总结（无 dashboard，AI 即看板；赛季全员共享） |
| "短期内最推荐/最被低估的股票" | horizon-framework | `python -m polar_star screen --horizon short` |
| "超短线/短线有什么机会" | horizon-framework | `python -m polar_star screen --horizon ultrashort`（必须附短炒警示） |
| "X适合中长期持有吗" | horizon-framework | `python -m polar_star ask X`（四周期剖面）+ 14 号 playbook 质性层 |
| Philosophy / 处世 / 人生问题 / how to value | cognitive-tower | `python -m polar_star tower search <query>` 查塔作答（见 Cognitive tower 节家规） |
| "新手 / 导航 / 这是什么 / 带我去X / 参观" | navigation | 无专用命令——按 skills/20-navigation 渐进讲解（AI 即导览，一次只讲一层，无状态） |

## Cognitive tower (认知巴别塔)

The tower is the canonical home for philosophy — every idea worth
keeping becomes a **brick**: one `polar_star/tower/bricks/<id>.md`
file (git-tracked inside the package since 2026-10-13, never inside
the cleanable `data/`) with a one-line
`statement`, a `source` (`book:` / `master:` / `conversation:` /
`ai`), a cognitive `status` and typed links (`derives-from` /
`refines` / `contradicts` / `applies-to` / `tension`). The single
axiom is `dcf-universal-law` — everything else traces to it,
tensions included (marked, never resolved by deletion). Statuses:
`axiom > mission > law > principle > hypothesis > observation >
refuted`; migrations require a reason and are archived as Field
Notes; `refuted` bricks are never deleted (errors are assets).

- Commands: `python -m polar_star tower list|show|add|note|link|
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
   Master-attributed bricks are linked `applies-to: master-<id>`
   (hub bricks master-duan/buffett/munger/graham/livermore/sheng/
   sanhuyi) **at absorb time**, so `tower search master-<id>`
   always returns the full theory set for the L3 master vote
   (tower→L3 channel, skills/18; user mandate 2026-10-11).
3. Answers stay non-evasive: brick × current reality = concrete
   judgment; a conditional verdict must state its conditions, not
   hedge.

## Thesis pools (论点喂池)

Theses are the tower→L1 pipeline: a brick's assertion about a
money-printing machine (e.g. "memory is being repriced from cyclical
to compute-input") becomes a named, member-carrying pool that
`masters-vote --thesis <id>` injects into the L1 candidate universe.
They live in the git-tracked `polar_star/tower/bricks/theses/` dir
(one JSON per
thesis, CLI-maintained, atomic writes — never inside `data/`); a
thesis is a tower artifact, so it lives where its brick lineage lives
(merged 2026-09-30; moved into the package 2026-10-13).

A thesis carries: `brick` (tower lineage — the falsification trail
that motivated it), `statement`, `reason`, `features` (the three
window traits: new/unpriced, needed by a tech/demographic cycle,
skill-attention arbitrage), `falsification` (explicit kill
conditions), `members` (market:code list), `industry_hints`
(discovery aid), and `status` (active/retired).

- Commands: `python -m polar_star thesis list|show|add|amend|retire|
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

## Quant arsenal (量化武器库)

The arsenal is the toolkit's computation core (user mandates
2026-10-12/13): **every quantitative algorithm lives in
`polar_star/arsenal/`** — one weapon = one independent module
(`<weapon-id>.py`, dashes→underscores) + one registry entry
(`registry/<id>.json`). `strategy/` keeps strategy *declarations*
only (ids, weights, gate DSL strings, fame order); all math lives
here. Tower = meaning, arsenal = computation, strategy =
declaration — the three cores of the polar_star package.

- **Entry ticket**: every weapon cites a verified lineage (paper /
  classic book / master practice / toolkit veteran) — unverified
  experiments never enter the registry. There is **no trust
  lifecycle**: a registered weapon is trusted; `status` is only
  `armed` (data-ready) or `dormant` (waiting for a data source — the
  registry entry names the exact gap; a dormant weapon's `run`
  returns its status and reason, never fabricated numbers).
- **Four quality gates**: ① one weapon = one complete battlefield
  answer (fragments demoted to internal modules); ② output carries
  its own interpretation `anchor` — no naked numbers; ③ `limits`
  states the failure conditions; ④ synthetic-data unit tests cover
  the pure math (runners never touch the network — `build_context`
  is snapshot-pure).
- **No castes**: any weapon can dissect one stock (`run --on X`) or
  sweep a whole market (`scan --market US`); the registry's
  `sweepable` flag only marks compute cost. Registry reads
  (`list [--stage|--status]`, `show`, `stats`) skip the freshness
  gate like `tower`; the four execution commands (`run`, `scan`,
  `battery`, `screen`) pass through it.
- `battery --on X` fires every armed deep weapon at one stock and
  collects a briefing — **forensic-audit ranks first** (if the
  statements can't be trusted, nothing else matters); one weapon's
  exception never sinks the briefing (collected as `{"error"}`).
- `screen --market US` fires every armed sweepable weapon at the
  market universe → a stock×lens **evidence matrix** (`<wid>:<col>`
  columns) plus a **convergence list** (≥2 value lenses agree cheap
  ∧ zero vetoes — a *declared heuristic, never a ranking*); `--full`
  dumps the whole matrix. One lens failing never voids the salvo
  (collected under `failed`).
- `scan_sort` in a registry entry declares the display ordering
  (column + ascending) for `scan`; without it the first numeric
  column sorts descending.

**Dual-track doctrine (双轨呈报、综合评估, user mandate
2026-10-13):** selection = track A `arsenal screen` (20+ independent
verified lenses per stock — cheapness/quality/capital-discipline/
price-behavior each with its own validated definition, mutual
corroboration replacing single-score ranking) **×** track B the
classic weighted-ranking list (kept — its undervaluation-finding
ability is practice-proven). Both lists land on the AI's desk
together: intersection = high-confidence candidates, divergence =
research leads; the AI's three-core judgment (business model /
culture / DCF) is unchanged. **Rewiring `masters-vote` onto
`arsenal screen` (hard switch) is a post-Phase-1 action requiring
separate user authorization** — the old L1 pipeline is untouched.

**调用纪律 (usage discipline v2):**

1. Registered = trusted. The only questions are "right battlefield"
   and "right data fed" — read the weapon's `limits` field often.
2. Draw swords on demand: every weapon call leaves one trace line
   (which weapon, output, adopted-or-not, why) in the trading
   journal or a skill Field Note — the evidence chain belongs to the
   operator, scars never enter the registry itself.
3. Deep-review sword order: `forensic-audit` first (untrustworthy
   statements end the review) → `value-ladder` →
   (`average-earnings-power` when cyclical) → `expectations-engine`
   → `owner-audit`; sizing takes the minimum of
   `sizing-compass`'s three numbers; entries are declared through
   `barrier-forge`'s three barriers.
4. Trading windows: tactical positions check the chandelier trail
   mechanically (close-confirmed, only ratchets up); a broken value
   floor wakes `regime-radar` + intel + `short-interest-monitor`
   for a three-evidence verdict — price only rings the bell, it
   never judges.
5. Weapons only veto, never select: a forensic red light rejects a
   candidate, but a green light is never a buying reason (Duan's
   principle, Answer shape §5).

## Company profiles (公司画像, 本地-only)

Profiles are the L3 read-store: raw company source text on one side,
the AI's distilled business-model / culture assessment on the other.
They close the D3 loop — the culture core in `core_score` is
veto-only until a distillation activates it.

- **Storage split (user mandate 2026-09-29)**: raw fetches live under
  `data/profiles/raw/<market>/<code>.json` (cleanable, regenerable);
  assessments live in the top-level `profiles/<market>/<code>.json`
  loose store (LOCAL-ONLY working store), while the **compressed
  distribution pack `profiles/pack/<MKT>.jsonl` (minified, one company
  per line, sorted by code) is git-tracked and ships with the repo**
  (user mandate 2026-10-23, superseding the 2026-09-29 never-push rule
  for the pack only; regenerate with `profile pack` after distilling —
  fresh clones read the pack as the canonical source via loader
  fallback).
- Commands: `python -m polar_star profile fetch|show|assess|list|
  status|pack` — all `--json`-capable. Profile commands do **not** run
  the freshness gate. Sources: A = 东财 F10 机构概况；HK = 东财 HKF10
  公司概况；US = SEC submissions meta + stockanalysis 简介.
- The loop (per L3 deep-review candidate): `profile fetch X` →
  `profile show X` + `intel X` （读原文） → three-core argumentation →
  `profile assess X --business-score N --culture-score N ...` → the
  D3 hook re-activates `core_culture` on the next `masters-vote` /
  `ask` run (`core_gaps` marks `CULTURE_DISTILLED`).
- **Staleness**: the assessment pins the raw content hash; a
  refetched/changed raw marks it STALE and it drops out of scoring
  until re-distilled. Independently, every profile **expires 90 days
  after `assessed_at`** (user mandate 2026-10-23,
  `profile.PROFILE_TTL_DAYS`) — quarterly, aligned with the earnings
  cycle when fundamental change surfaces; EXPIRED is treated exactly
  like STALE. `profile status` lists coverage + staleness.
- Never improvise a culture score from pillar data — no distillation
  means the culture core stays veto-only.
- **三核齐备义务 (user mandate 2026-10-18)**: 荐股 / 分析 / 持仓
  verdict 之前必须补全 profile —— **禁止两核半**: an undistilled
  name gets veto power only, never a verdict. The profile is the
  combined business-model + culture portrait and is therefore
  mandatory, not optional: every recommendation, every ask-grade
  analysis and every held position must carry a live (non-STALE)
  assessment; a STALE profile is re-distilled before the verdict,
  not after. Holdings are audited for profile coverage
  (`profile status` × season positions) and gaps are closed at
  discovery, as done for all 11 season holdings on 2026-10-18.
- **全市场蒸馏战役 (user mandate 2026-10-18)**: every quoted company
  in A/HK/US gets a distilled profile, run as a standing campaign
  mirroring the modeling campaign's division of labor — the machine
  builds the tiered queue (holdings → funnel by core_score → market
  industry by industry, tier builders reused from `model/campaign.py`)
  and bulk-fetches raw text; the AI distills one company at a time
  across sessions. Commands: `profile campaign init|status|next`
  (queue + derived progress, state in `profiles/campaign.json`,
  LOCAL-ONLY; no scheduled monitor), `profile fetch-all
  [--markets A,HK,US] [--force]` (bulk raw: A/HK paged datacenter
  fast path with per-stock fallback, US per-stock SEC+stockanalysis;
  fail-closed, never clobbers an existing raw on failure), and
  `profile assess --from-json <file>` (the AI's batch pen — every
  entry is AI-authored; the CLI transports, never judges). A STALE
  assessment re-enters the work queue automatically.
- **战役质量分层 (user mandate 2026-10-18, amended 2026-10-23)**:
  business AND culture cores are assessed for EVERY name (2.0
  mandate: culture portrait mandatory, vivid and company-specific);
  culture score is capped by evidence tier declared in the argument —
  A (founder words / shareholder letters / dated crisis behavior,
  third-party verifiable) unlimited, B (annual-report + news behavior
  record) ≤70, C (company self-description only) ≤45 and marked
  placeholder. The 2026-10-18 <5% density cap is retired in favor of
  tier caps. Profile 2.0 re-distillation (spec
  `docs/superpowers/specs/2026-10-23-profile-2.0-prompt.md`) requires
  reading the annual report (A: MD&A+segments; US: 10-K Item 1/7;
  HK: PDF gap declared) plus web due diligence (founder interviews,
  earnings calls, lawsuits, employee reviews) BEFORE scoring — a
  profile-summary-only score is a campaign violation. Anti-template:
  every argument carries ≥3 company-specific dated facts; same-cluster
  companies must be scored distinguishably (peer-relative pass first).
  All arguments declare their evidence basis.

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
- Commands: `python -m polar_star model gather|write|show|lint|status`
  (workbench) + `fetch|build|set|list` (valuation layer) + `campaign
  init|status|next|gather` (full-market campaign queue, user mandate
  2026-10-04: tiered queue holdings→funnel→market in
  `models/campaign.json`, gather-ahead monitor with backlog cap 300 and
  fail-3 park; the dossier itself stays AI-only) — all `--json`-
  capable. Only `build` runs the freshness gate. `gather`
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
  **On-the-spot modeling (user mandate 2026-10-23)**: when a
  recommendation/scan deep-review shortlist contains an unmodeled
  name, build the model on the spot (gather → write → lint) before
  any verdict — "no model" is never a reason to skip a candidate.
- **Staleness**: the result pins the history hash; a refetched history
  (new reporting period) marks it STALE and it drops out of scoring
  until rebuilt. Independently, every model **expires 30 days after
  `built_at`** (user mandate 2026-10-23, `store.MODEL_TTL_DAYS`) —
  EXPIRED is treated exactly like STALE: out of scoring, rebuilt
  before any verdict.
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

`python -m polar_star strategy list` shows all strategies (presets +
masters). `screen --strategy <id>` applies the master's gates and
weights. Each master has a skill playbook in `skills/` — read it
before answering in that voice.

Playbooks live in `skills/` — read the relevant one before answering.
`python -m polar_star skill list` indexes them.

## Holding-period dimension

Four horizons (registry-backed, `python -m polar_star horizon list`):
ultrashort (1-10 交易日, ret_5d+ret_20d), short (10日-3月,
ret_20d+ret_60d), mid (3月-3年, 估值修复+业绩兑现), long (3年+,
商业模式+现金流). `screen --horizon H` screens under the horizon;
`--strategy X --horizon Y` keeps the master's weights/gates and swaps
only the momentum window; `ask X` prints a four-horizon suitability
profile. The value DNA of this toolkit: mid/long are the promoted
horizons; ultrashort/short answers must carry the caution line and
position-sizing discipline.

## Daily mail (每日邮件)

A daily Buffett-letter-style Chinese letter (user mandate 2026-10-17,
spec `docs/superpowers/specs/2026-10-17-daily-mail-design.md`):
**the machine aggregates, the AI writes, the machine delivers** —
`python -m polar_star mail digest [--json]` builds the material pack
(L1 wide pool + one ask summary per deduped subscriber watch stock +
the active-seasons P&L block — per-position unrealized P&L merged from
season cost, `seasons_error` declared on failure; freshness-gated like
every data command), the AI composes the letter (today's pick via the
fused pipeline / a story from its own knowledge / watch-stock analyses
/ three-season holdings commentary — 3-5 minute read), and
`python -m polar_star mail send --file X.html --subject "..."
--data-as-of "..."` wraps it in the fixed research-note shell and
delivers it via QQ-mail SMTP
(To: the sender mailbox, Cc: all subscribers; one send per day unless
`--force`; `--dry-run` prints without sending). Subscribers are
managed with `subscriber add|remove|list`; storage is LOCAL-ONLY
under top-level `mail/` (gitignored, never pushed — SMTP credentials
in `mail/config.json`, hand-edited once). The scheduled task
(TRAE solo, 10:00 daily) runs: doctor → fetch if needed → digest →
write letter → send.

**Letter style spec (user mandates 2026-10-17, every daily letter):**

- **Voice**: 巴菲特股东信口吻 — 开场固定"各位股东"，结尾不署名；
  辛辣、幽默、带讽刺，让人有读下去的欲望；说人话，机器词汇
  （三核 / 百分位 / intel_red / DCF 核 / veto / L1-L4）一律翻译
  成日常语言（"每 100 块收入 67 块是毛利""股东每一块钱一年
  赚回三毛八""价格是 11 年半的利润"）。
- **Every stock verdict**: 每只分析的股票必须给出**高估/低估幅度**
  （估值假设写在明处：10% 要求回报、保守增长率≤过去实际值的一半，
  周期股/银行股用各自纪律，不硬套）。推荐段的股票默认可以下手，
  不标操作；只在**不能下手或有条件**时标注（观察 / 不伸手 /
  等数据 / 按纪律持有 / 不追）。数据缺的就老实说缺，
  操作栏写"等数据"，不编数。
- **推荐以美股、港股为主**：推荐段每个市场（US / HK / A）各推
  **一支**，只讲入选的，不解释谁被否决、为什么否决。
- **Profile gate (user mandate 2026-10-18)**: 信中分析/推荐的每只
  股票必须携带活体 profile 蒸馏（三核齐备义务 — 见 Company
  profiles 节）——写信前先 fetch + assess；未蒸馏标的只有否决，
  不上正文。
- **Layout (user mandates 2026-10-19 shell + 2026-10-21 mobile
  single column)**: 研报风排版壳 — 仿汇丰 / 摩根士丹利每日研报邮件：
  顶部藏青横向刊头条 + 红色细条，标题区（kicker / h1 / meta 分隔带 /
  standfirst 摘要框），数据表 `table.data`（深青表头），涨跌着色
  `.up`/`.dn`（红涨绿跌）。**正文单栏顺序排列**（2026-10-21 取消
  双栏，照顾手机读者；旧 `table.cols` 片段自动堆叠兼容）。壳承载全部
  版式（`LETTER_CSS` + `wrap_letter`）—— AI 只写正文片段，永远不改壳；
  片段契约注释在 mail.py 的 Letter shell 一节。
- **三期持仓段 (user mandates 2026-10-19 / 2026-10-21)**: 每日邮件
  必须包含三期实盘持仓盈亏和分析 —— 素材由 digest 的 seasons 块提供
  （NAV / 日盈亏 / 累计回报 + 逐持仓成本与浮动盈亏）。呈现方式
  （2026-10-21）：一张 `table.data` 汇总表展示三期 NAV / 日盈亏 /
  累计回报（逐持仓明细可续行或入 `.box`），"三期实盘" 段放分析
  prose；累计收益曲线写 `{{NAV_CHART}}` token，`mail send` 用
  纯标准库渲染器（mail_chart.py，活体 season NAV 历史）把它替换为
  CID 内联 PNG 图像 —— 无可画数据时机器自动落一句诚实缺口注记，
  不编图。
- **No meta sections**: 不单列"数据边界"段（数据问题在行文中
  一句话交代）；不立规矩、不写免责（壳的页脚自带免责与数据截至行）。
- 故事段保留：每期一个从 AI 知识储备里挑的故事，**与股票直接
  或间接相关均可**，标准是"值得思考"；来源（书/大师/史实）写明。

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
   veto_hard = intel_red | borrowed_dividend | profit_spike |
   expectation_overreach; cycle_trap excluded post-live-pass; ranked by
   core_score only — never from a single strategy's top rank, never by
   vote count. Pool rows carry the Graham-audit display columns
   `graham_g` (implied growth the price pays for, (pe−8.5)/2) and
   `expectation_gap` (graham_g − realized growth) — veto/display
   context, never ranking inputs. 量化只否决、AI
   做选择: the AI reads the whole pool and picks the deep-review
   list; `--check` runs the live cycle-trap pass on that shortlist;
   `--top N` is a legacy shortlist, not a selection mechanism.
   `masters-vote --horizon short|ultrashort` runs the same fusion in
   D4 tactical mode: floor = real business (core_business≥50) +
   weekly uptrend structure + no veto, pullback-from-60d-high sweet
   spot (-15%,-5%), DCF downgraded to an honest "失败变持有" note,
   mandatory 短炒警示 discipline block) →
   **L2** veto flags (cycle_trap = pe_divergence ≥ 1.5, cycle_warn ≥
   1.25, profit_spike ≥ +200%, expectation_overreach = Graham audit —
   implied g (pe−8.5)/2 ≥ 15% AND >15pp above realized growth, rev_yoy
   preferred / profit_yoy fallback; one-directional, never fires on
   cheapness; FCF-free so it covers the HK/US names where
   dcf_implied_g is imputed — user mandate 2026-10-11; intel red
   flags: insider selling /
   解禁减持 / 粉饰 / 借钱分红) → **L3** AI three-core deep review with
   written argumentation duty (business model: moat + machine
   lifecycle; culture: founder + 本分审计, behavior-level evidence
   only; DCF: reverse-DCF implied expectations as the starting point)
   + 7-master qualitative vote on top (playbooks 07-12, 17 + tower
   hub bricks `master-<id>` via `tower search` — tower→L3 channel,
   vote reasons cite brick IDs, skills/18) →
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

## Git & memory boundaries (user-mandated)

- **Git (2026-09-06)**: never push `main` directly — the repo has PR
  protection but credentials can bypass it silently, so "push
  succeeded" is NOT proof of compliance. Push only feature branches;
  PRs are opened and merged by the user on GitHub. The AI never
  calls the GitHub API to operate PRs on the user's behalf.
- **Memory files (2026-10-03 / 2026-10-09)**: no local memory files
  (`project_memory.md` prohibited 2026-10-03; `user_profile.md`
  prohibited 2026-10-09). All memory lives in the system libraries:
  philosophy → `polar_star/tower/bricks/`, procedures → `skills/`
  Field Notes, user state → `users/` (LOCAL-ONLY, gitignored),
  seasons → `trading/seasons/`. New user mandates are recorded at
  their proper layer at conversation time, never in scratch memory
  files.

## Self-refinement protocol (leave the toolkit smarter)

After answering, if you hit a quirk or found a better procedure
(resolution trick, source failure workaround, ambiguity in a skill),
record it in one concrete line:

    python -m polar_star skill note single-stock-analysis "smartbox resolves names missing from snapshot after delistings"

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
- Scratch files (one-off analysis helpers, ad-hoc JSON dumps) go to
  `tmp/` (gitignored) or the OS temp dir — never the repo root;
  anything left in the root must be committed deliberately or deleted
  at session end.
- Data lives in `data/snapshots/YYYYMMDD/`; never edit snapshot files.
  `data/` as a whole is **regenerable run-time state — safe to wipe
  daily** (user-mandated policy; `fetch` rebuilds it). Per-user
  profiles live in the top-level LOCAL-ONLY `users/` dir (gitignored,
  never pushed) — modify them only through the `user` / `holding`
  CLI commands, never by hand.
