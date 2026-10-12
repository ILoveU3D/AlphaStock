---
id: max-entropy-ignorance-pricing
title: 最大熵=无知定价：探索期的诚实纪律
statement: 最大熵原理是"nonspeculative procedure"——只承认样本空间与已有数据内的约束，不引用任何额外假设，"protects us against drawing conclusions not warranted by the data"；研究两阶段纪律：探索期（无模型）用最大熵陈述——"已知约束下最诚实的分布是什么"，不编造结构；成熟期（有模型+先验）才用贝叶斯称重；只约束你真有的信息（均值/方差）是诚实的，预测失败=发现新约束，失败反而有用。
source: "book:概率论沉思录"
status: principle
tags:
  - entropy
  - ignorance
  - method
  - research
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:entropy-expectation-gap"
  - "refines:rough-estimate-mandatory"
version: 1
created_at: 2026-10-12T16:32:00
updated_at: 2026-10-12T16:32:00
---

## 论证
Jaynes Preface（548-563行）："Before Bayesian methods can be used, a problem must be developed beyond the 'exploratory phase'... Problems at this level call for more primitive means of assigning probabilities directly out of our incomplete information. For this purpose, the Principle of maximum entropy has at present the clearest theoretical justification... maximum entropy is a nonspeculative procedure, in the sense that it invokes no hypotheses beyond the sample space and the evidence that is in the available data."第11章给公理化地基：三个desiderata（唯一性/一致性/子集独立）数学强制H=−∑p log p（11.1-11.2）；Wallis直观推导：最大熵解=猴子随机分配里最概然的那个（11.3）；对四大质疑的正面回应（11.8）：无知量化≠不可靠（质疑①）、与频率有精确连接（②）、只约束均值是诚实的（③）、不同信息不同结果且矛盾自动暴露（④）、预测失败=新约束的发现（⑤）。

迁移（研究流程）：
1. **新领域初判的纪律**：新行业/新公司初判时，正确姿势是MaxEnt式陈述——列出真约束（生态现状/产能/资本开支/渗透率上限），在约束内给出最无想象的分布，而不是直接编一个终局市占率；"约束下的诚实分布"是探索期唯一不欠债的输出。
2. **两阶段切换条件**：从MaxEnt切到贝叶斯的标志=模型已建立且先验可追溯（此时证据按db称重）；在此之前的"目标价"都应携带"探索期"标签——把探索期的最大熵分布当成熟期后验出售，是研报最常见的身份欺诈。
3. **失败的用途**：MaxEnt预测失败意味着发现了未建模的约束（新竞争者/新渠道/新监管）——失败是信息不是耻辱，前提是当初真的用了最大熵（没有隐藏结构假设）。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（Preface+第11章，548-563+11578-12749行）。与熵砖（entropy-expectation-gap，Gleick侧）构成对偶：那块讲"信息=惊讶度"，这块讲"无知=最大熵分布"。尚未经对话验证，status=principle。
