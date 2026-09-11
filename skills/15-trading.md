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
version: 24
updated_at: 2026-09-11T23:39:51
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
- [2026-09-08 23:08] (ai) fee-drag math on small book (2026-09-08, s001): 4 days in, friction=-10.26USD (fees 7.29 + FX spread 2.97) vs market P&L -3.82 → 73% of total loss is friction; venue entry costs on a 2.5k USD book: HK min fee 18HKD≈0.97% of a 2k HKD position (worst venue for small orders), US .99 min≈0.4-0.5%, A-share 5CNY≈0.2%; HK adds should be sized >=2k HKD or skipped; minimize FX round-trips (0.3% per leg)
- [2026-09-09 11:57] (ai) SB suggest(searchapi.eastmoney.com)整日挂返回空HTML时,代码形式传参(002001/06831)仍可正常解析并成交;午休盘外单引擎自动取当日最新价(今晨收盘)成交,标记session=out,无需等13:00开盘
- [2026-09-09 16:15] (ai) 舆情强制参与铁律(2026-09-09实战验证): 持仓复盘必须跑intel X，首日即抓到巨人网络大股东减持14亿红旗(营收+182%与内部人减持背离)，判断从持有升级为减仓；只跑ask --evidence不跑intel的复盘=不完整，AI不得遗漏；明日开盘优先处置舆情红旗仓位
- [2026-09-09 22:07] (ai) s002短线法则(用户2026-09-09):舆情升级为主动信号——开仓前intel查催化剂(事件日历/评级动量),持仓期每日跟踪新闻热度/披露边际变化;解禁/减持日期作为持仓期约束(事件前离场);舆情红旗对短线更是命门:止损位近,一次跳空直接击穿
- [2026-09-09 22:11] (ai) 元法则(用户2026-09-09,一定要记住):投资操作法则只通过CLI skill note记入skill Field Notes,不写本地memory文件——skills随git仓库走且每个未来agent必读=系统自我提升的唯一渠道,本地记录无法提升自我
- [2026-09-10 14:05] (ai) 榜首红旗否决案例(2026-09-10):sheng双窗口榜首海通发展(momentum 100,当日+11.6%)被intel三重红旗一票否决——30天解禁68.1%(短线持仓期约束:事件前必须离场)+粉饰信号2项(应收/存货增速远超营收)+当日新闻'成交额创上市以来新高'。法则:榜首不等于买点,红旗否决先于动量排序;新闻标题含'成交额创上市/历史新高'可直接当注意力高潮信号用;intel新闻热度'前7天 vs 近7天'条数对比=注意力周期量化分级抓手——2→30=升温早段可进,9→41+成交额新高=高潮回避
- [2026-09-10 22:24] (ai) 备选仓规则(2026-09-10):等待型备选的进场触发条件必须事前显式写明,避免临场主观裁量——FUTU触发器=ret_5d转正或单日放量反转+3%以上,触发时先重跑intel再进场;触发未到=持有现金,备选不会因为等了几天就失效(同宏桥手数封杀批次)
- [2026-09-10 22:25] (ai) s001国别集中度前置检查(2026-09-10):开仓前数一遍中国beta仓位数(中概ADR+A股+港股中国公司),当前4/5仓中国关联——BZ(BOSS直聘)过全部gates仍放弃即因此;下一仓优先非中国beta标的,与行业分散同属仓位纪律层
- [2026-09-11 10:31] (ai) 机械红旗升级+止损日纪律(2026-09-11,北方铜业跌停止损实战): (1)净利率>100%直接机械否决——亚太资源01104净利率398.5%(毛利率仅9.4%)系'净利>毛利'同源的非经营性暴利变体,sheng双榜首PE1.3的数据完美陷阱,榜首要先做这道除法 (2)机械止损执行当日不开新注——防报复性交易,与备选仓显式触发器同族约束;止损日正确的动作是收缩不是马上再进场 (3)北方铜业跌停封板(-10.01%)被事前止损线14.756接走:机械止损的真实价值在极端日用足
- [2026-09-11 10:38] (ai) trade status net% 分母 bug(2026-09-11 发现): deposit 注资后 initial_capital 字段未同步更新(仍为2500),status 的 net% 除以旧本金而非 2500+deposited=7500,两期净亏被夸大约3倍(s001 显示-6.83%实际按7500算是-2.27%)——向用户汇报盈亏时必须按 totals 重算真实净收益率,勿直接引用 status net%
- [2026-09-11 14:04] (ai) 方法论三修正(2026-09-11用户质询'是不是方法论错了'后直面归因): (1)单一叙事beta前置硬gate——建仓前检查金属/航运等单一叙事敞口,超限直接禁入,'去X化'必须是本注纪律不是下一注备忘(铜业-337CNY教训:09-10明知CDE白银在场仍建39%金属敞口,跌停是运气,超限暴露是明知故犯=罚金非学费) (2)短线注note禁写基本面理由——只留动量证据/热度分级/止损线,基本面论证会诱发'基本面没坏不该卖'的犹豫从而腐蚀止损纪律 (3)热度分级量化——近7天vs前7天倍数+绝对条数双阈值替代'早段/高潮'主观词; 附:巨人-181CNY系舆情铁律(09-09)确立前的流程缺口,铁律后零复发;连续三次'数据完美陷阱'(巨人烟蒂数据/亚太资源PE1.3/粤桂三红旗)说明筛选层光泽与可投资性存在系统性gap,红旗检查应前置成screen硬gate而非被动否决
- [2026-09-11 23:39] (ai) 止损日纪律跨窗口执行(2026-09-11美股窗口首例):机械止损执行后,同一交易日的后续所有市场窗口(A股早盘->美股夜盘)一律不开新注,跨窗口纪律一致性优先于机会成本;sheng榜单有合格候选也 abstain——收缩不是马上再进场
- [2026-09-11 23:39] (ai) 每日复盘蒸馏闭环(用户2026-09-11确立):每个交易日的journal复盘当天必须把新教训蒸馏成Field Notes条目——journal=当日快照,Field Notes=跨season复利资产,复盘只写journal不落skill=流失;当日无可蒸馏教训也无需强行凑条,但任何规则首次执行/首次失效/首次边界情形必须当天记录
