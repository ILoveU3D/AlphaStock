---
id: prior-as-pseudodata
title: 先验=伪数据：Laplace法则与N≫K准则
statement: 先验不是玄学是压缩的过往证据——均匀先验携带两份伪观测的权重：p=(r+1)/(n+2)=n·(r/n)+2·(1/2)的加权平均；"我了解这门生意"的量化形式=先验值几份财报的伪观测数，直接决定新数据稀释后验的速度；N≫K准则：数据量远超假设复杂度时先验被淹没（成熟公司估值中历史数据压倒宏观叙事），N≪K时先验的诚实性比数据的精致度重要一个数量级——"3年历史跑了个漂亮的多元回归"=假装N≫K；数据与先验打架=复活备择假设的警报，不是数据的失败。
source: "book:概率论沉思录"
status: principle
tags:
  - prior
  - base-rate
  - method
  - valuation
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:outside-view-growth-prior"
  - "refines:weight-archaeology-reading"
version: 1
created_at: 2026-10-12T16:32:00
updated_at: 2026-10-12T16:32:00
---

## 论证
Jaynes第6章（5441-5510+5685-5698行）：Laplace逐次法则(r+1)/(n+2)改写为(6.46)——"the uniform prior carries a weight corresponding to two observations"，方差p(1−p)/(n+3)；1600人民调±3%的反推验证(6.36)——小样本估计必须向中性缩水，先验占两票。第18章（18.10，19177-19191行）N≫K准则："as soon as the number of observations N is large compared with the number of hypotheses K, then the probability assigned to any particular hypothesis depends, for all practical purposes, only on what we have observed"——小样本用逐次法则数值很"soft"但方向正确。第8章（9376-9396行）先验何时重要：数据与先验打架=数据在悄悄复活你没列出的备择假设，是警报不是尴尬。Bibliography批注（Walley 1991）：先验的可用性"determined not by any property of the prior alone, but by the joint behavior of the prior, the model, and the data"——单个假设不能孤立评判，增长率+WACC+数据三者联合决定结论是否可用。

迁移：
1. **"我懂这门生意"的换算**：先验强度的正确单位是伪观测数（相当于几份财报）；两位分析师看同一份新财报后分歧的大小，由各自先验的伪观测数决定——分歧不是谁不理性，是先验权重不同（参 polarization-trust-prior）。
2. **N与K的显式对账**：新公司/新业务估值先问N（几年可验证数据）对K（假设里藏了几个自由度：终局份额×利润率×再投资×折现率×政策）——N≪K时结论几乎完全由先验决定，此时先验的诚实性（外推历史还是编造未来）比回归的精致度重要一个数量级。
3. **打架即警报**：新数据与你的先验剧烈冲突时，第一动作不是捍卫先验也不是抛弃先验，而是列出被复活的备择假设清单（周期顶/口径变化/造假/结构转型）——参 outlier-degradation-prior。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第6章+第8章+18.10+附录A）。给 outside-view（参考类别=先验的来源侧）补上数学形式（伪观测权重）。尚未经对话验证，status=principle。
