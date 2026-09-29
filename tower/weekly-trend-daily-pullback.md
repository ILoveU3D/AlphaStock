---
id: weekly-trend-daily-pullback
title: 周K趋势+日K回撤=短线入场
statement: 短线高胜率入场手段：宏观（周K）明显上升趋势中，微观（日K）出现回撤时买入，往往短线即盈利——本质是强势延续的回撤买点，赌的是趋势惯性而非折现。地板必须是真生意（生意/文化/否决全过），价格维度不参与地板；交易失败变持有时以reverse DCF诚实备注长期回报压缩。来源：用户早年实战惯用手段（2026-09-29），状态observation，待赛季实战验证后升级。
source: "conversation:2026-09-29"
status: observation
tags:
  - timing
  - momentum
links:
  - "refines:pivotal-points"
version: 2
created_at: 2026-09-29T23:01:27
updated_at: 2026-09-30T00:42:16
---

## 论证
（待论证）

## Field Notes
- [2026-09-30 00:42] (ai) 2026-09-29 代码落地与结构校准（recommendation-v2 Phase 4，masters-vote --horizon short|ultrashort）：weekly_uptrend 操作化为结构条件 MA10W>MA20W 且 26周涨幅>0——刻意不要求 close>MA20W，因陡坡上涨中 -8% 回撤会破 MA20W 而那正是本砖的买点，要求收线在均线上会把甜点区全部过滤掉；pullback_from_high 甜点区定 (-15%,-5%)（config.PULLBACK_SWEET），floor=core_business≥50+weekly_uptrend+无否决；战术排序 short_floor>pullback_sweet>ret_60d，DCF 降级为'失败变持有'诚实备注。待赛季实弹验证胜率后按塔规升 principle/law。
