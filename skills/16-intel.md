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
version: 1
updated_at: 2026-09-09T09:40:00
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
