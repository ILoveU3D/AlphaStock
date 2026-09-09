---
id: intel
title: Intel — 舆情情报 Playbook
order: 16
triggers:
  - 舆情
  - 情报
  - 公告
  - 解禁
  - 研报
  - 评级
  - 财报解读
  - 事件雷达
commands:
  - intel X
  - intel X --json
version: 7
updated_at: 2026-09-09T22:39:19
---

# Playbook

intel X 输出五个板块（事件雷达 / 公告或披露文件时间线 / 财报信号 /
投行评级 / 新闻时间线）。市场覆盖：A 全板块；HK 公告+新闻（东财港股
镜像），研报无源显式降级；US EDGAR 披露文件 + 新闻 + stockanalysis
一致评级。雷达批表（解禁/减持/回购/定增/预告/预约）仅 A 股。

## AI 解读框架
- 解禁：看结构（大股东 vs 财投、成本、占比）；30 天 ≥5% 是红旗。
- 评级：方向 + 调整轨迹（连续上调/下调比单次动作重要）；目标价
  变化轨迹比绝对值重要。
- 粉饰信号：单看一项不定罪，组合出现（应收+存货+OCF 缺口）才升级。
- 事件与周期：解禁/财报日对 short horizon 是催化，对 long horizon
  通常只是噪音——按 ask X 的四周期剖面分别说。
- HK 研报缺失时：用新闻时间线里的评级标题（"大摩下调目标价"）做
  替代证据，并在答案中说明数据缺口。

## Field Notes

- (2026-09-09) 港股研报端点不存在：reportapi qType=0/1 对 HK 代码均
  0 hits；hkStock 页面 XHR 藏在 minified main.js 中未定位——HK 评级
  走新闻时间线降级，找到端点后再补。
- (2026-09-09) stockanalysis.com 评级页为 Next.js flight data，无公开
  API：正则引用 bare key + 前导零浮点（stars:.6）两步修复后
  json.loads 可解析；无评级页 404 → fail-closed None。
- (2026-09-09) np-listapi 美股前缀：105=NASDAQ、106=NYSE 有新闻，
  107=AMEX 返回空 data——快照外美股自动按 105→106 试。
- (2026-09-09) EDGAR submissions.filings.recent 覆盖近千条提交（新→
  旧），90 天窗口无需分页；144（拟议内部人出售）是噪音已过滤。
- [2026-09-09 07:56] (ai) 快照无雷达行 ≠ bug：雷达行只在 master/watchlist 里查（漏斗 ~200 只 + 持仓兜底），漏斗外大盘股（如 00700、600519）正常显示无雷达行；A 股事件明细仍从全市场批表按 code 过滤可用。
- [2026-09-09 20:52] (ai) EDGAR Form4内部人交易深挖:submissions API的primaryDocument是HTML渲染页,需fetch {accession}/index.json选.xml原始文件才能解析transactionCode;code S=卖出/A=授予/P=买入/F=税扣,高管小量多人均衡卖出=RSU/10b5-1常规,大股东持续大量卖出才是否决级红旗
- [2026-09-09 21:47] (ai) US ratings源偶发失败报ratings source failed(2026-09-09 CARG)——EDGAR披露/新闻通道正常时勿阻塞决策,可稍后重试
- [2026-09-09 22:34] (ai) 舆情四要求铁律(用户2026-09-09,原话记住):财报一定要能看懂,公告一定要知道含义,新闻一定要有时效性,投研报告一定要全面且权威有参考性;往往公告和新闻对短线的影响更大——短线决策时公告/新闻优先级高于研报,持仓期每日复查这两条通道
- [2026-09-09 22:34] (ai) 解释层已落地(2026-09-10):intel X 新增[财报速读](master行+a_financials白话解读;亏损期扣非占比/OCF净利比值标'不适用'只给绝对值,摩尔线程实跑修正)+[新闻热度](今日/3天/7天vs前7天→升温/降温/持平;骤升=注意力高潮预警即兑现离场)+[研报汇总](每机构只取最新评级:分布/上调下调/EPS一致/目标价区间/主力机构名);A/HK公告与US EDGAR文件自动带〔含义〕标签(ANN_MEANINGS含港股繁体/EDGAR_FORM_MEANINGS);研报pageSize50→100;6-K/20-F纳入重要文件(中概ADR主披露通道,TCOM实跑0条发现)
- [2026-09-09 22:39] (ai) np-listapi HK新闻偶发返回空列表(2026-09-10腾讯00700实跑0条,前日P3验证同股正常)——空列表与源失败难区分;遇到0条新闻的港股先重跑一次再下结论,勿把'无新闻'当'无关注'写进复盘
