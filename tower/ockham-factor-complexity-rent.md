---
id: ockham-factor-complexity-rent
title: 奥卡姆因子：想象参数付复杂度租金
statement: 模型比较的自动剃刀：加参数θn+1→先验概率摊薄到更大的参数空间→若老模型已能解释数据（新参数的ML点接近零）→新模型对数据的证据权重更低——Bayes"will, like Ockham, tell us to prefer the old model"；反转条件=新参数的似然增益盖过摊薄（数据已在尖叫：新业务收入占比持续爬升）；研报里每个想象参数（协同效应/平台化/出海空间/第二曲线）先问它的ML证据离零有多远——离零近的想象参数是负资产；例外：当新参数伴随对老参数的重新认识时（转型公司的新业务改变老业务的含义），复杂化可能同时更可信。
source: "book:概率论沉思录"
status: principle
tags:
  - model-comparison
  - complexity
  - valuation
  - method
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:convergent-parsimony-verification"
  - "applies-to:quant-paradox"
version: 1
created_at: 2026-10-12T16:34:00
updated_at: 2026-10-12T16:34:00
---

## 论证
Jaynes第20章（20.3末尾，20456-20487行）：加参数θn+1的机制——先验概率摊薄到更大参数空间；若老模型已能解释数据（ML点在θn+1=0附近），新模型p(D|M)更低，"then as a general rule Bayes' theorem will, like Ockham, tell us to prefer the old model"；反转条件——ML点远离θn+1=0（显著性检验显著）时新参数的似然增益才盖过先验摊薄。20.2（20338-20374行）：公平法官与残酷现实主义者——框架选择要配参数先验，参数空间没有天然的无信息测度。20.3（20415-20439行）：简单性的平反——Ockham优势是可信度结构而非参数计数的教条。

迁移：
1. **想象参数的审计问题**：给研报里的每个"想象参数"（协同效应/平台化/出海空间/AI赋能）打分前先问：它的ML证据离零多远？"市场没为故事付钱"在模型比较语言里=θn+1的ML值接近零——此时为它加参数=自动降低整个估值故事的证据权重，想象参数是负资产。
2. **复杂化的回本条件**：只有数据已经在尖叫（新业务收入占比持续爬升、订单能见度连续兑现）时复杂化才回本——第二曲线必须是已被观测的曲线，不能只是被讲述的曲线。
3. **合法例外**：Bayes偶尔违反Ockham（新参数伴随对老参数的重新认识）——转型公司"新业务"参数改变了"老业务"参数的含义（同一批客户/同一套产能的双计数问题），此时两参数模型比单参数模型同时更简单更可信；判据不是参数个数而是叙事是否重新解释了旧数据。
4. **量化侧**：因子模型每加一个因子付一次摊薄——样本内R²的上升不付租金，样本外预测才是租金的支付方（参 quant-paradox）。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第20章，20328-20820行）。给 convergent-parsimony-verification（盲眼钟表匠侧：多重独立证据链的简约原则）补上贝叶斯模型比较的定量机制。尚未经对话验证，status=principle。
