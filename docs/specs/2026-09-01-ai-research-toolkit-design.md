# Value Genie — AI-First Research Toolkit (Phase 2 Design)

Date: 2026-09-01
Status: approved
Depends on: `2026-08-31-value-genie-design.md` (Phase 1: fetch pipeline, composite scoring, Streamlit dashboard)

## 1. Problem

Phase 1 delivers a human-facing screener: batch fetch → funnel → composite
ranking → dashboard. It cannot answer the user's actual day-to-day question:
"你怎么看待茶百道？" ("What do you think of ChaBaiDao?") — the pipeline only
ranks the pre-selected ~200 candidates per market, has no name resolution,
no single-stock deep view, and no interface designed for AI agents.

The user's core repositioning: **this repo is primarily a financial toolkit
for AI agents**. Any AI (Claude Code, Trae, Cursor, ...) that scans the repo
should discover the tools, know when to use which one, and produce a
professional, data-backed answer with fresh data. The visualization layer
is a human-facing auxiliary, not the core.

## 2. Goals

1. Any AI entering the repo auto-discovers capabilities via `AGENTS.md`
   and routes questions to the right tool without human setup.
2. Single-stock questions get a two-layer answer: instant conclusion
   first (brief), full evidence on demand (--evidence) — per user's
   explicit preference: "最简单的、最具实时性的结论；追问时再摆数据".
3. Skills (playbooks) are living documents with two refinement paths:
   - AI self-refinement: agents append field notes after each answer.
   - Human refinement: visual Skills Manager page in the Streamlit app.
4. Coverage beyond stock picking: macro themes (geopolitics, gold) and
   investment philosophy skills that frame *how* to reason, backed by
   the data tools.

Non-goals (Phase 2): real-time macro data feeds (gold spot, FX beyond
HKD/CNY, indices) — reserved as Phase 3 extension points; MCP server
transport; natural-language answer generation inside the toolkit
(the calling AI writes the prose; the toolkit supplies facts).

## 3. Architecture

```
Human question ──→ AI reads AGENTS.md → routes to skill
                    │
                    ├─ runs CLI: ask / compare / overview / doctor
                    ├─ answers the human
                    └─ skill note <id> "lesson"   (self-refinement)
                              │
Human ──→ Streamlit Skills Manager: view / edit / promote notes
                              │
                              ▼
                   skills evolve, all AIs inherit
```

New package layout (additions in bold):

```
value_genie/
  resolve.py          # name/code → {market, code, name} resolution
  analyze.py          # single-stock engine: live quote + financials
                      #   + peer percentiles + verdict + risk flags
  overview.py         # market snapshot digest: top-N, sectors, valuation
  doctor.py           # snapshot age / kline freshness / source health
  skills.py           # skill file store: parse / validate / note / edit
  __main__.py         # + ask / compare / overview / doctor / skill
AGENTS.md             # capability map + routing table + freshness contract
skills/               # 6 playbooks, YAML frontmatter + markdown body
app.py                # + Skills Manager page
```

## 4. Component Design

### 4.1 `resolve.py` — symbol resolution

- Input: free text (Chinese name, ticker, pinyin-ish name, "2555.HK").
- Resolution chain:
  1. Exact code forms: `600519` / `sh600519` / `600519.SH` / `02555` /
     `2555.HK` / `HK02555` / `AAPL` / `usAAPL` → market + code.
  2. Latest snapshot quotes (`data/snapshots/<latest>/<mkt>_quotes.csv`):
     exact name match, then substring / fuzzy match (rapidfuzz if
     available, difflib fallback) over all three markets.
  3. Live fallback: Eastmoney smartbox search API (`searchapi` endpoint)
     — works even with no snapshot on disk.
- Output: list of candidate matches (best first) with market/code/name;
  `AmbiguousStock` error carrying the shortlist when top matches tie.
- Pure functions + thin network fallback; fully unit-testable offline via
  injected snapshot frames.

### 4.2 `analyze.py` — single-stock engine

Data assembly for target {market, code}:
- Live quote: Eastmoney push2 single-security endpoint (real-time price,
  market cap, PE/PB) — the "实时性" requirement. Falls back to snapshot.
- Fundamentals on demand: A → Eastmoney F10 batch (by code); HK → F10
  single; US → SEC companyconcept/frames (reuse Phase 1 fetchers).
- Kline metrics: reuse cached snapshot kline if fresh, else fetch.
- Peer set: the gated universe (post-gates, pre-candidate-cap) from the
  latest snapshot quotes+financials; recomputed from snapshot files.

Percentile engine: for each metric (pe_ttm, pb, ps, dividend_yield,
rev_yoy, profit_yoy, roe, gross_margin, net_margin, debt_ratio,
ret_250d, volatility) compute the target's percentile within its
market peer set. Cheaper-is-better metrics (pe, pb, ps, debt_ratio,
volatility) invert so higher percentile always = more attractive.

Verdict engine (deterministic, no LLM):
- Composite pillar scores (Phase 1 factors) on the target row.
- Blend with balanced preset weights → composite percentile vs peer set.
- Five-band verdict: significantly undervalued / undervalued / fair /
  overvalued / significantly overvalued.
- Risk flags: debt_ratio > 70; rev_yoy < 0; profit_yoy < 0;
  drawdown_52w < -40%; pe_ttm missing; data staleness.
- Output modes:
  - brief (default): verdict + live price + 3 key numbers + risk count.
  - evidence: full metric table with peer percentiles, risk flag list,
    kline momentum block, data-as-of timestamps.

### 4.3 `overview.py` — market digest

- Inputs: latest snapshot master.csv (+ quotes for sector counts).
- Output: per market — top-N by balanced composite, sector distribution
  of the top-50, valuation medians (pe/pb), breadth (share of
  candidates above/below 52w mid), snapshot age. Markdown + JSON.

### 4.4 `doctor.py` — data health

- Checks: latest snapshot age; per-market quotes row count; kline
  freshness (max last-date lag per market); financials file presence and
  row counts; failed-fetch entries from manifest; clock skew vs last
  trade date per market timezone.
- Output: PASS/WARN/FAIL per check + one recommended action line
  ("run: python -m value_genie fetch"). Exit code 0/1 for CI-ish use.
- Contract in AGENTS.md: AI should run `doctor` before answering when
  the question is price-sensitive and the snapshot is older than one
  trading day; `ask` always uses live quotes regardless.

### 4.5 `skills.py` — skill store (evolution core)

Skill file format (YAML frontmatter + markdown):

```markdown
---
id: single-stock-analysis
title: Single Stock Analysis
triggers:
  - "你怎么看待X"
  - "X值得买吗"
commands:
  - ask
version: 3
updated_at: 2026-09-01T12:00:00
---
# Playbook
1. Resolve the name ...
## Field Notes
- [2026-09-01 14:32] (ai) smartbox fallback resolves delisted names faster
```

Store API (pure functions over a skills directory):
- `load_skills(dir) -> list[Skill]` — parse + validate frontmatter;
  malformed files are reported, never crash the whole load.
- `save_skill(dir, skill, author)` — validate, bump version,
  timestamp, write atomically (tmp file + replace), keep backup copy
  under `skills/.backup/<id>/<version>.md` (prune to last 10).
- `append_note(dir, id, text, author="ai")` — append one timestamped
  line to Field Notes; the only write path agents get by default.
- `edit_skill(dir, id, {...})` — structured edits: add/remove triggers,
  replace body; requires author="human" unless explicitly overridden.
- YAML dependency: PyYAML (add to requirements; sandbox installs to
  `libs/` as with pandas).

Guardrails: frontmatter must parse and `id` must match filename;
backups before every overwrite; `append_note` never touches the
Playbook body.

### 4.6 CLI surface (`__main__.py`)

```
python -m value_genie ask 茶百道                 # brief verdict
python -m value_genie ask 摩尔线程 --evidence    # full evidence pack
python -m value_genie ask AAPL --json            # machine-readable
python -m value_genie compare 茶百道 古茗 奈雪的茶
python -m value_genie overview --markets A,HK --top 10
python -m value_genie doctor
python -m value_genie skill list
python -m value_genie skill show <id>
python -m value_genie skill note <id> "lesson text"
python -m value_genie skill edit <id> --add-trigger "X还能买吗"
```

Existing `fetch` / `screen` unchanged.

### 4.7 `AGENTS.md` — the discovery surface

Sections:
1. What this repo is (one paragraph, AI-facing).
2. Freshness contract: when to run `doctor`, when `fetch` is required,
   live-vs-snapshot semantics per command.
3. Routing table: question pattern → skill id → commands.
4. Self-refinement protocol: after answering, if a lesson was learned
   (source quirk, resolution trick, missing data path), run
   `skill note <id> "<lesson>"`; keep notes one-line and concrete.
5. Output conventions: lead with the verdict; show evidence only when
   the human asks why; always state data-as-of timestamps.
6. Pointers to skills/ playbooks for deeper procedures.

Written in English (per project convention: all written material
English except README, which stays Chinese).

### 4.8 Skills — the six playbooks

| File | Skill | Type |
|---|---|---|
| 01-single-stock-analysis.md | name → resolve → doctor-if-stale → ask brief → evidence on follow-up | tool |
| 02-compare-stocks.md | resolve all → compare → highlight cheapest vs fastest grower vs safest | tool |
| 03-market-overview.md | overview → sector read → top names as candidates | tool |
| 04-data-ops.md | doctor → interpret → fetch when stale → source failure playbook (push2 rotation, TX endpoint fallback) | tool |
| 05-macro-themes.md | geopolitics / gold / macro: reasoning framework (second-order effects, safe-haven flows, rate path) + which toolkit metrics corroborate (volatility, drawdown, defensive sector percentiles) | knowledge |
| 06-investment-philosophy.md | margin of safety, circle of competence, moats, mean reversion — the house voice for every answer; how to phrase uncertainty | knowledge |

Knowledge skills deliberately reference tool commands for corroboration
so even philosophy answers stay data-grounded.

### 4.9 Streamlit Skills Manager (human refinement)

New page in `app.py` (sidebar nav: Dashboard | Skills Manager):
- Table: id, title, triggers, version, updated_at, note count.
- Detail editor: editable triggers (tag input), commands, Playbook body
  (text area), read-only rendered Field Notes with per-note actions
  (promote → appends the note text into Playbook body and removes the
  note; delete).
- Save path: `save_skill(..., author="human")` → same validation,
  versioning and backup as CLI.
- Left as the only human write path; no direct file editing required.

## 5. Data Flow Example

"你怎么看待茶百道？" →
`ask 茶百道` → resolve → HK/02555 (snapshot fuzzy hit) →
live push2 quote (price, cap, PE) + snapshot F10 fundamentals +
peer set (gated HK universe) → percentiles → verdict
"undervalued band, PE at 18th percentile, rev_yoy -4.2%,
1 risk flag (revenue contracting)" → AI writes the prose answer.
Follow-up "为什么？" → `ask 茶百道 --evidence` → full tables.
AI notices smartbox needed for a peer name → `skill note
01-single-stock-analysis "smartbox resolves CN names missing from
snapshot after delistings"`.

## 6. Error Handling

- Unresolvable name → exit 2 with the closest matches listed.
- No snapshot on disk → `ask` degrades to live-only metrics with a
  warning; percentiles unavailable; `compare`/`overview` hard-fail with
  "run fetch first".
- Source failures inside analyze → per-dataset fallback chain already
  in Phase 1 http layer; missing pieces show as N/A + risk flag
  "incomplete data" instead of crashing.
- Malformed skill file → load reports it, CLI `skill list` marks it
  ERROR, other skills unaffected.

## 7. Testing

- Unit: resolver (code forms, snapshot fuzzy, ambiguity), percentile
  orientation, verdict bands, risk flags, skill store (parse/validate/
  note/backup/atomic write), doctor checks (fixture snapshot trees).
- CLI: arg parsing + output shaping via capsys, network mocked.
- Smoke on real data: `ask 茶百道`, `ask 摩尔线程`, `ask AAPL
  --evidence`, `compare`, `overview`, `doctor`, `skill note` round-trip,
  Skills Manager render path.
- AppTest for Skills Manager (where sandbox permits; else import-level).

## 8. Delivery Order

1. skills.py + skill files + AGENTS.md (discovery surface first).
2. resolve.py + analyze.py + ask/compare commands.
3. overview.py + doctor.py + their commands.
4. `skill` CLI commands.
5. Skills Manager page in app.py.
6. Full test pass + real-data smoke + README update (Chinese, brief).
