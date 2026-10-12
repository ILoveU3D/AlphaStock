---
id: monkey-prior-emh-structure
title: 猴子先验：市场有效是先验选择不是数据结论
statement: 二项（猴子）先验有魔数性质——它nullifies the data：若先验正确描述了总体，抽样几乎不提供任何信息（除非抽到接近全体）；价值投资vs指数化的分歧原型即先验分歧：若每个定价错误独立无共同成因（猴子扔球），研究任何一只股票都不增进对市场的认识——抽样无意义；若企业质量有共同生成机制（商业模式/文化/行业结构），单样本携带全体信息——"研究一只股票帮我理解同类"的合法性=拒绝猴子先验；主动管理的元假设：市场有跨股票的逻辑结构，没有这个先验，深研在数学上就是徒劳。
source: "book:概率论沉思录"
status: principle
tags:
  - emh
  - prior
  - market-structure
  - active-management
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:emt-refutation"
  - "refines:market-prices-dividends-4x"
version: 1
created_at: 2026-10-12T16:34:00
updated_at: 2026-10-12T16:34:00
---

## 论证
Jaynes第6章（6.9，5775-5887行）：二项先验（猴子随机扔球入瓮）下的惊人结果——后验估计(6.65)与无数据时的先验估计完全相同："the binomial prior has the magical property that it nullifies the data!... if your prior information about the population is correctly described by the binomial prior, then sampling is futile (it tells you practically nothing about the population) unless you sample practically the whole population."甚至抽样99%对其余1%仍无信息。根源=逻辑独立性在先验中成立则在后验中保持："knowing that any given ball is in fact red, gives one no information whatsoever about any other ball."

迁移：
1. **主动管理的先验地基**：主动研究在数学上成立的前提=市场定价错误有跨股票的共同生成机制（同一批人用同一套叙事犯错、质量因子被同一类资金抛售、商业模式的知识可迁移）——猴子先验下，看一万只股票与看一只股票的信息量相同，指数化是数学正确的选择；价值投资者的每一次跨市场迁移（A→港→美的能力圈复用）都在隐含使用"共同机制"先验。
2. **EMH争论的正确形态**：市场有效不是可以从数据证明/证伪的命题，是关于市场错误结构的先验选择——Shiller式证据（股价波动4倍于股息，参 market-prices-dividends-4x）说服不了真信猴子先验的人，因为他的先验下这些数据本来就无信息；争论应该在先验层打（错误的共同成因是什么），不是在数据层打。
3. **深研的溢出条件**：判断"研究这只股票能否帮我理解那一只"的判据=两家的错误/质量是否有共同生成机制（同行业同监管同资金结构=有；纯题材联动=无——后者是猴子层的相似性，携带不了信息）。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第6.9节，5775-5887行）。EMH争论的先验层重构——与 emt-refutation（Fisher侧：市场先生有效论的历史反驳）和 market-prices-dividends-4x（数据侧）三面合围。尚未经对话验证，status=principle。
