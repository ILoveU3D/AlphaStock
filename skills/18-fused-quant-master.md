---
id: fused-quant-master
title: Quant-Master Fusion Recommendation (量化×大师融合推荐)
order: 18
triggers:
  - 推荐
  - 最推荐
  - 最被低估
  - 低估的标的
  - 有什么机会
  - 量化加大师
  - 融合推荐
  - 值得买
commands:
  - masters-vote [--top N] [--json]
  - ask X --evidence
  - intel X
  - recommend --user me
version: 4
updated_at: 2026-09-16T11:06:53
---

# Playbook

Answer every recommendation request through the fused QMF pipeline —
ONE quant+master-optimal pick, never a split "quant says X, masters say
Y" answer. User mandate 2026-09-15: 融合，不分情况讨论。The GSL case
(2026-09-15) is the origin: quant screens ranked GSL #1 (graham +
sanhuyi), the 7-master layer vetoed 6:1 (cycle trap + CEO/CFO
synchronized selling + forward PE 8.41 vs TTM 4.30). The fusion must
catch that BEFORE recommending, not after.

## The four layers (L1/L2 code-enforced, L3/L4 AI-run)

### L1 — 量化共识层（代码，`masters-vote`）

`python -m value_genie masters-vote --top 15 [--json]`

- Each stock is voted against all 7 masters' hard gates:
  `vote_count` (0-7) + `masters_passed` + `mean_composite` (mean of
  composites under each master's own weights).
- Ranking: vote_count desc → mean_composite desc. A 2-vote Graham #1
  (GSL) correctly ranks below 4-vote consensus names.
- **Never recommend from a single strategy's top rank** — the pool
  starts at the cross-master consensus.

### L2 — 否决层（代码 flags + 规则）

`masters-vote` prints the veto flags; treat them as hard inputs:

- `CYCLE_TRAP`: pe_divergence (eps_ttm / consensus EPS) ≥ 1.5 — the
  market prices earnings falling ≥ 1/3. The GSL signature. Veto unless
  the qualitative layer can prove the consensus wrong.
- `cycle_warn`: divergence ≥ 1.25 — earnings-decline risk, requires
  explicit justification to pass.
- `profit_spike`: profit_yoy ≥ +200% — low-base/one-off rebound;
  growth pillar is unreliable, check the base year before believing
  the number.
- `gap:` lines: no consensus-EPS source (HK/US) or no coverage —
  declare the gap in the answer, never improvise the number.
- Then run `intel X` on finalists: 内部人卖出、解禁/减持计划、粉饰
  信号、借钱分红 are vetoes per the 舆情铁律 (2026-09-09). Insider
  synchronized selling + high profit growth = classic sell signal.

### L3 — 大师定性层（AI，per the deepened playbooks 07-12, 17）

For each L2 survivor, run the 7-master qualitative vote — business
model, culture, moat, earn/lose paths (data via `ask X --evidence` +
`intel X`). Each master votes from their own playbook lens:

- Buffett: 三时代定位 + owner earnings + right people
- Munger: 双轨分析 + 三筐 (In/Out/Too Hard) + Lollapalooza
- Graham: 方法边界自检（周期股低 PE 是反向指标）+ 市场先生位置
- Livermore: 关键点 + 最小阻力方向 + 仓位纪律
- Duan: 四连问（生意/文化/价格）+ right people + -50% 测试
- Sheng: 注意力周期 + climax 退出（仅短线视角，仓位 ≤5%）
- 散户乙: 股权思维 + 分红回本算术 + 借钱分红 veto

数据只能成为不买的理由（用户原话 2026-09-06）—— qualitative
vetoes are absolute; qualitative approvals are necessary but never
sufficient alone.

### L4 — 融合裁决（AI 决策权）

Fuse: L1 vote count + L2 survivors + L3 master table + user style
(`recommend --user me` for style gates + holdings exclusion) + market
conditions. NOT a mechanical gate intersection (user principle):
统筹兼顾，最终判断由 AI 掌控并给出明确结论。

Output shape (hard rules):

1. **One verdict, one pick** — the quant+master optimal. Runners-up
   listed with one-line reasons, no case-by-case branching.
2. Master vote table (7 rows: vote + one-line reason).
3. Position discipline per Duan: -50% drawdown tolerance sizing;
   keyhole compatibility check (分红收回路径 for 分红舱 candidates).
4. Data-as-of line + declared gaps verbatim.
5. 短炒警示 if the horizon is ultrashort/short.

## Worked example (2026-09-15, the calibration case)

- L1: 海德股份 4 votes (buffett,munger,graham,duan) but L2 flags
  `profit_spike` (+815.8% profit_yoy, 低基数) → veto.
- L1: GSL 2 votes only — consensus already demoted the graham #1.
  L2 (manual check then; now automated): pe_div ≈ 1.96 → CYCLE_TRAP.
  L3: CEO+CFO 8月26-27日同步卖出 → Duan right-people veto.
- 荣昌生物: L2 caught `pe_div=51.58` → CYCLE_TRAP + profit_spike —
  exactly the signature the code now catches automatically.
- Final pick that day (via manual fusion): 周生生 00116 — 5:1 master
  vote, PE×PB 1.53, 股息率 7.02%, 0 risk flags, gaps declared (HK
  无研报源 / 20% 红利税 / ROE 14% 边界).

## Hard limits

- L2 flags are vetoes unless the AI can *prove* them wrong with
  sourced evidence (先搜公开渠道再定性, 2026-09-14).
- 倍数口径规则 (2026-09-15): every multiple marked TTM/LF/forward,
  computed from the toolkit, never from memory.
- If L1 pool is empty or all finalists are flagged, say so — an
  honest "no qualifying pick today" beats a forced recommendation.

## Field Notes
- [2026-09-15 17:11] (ai) masters-vote L2 live pass only covers A-share (Eastmoney consensus EPS); HK/US rows show gap:no consensus-EPS source instead of a divergence value - state the gap, do not improvise. Calibration 2026-09-15: 海德股份 ranked L1 #1 (4 fundamental-master votes) but carried profit_spike + missing consensus EPS - same shape as the GSL trap; L3/L4 must veto flagged L1 leaders before recommending. HK/US profit_spike rows (Dorian LPG, Gulfport, NUTX, Aurinia) are LLM-cycle/shipping-cycle peaks - treat profit_spike as a hard veto, not a caveat.
- [2026-09-15 20:55] (ai) TCOM 校准（2026-09-15）：L1 四基本面大师全票+表观 PE 5.47 第一，仍被 L2 叙事核查推翻——2025 净利 332.94亿CNY 含 199亿投资利得（占60%），OCF/净利 0.43，真实经营 PE ~13-14x；反垄断罚没 51.79亿+整改拆除'特牌独家+全网最低价'take rate 壁垒，Q2 收入指引放缓至 3-8%。教训：US/HK 无 A 股扣非/粉饰信号时，L2 必须用 web 叙事核查 + OCF/净利<0.6 双指标替代利润质量闸门；表观 PE 第一 ≠ 最被低估。GSL 案之后第二例融合否决。
- [2026-09-16 11:06] (ai) 板手数前置检查（2026-09-16 AH案例）：L4 裁决输出前必须先查 HK 标的 board lot（trade buy 会被引擎拒绝并返回手数），计算最小手数仓位%——江南布衣最优（四票+ROE38.3+派息率110%）但500股/手=18.8%NAV突破单名15%上限，纪律否决执行后改次优波司登（2000股/手=14.9%恰在限内）。教训：基本面最优 ≠ 可执行最优；手数不可分割时'首笔5%分批建仓'失效，须在裁决层就选择手数合规的次优标的，而非成交后才发现超限。A 股 100 股/US 1 股无此问题。
