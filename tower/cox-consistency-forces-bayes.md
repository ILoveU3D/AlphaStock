---
id: cox-consistency-forces-bayes
title: Cox定理：一致性强制贝叶斯
statement: 演绎逻辑是概率推理的极限形式而非并列的另一种东西——Cox定理：任何满足一致性的置信度系统必然同构于概率论（乘法规则=结合性方程的数学强制，不是设计选择）；一致性意味着同一信息+同一规则只能有一个答案：自下而上DCF/可比公司/反推DCF得出不同目标价时，三选一之前先找bug——多路径收敛是合格线不是加分项；"观点不随数据移动"不是有定力，是不自洽。
source: "book:概率论沉思录"
status: principle
tags:
  - bayesian
  - epistemology
  - method
  - valuation
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:bayesian-updating"
  - "refines:elementary-probability-repertoire"
version: 1
created_at: 2026-10-12T16:32:00
updated_at: 2026-10-12T16:32:00
---

## 论证
Jaynes第2章（2.1-2.3，1301-1427行）：合取的可信度不能是各边缘可信度的函数（Boole之失）；Cox从结合性方程F(F(x,y),z)=F(x,F(y,z))（Abel 1826/Aczél定理）推出乘法规则w(AB|C)=w(A|BC)w(B|C)，再由否定一致性推出加法规则——(ABCDEFG|H)的展开方式有天文数字种，满足乘法规则则全部收敛到同一答案。第1章给出三重合意条件：一致性既是内部的（同一问题不同算法同答案）、也是外部的（与演绎逻辑极限衔接）、也是累积的（新证据到来时旧结论按规则移动）。第2章素材③：演绎逻辑=可信度推理的极限形式——概率论包含逻辑作为β→1的特例，不是与逻辑竞争的另一种知识。

迁移（估值纪律）：
1. **多路径收敛义务**：交叉验证不是加分项是合格线——同一个人对同一公司写出三个互相矛盾的目标价，在Cox语言里不是"多元视角"，是至少一条路径上有bug。
2. **定力的重新审计**：贝叶斯机器人不更新不是稳健，是违反一致性；"我从来不看盘"与"我看了数据但结论没变"是两种完全不同的状态，后者需要db级的证据账目支持（参 evidence-decibel-scale）。
3. **频率派的自我矛盾**（第18章再补刀）：一边骂Laplace逐次法则一边用观测频率定义概率，"Anyone who assigns a probability to an event equal to its observed frequency... is doing just what Laplace's rule tells him to do"——研究里"看不起拍脑袋但每天在拍脑袋"的同款结构。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第1-2章，724-2146行）。同批：evidence-decibel-scale / mind-projection-fallacy / max-entropy-ignorance-pricing / prior-as-pseudodata / monkey-prior-emh-structure / ockham-factor-complexity-rent / loss-function-defines-estimate / polarization-trust-prior / outlier-degradation-prior。尚未经对话验证，status=principle。
