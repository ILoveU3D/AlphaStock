---
id: limits-to-growth-terminal-value
title: 终值=限制回路的函数
statement: 呈指数成长的实体系统必然同时存在至少一个驱动成长的增强回路和至少一个限制成长的调节回路（有限环境中没有物理系统能永远增长）——因此DCF终值不是增长假设的函数而是限制回路强度的函数：永续g>0隐含断言"限制回路永不被激活"，终值审计的正业=枚举限制回路、估计接管点；指数逼近惊奇：变量以指数形式逼近约束时到达时间出乎意料地短，成长股的顶普遍早于线性外推预期；存量型生意的终值=耗竭折现曲线，不是永续年金。
source: "book:系统之美"
status: principle
tags:
  - dcf
  - terminal-value
  - systems
  - growth
links:
  - "derives-from:dcf-universal-law"
  - "derives-from:thinking-in-systems"
  - "refines:geometric-progression-finite-earth"
  - "applies-to:pe-as-priced-growth"
  - "applies-to:terminal-value-two-forms"
version: 1
created_at: 2026-10-12T03:10:00
updated_at: 2026-10-12T03:10:00
---

## 论证

Meadows 第2章"系统大观园"双资源模型 + 第4章限制因素，是 DCF 终值层的系统论地基：

**成长上限结构（limits-to-growth）**：任何成长的系统——人口、公司、银行账户、谣言、流行病、新产品销售——必然能找到驱动增长的增强回路，也必然能找到最终限制增长的调节回路，"即使尚未占据主导地位，似乎还看不到它们对系统行为的影响，但这些调节回路肯定存在"。映射：DCF 终值给 g>0 的永续假设，等于断言限制回路在整个终值窗口内不被激活——这不是保守与否的口味问题，是可以枚举证伪的结构断言。终值审计的正业从"增长率给多少"换成"限制回路是哪几条、何时接管"。

**不可再生资源模型（石油）**：资本增长越快、崩溃越深越早；资源储量翻一番只延长开采高峰约14年（年资本增长5%下）；价格上涨或技术降本都不能避免崩溃，只堆高崩溃前的资本存量，把最贵的资源永久封在地下。映射：存量型生意（矿、油田、按储量计的牌照）的终值=剩余存量×开采经济性的耗竭折现曲线；加速开采=烧寿；"技术降本延长寿命"在存量型生意里是延迟甚至加速耗竭（见 renewable-vs-depleting-moat）。

**可再生资源模型（渔场）三结局**：①过度开发后平滑收敛均衡（限制回路在关键转折点之前起效）；②围绕均衡振荡（起效慢）；③崩溃（起效太晚+跌破关键转折点，可再生变不可再生）。映射：成熟生意的终值三种命运，判据是限制回路起效速度与关键转折点的赛跑——这一判据在 dominance-shift-two-stage-dcf 展开。

**指数逼近惊奇**："当一个变量以指数级形式逼近一项约束或限制时，其接近限制的时间会出乎意料地短。"空间按存量算（"市场还有十倍空间"），时间按指数倒数算——"还有很大空间"的叙事总是系统性高估剩余时间。

**与 Munger 算术判词的分工**：geometric-progression-finite-earth 给"高增长×有限市场必然相交"的算术（Quant Tech 案例），本砖给结构机制（哪条回路限制、何时接管、转换长什么样）——终值审计的算术层+结构层，两砖合用。

**reverse-DCF 读法升级**：解出的隐含 g 不是"市场预期增长多少"，而是"市场认为限制回路距离接管还有多少年"。g≥15% 的隐含断言=限制回路十年内不接管——这正是 L2 expectation_overreach 否决（Graham 审计 (pe−8.5)/2）的结构版同层物：一个用算术表达，一个用回路表达。

## Field Notes
- [2026-10-12] (ai) 成砖：《系统之美》全书逐字精读（1861行/14.5万字，library/meadows/）分形砖之一，canon #32 终值组主砖；同批 renewable-vs-depleting-moat / dominance-shift-two-stage-dcf / bounded-rationality-mr-market / delay-oscillation-cycle / leverage-hierarchy-paramount / goal-erosion-guidance。
