---
id: trading
title: Trading — AI Virtual Portfolio Playbook
order: 15
triggers:
  - 虚拟盘
  - 你的盘怎么样
  - 你的资产情况
  - 复盘虚拟盘
  - trade status
commands:
  - trade status
  - trade buy
  - trade sell
  - trade nav
  - trade journal
version: 11
updated_at: 2026-09-08T12:12:40
---

# Playbook

The AI manages its own virtual portfolio (`trade` command group) to
earn real trading experience under real market rules. Dual goal:
**grow NAV** AND **build a sustainable "dividend-style" withdrawal
stream** (提款率 = 累计提款/初始资金 — the happiness metric).

## Daily rhythm

1. **Every conversation start** (after the freshness check): for each
   active season, if `nav_history` last date < today, run
   `python -m value_genie trade nav <id>` to mark NAV. Marking is NOT
   a trade — it never consumes the user-granted daily trade budget.
2. **Trading**: ONLY on explicit user instruction (the user grants
   ~1-2 trade opportunities per day; a forgotten day = no trades).
   Before filling: check freshness (<1h house rule), season rules
   (allowed markets), then decide the position using the user's
   style + master frameworks + self-evolved discipline from Field
   Notes. Always record the rationale in `--note`.
3. **Review**: on user request, read the day's NAV attribution +
   fills, then `trade journal <id> --text "..."` with: why money was
   made/lost, what to repeat, what to avoid. Lessons the user endorses
   go to Field Notes via `skill note trading "..."` (append-only).

## Simulation boundaries (know them, state them)

- Fees are real-world models: CITIC for A-shares (commission 0.025%
  min ¥5, stamp 0.05% sell, transfer 0.001%), ZA Bank for HK/US
  (HK platform max(0.05%, HK$18) + stamp 0.1%; US platform
  max($0.0099/sh, $1.99) capped 1.5%).
- Settlement is simulated strictly: A-share same-day round trip is
  rejected; sell proceeds rebuy same market at T+1; HK proceeds usable
  for FX only at T+2. Holidays are approximated by weekdays.
- Fills execute at `live_price` whenever the user triggers the trade
  (in-session = live tick, out-of-session = latest close — the user
  accepts the quote fetched within the hour).
- NOT simulated: dividends, slippage, margin. Withdrawals ARE the
  dividend proxy: `trade cash <id> withdraw --amount N --currency C
  --note living costs` — pursue raising 提款率 without eating capital.

## Answer shape for "你的盘怎么样"

Verdict first (NAV + day P&L + net return + withdrawal rate), then
positions table, then one line on what the portfolio is positioned
for. Cite the nav-as-of date. Never soften risk observations.

## Field Notes
- [2026-09-05 03:27] (ai) trade CLI --data-dir must point to a dir whose snapshots/<date>/ contains master.csv (not just manifest.json), else resolve_snapshot returns None and fx_rates silently degrades to CNY-only — test fixtures need master.csv too
- [2026-09-05 10:56] (ai) S001 trading framework (2026-09-05, user-endorsed): (1) 选股=急跌错杀 gates ret_20d<=-3 + roe>=10 + rev_yoy>=0，动量分位<10 优先，阴跌不接；榜首若触发非经营性暴利（营收利润背离，如梧桐国际00613）主动排除 (2) 仓位=单仓<=20% NAV，起步总仓位~50%，小资金(2500USD)先活下来 (3) 现金=USD主火力等急跌，HKD留存待港股机会避免双向点差0.6% (4) 赛道偏好AI/半导体(模型-Token-Agent)但A股单手门槛高：存储股一手>4800USD本期买不起，下单前先核手数和单手成本 (5) 每日NAV+journal复盘，赚钱归因、亏钱记教训
- [2026-09-05 11:05] (ai) after every fill and every daily NAV mark, run 	rade dashboard <sid> to refresh trading/dashboards/<sid>.md and commit it — the dashboard is the public, auditable scorecard
- [2026-09-05 11:05] (ai) dashboard refresh rule (supersedes garbled prev note): after every fill and daily NAV mark run 'python -m value_genie trade dashboard <sid>' then git commit trading/dashboards/<sid>.md
- [2026-09-06 23:17] (ai) S001 framework v2 (cashflow-first): (1) 估值锚从 PE 换成 FCF 收益率（DCF 一阶近似，年报口径）; (2) 买入前四问写进 --note：负债怎么来的、准备怎么处理？现金流怎么来的、准备怎么处理？; (3) borrowed_dividend=1 一票否决——A 股机制：分红是再融资资格的敲门砖，现金流出问题的公司保资格式分红（分红出去的钱从筹资端回来）; (4) 烟蒂备用仓（银行/保险/稳健）必须过 graham 屏（pe_pb<=22.5），格雷厄姆安全边际算术，不做价格目标
- [2026-09-06 23:50] (ai) MANDATE 2026-09-06: every trade buy/sell decision note and journal entry must cite the master-evaluation layer (gates passed/failed + business model / culture / earn-lose paths); a note containing only factor numbers is invalid
- [2026-09-06 23:54] (ai) Update 2026-09-06: master-evaluation mandate softened by user to standard-flow-not-enforced; position discipline added (Duan: enter only if -50% drawdown tolerable, size accordingly); Duan's principle — data is only ever a reason NOT to buy, the buy reason must be future cash flows from business model + culture
- [2026-09-07 14:10] (ai) HK lot pre-check rule (2026-09-07): before running master evaluation on an HK candidate, verify board_lot x price <= 20% NAV (~3.9k HKD on s001's 2.5k USD book). 中国宏桥 01378 lot=500 (11,590 HKD per hand = 47% of NAV) passed every gate (my style #1 valid HK candidate, graham PE×PB=10.8, FCF yield 14.2%) then the buy order was rejected at lot validation — same miss class as 六福(1000股/手) and A股存储股(一手>4800USD). Gate the lot first, evaluate second
- [2026-09-08 12:12] (ai) 康臣药业01681 lot=1000 → 13,200 HKD/手 = NAV68%：第4只手数封杀（宏桥500/六福1000/中铝2000/康臣1000）。lot×price≤20%NAV 前置硬筛已生效——本次在深研阶段拦截而非下单被拒，流程较09-07进化
- [2026-09-08 12:12] (ai) 非经营性暴利红旗机械化（2026-09-08）：净利>毛利 ⇒ 直接排除。炜冈科技001256 H1净利1.61亿>毛利1.04亿（营收3.09亿×毛利33.6%）=投资收益/非经常项主导，与梧桐国际 net margin 959% 同源。错杀筛遇 +100% 以上利润增速先做这道除法
