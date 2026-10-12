---
id: outlier-degradation-prior
title: 离群值=数据源故障率先验：教条模型的u=1陷阱
statement: 极端数据点的处理不存在"客观正确"答案，只存在"你对这个数据源的故障率先验"：知道仪器易坏→离群值大概率是故障（该扔），绝对信任仪器→是重大发现（必须保留）——Chauvenet等任意阈值准则忽略的正是这唯一关键因素；正确框架=好数据分布+坏数据分布+纯度参数的贝叶斯混合，行为自动变成温和降权（既不全信也不全扔）；概率论特有的陷阱：没建模的特征不是被忽略而是被默认假设为零——估值框架不显式建模"财报可能坏"=教条宣称所有数据真实，一个造假季度会把全年盈利预测拖走N个σ；坏数据出现的模式本身携带公司信息（连续Q4爆雷vs孤立爆雷），扔数据前先读模式。
source: "book:概率论沉思录"
status: principle
tags:
  - outliers
  - data-quality
  - fraud
  - modeling
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:dollop-by-dollop-fraud-economics"
  - "refines:model-sanity-four-checks"
version: 1
created_at: 2026-10-12T16:34:00
updated_at: 2026-10-12T16:34:00
---

## 论证
Jaynes第21章（21.1，20784-20834行）：两个伦理化立场——(I)仪器坏了该剔除防污染 vs (II)扔数据=作弊、离群值"may well be the most significant datum you have"；Jaynes的调和："they reflect different prior information about the apparatus. This is the crucial factor – ignored in all the aforementioned criteria."21.5-21.7（20894-21110行）：两模型混合——好数据G(x|θ)+坏数据B(x|η)+纯度u的混合(21.8)；准似然展开(21.22)=按先验概率加权"每种子集可能坏"的所有情形，"every detail of our prior knowledge about how the data are being generated is captured"；单模型G的错误在于它"proclaims dogmatically: I know in advance that u=1... no evidence from the data could change my mind"，于是离群值把估计拉走10σ。关键警句："In other areas of applied mathematics, failure to notice some feature means only that it will not be taken into account. In probability theory, failure to notice some feature may be tantamount to making irrational assumptions about it."（没注意某特征≈对它做了非理性假设）。纯离群值判据（21.6）：确定坏的就该扔，除非"产生这个离群值的概率依赖于θ"——此时离群值的模式本身携带参数信息。

迁移：
1. **数据源分层先于数据规则**：对异常季报/单日异动/离谱指引的处理，第一步不是套规则（"超3σ必剔除/必保留"）而是给数据源定故障率——成熟审计+大所覆盖+口径稳定的公司，异常更可能是真信号（该追）；历史劣迹+小所审计+口径常变，异常更可能是噪声或操纵（该降权）。
2. **u=1陷阱**：估值模型不显式建模"财报可能坏"（造假/一次性损益/口径变化），等于宣称教条的u=1——此时一个造假季度会把全年预测拖走N个标准差，这是模型的错不是数据的错；正确结构=好数据+坏数据+纯度的混合，对可疑季度自动温和降权（与L2红旗层的profit_spike/expectation_overreach否决同构）。
3. **没讨论≠中性**：概率论里未建模的控制权/汇率/关联交易不是被忽略，是被默认假设为零——估值清单的"未提及项"就是隐性假设清单。
4. **坏数据的模式即信息**：连续四个Q4爆雷vs孤立一次爆雷，对公司的含义完全不同（前者是模式=渠道压货的季节性规律，后者可能是事件）——扔数据前先读模式。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第21章，20821-21158行）。给 dollop-by-dollop-fraud-economics（造假经济学）补上数据处理侧的数学结构。尚未经对话验证，status=principle。
