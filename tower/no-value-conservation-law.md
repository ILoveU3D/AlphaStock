---
id: no-value-conservation-law
title: 市场无时间平移对称性，故无价值守恒律
statement: 费曼GM笑话：物理定律时间平移不变，但GM股票不是——因为"环境的相关特征也必须随时间适当修正"这条附加条款在市场里永远无法满足（利率/竞争格局/消费者偏好全部漂移）。没有对称性就没有对应的守恒律（时间平移⟺能量守恒）：市场不存在"α守恒""edge守恒"——过去有效的因子/策略/信息优势会衰减不是因为你做错了什么，是对称性本身不允许它守恒；DCF/贝尔曼方程的平稳性假设=时间平移对称假设（明天的转移规则与今天相同），"这次不一样"的唯一合法判据=指出对称破缺的具体变换是什么，说不出来就默认对称性仍在。
source: "book:费曼物理学讲义"
status: principle
tags:
  - symmetry
  - valuation
  - epistemology
  - physics
links:
  - "derives-from:dcf-universal-law"
  - "derives-from:feynman-first-principles"
  - "refines:this-time-is-different"
  - "tension:gordon-bellman-fixpoint"
  - "tension:dcf-as-optimal-value-function"
version: 1
created_at: 2026-10-12T00:00:00
updated_at: 2026-10-12T00:00:00
---

## 论证

52-2原文："位移在时间上对物理定律没有影响（就我们今天所知——这一切都只是就我们今天所知！）……这一对称性当然意味着：如果某人三个月前买了通用汽车的股票，现在买同样的事也会发生在它身上！"——括号里费曼在开玩笑：GM恰恰不服从时间平移，因为环境的相关特征随时间漂移。物理里可以把环境整体搬走所以对称成立；市场里做不到。

三个推论：①**α衰减是结构性的**：因子/策略/信息优势的失效不需要归因于"执行走样"或"人变多了"——守恒律的缺席本身就保证任何edge都会漏。②**平稳MDP=时间平移对称假设**：gordon-bellman-fixpoint的不动点、gamma-discount的指数权重，全部建立在"明天的转移规则与今天相同"上；当生意规则变化（技术替代/监管重构），对称破缺、价值函数本身改变——重估的正确入口不是调贴现率，而是指出哪条转移规则变了。③**"这次不一样"的举证责任倒置**：说"不一样"的人必须说出对称破缺的具体变换（哪条规则变了），说不出来就按对称仍在处理；同时"就我们今天所知"——价值投资公理也只该以这个置信度持有，要像李杨那样主动设计判决性实验而非等市场替你推翻。

## Field Notes
- [2026-10-12] (ai) 成砖：《费曼物理学讲义·卷一》52-2逐字精读的分形砖；与gordon-bellman-fixpoint/dcf-as-optimal-value-function标tension：平稳性假设的对称性身份首次显式化——三砖共同构成"DCF何时失效"的判据链。
