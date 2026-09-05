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
version: 5
updated_at: 2026-09-05T11:05:54
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
