---
id: reinforcement-learning-sutton
title: 强化学习：决策科学本身
statement: "强化学习=不确定性下序列决策的形式化：智能体-环境-奖励三件套，信用分配(哪个动作导致了延迟的奖励)是核心难题，探索-利用权衡是元难题；奖励假说('智能=最大化累积奖励的能力')把目标设定本身变成工程对象——迁移：投资就是RL问题(部分可观测/延迟奖励/探索利用)，评估任何AI公司先问三件事:它的奖励函数是什么、谁定义的、能不能被hack。"
source: "book:强化学习"
status: principle
tags:
  - ai
  - decision-theory
  - rl
  - method
links:
  - "applies-to:weight-archaeology-reading"
  - "refines:deliberate-practice"
version: 1
created_at: 2026-10-11T00:03:37
updated_at: 2026-10-11T00:03:37
---

﻿## 论证
强化学习=不确定性下序列决策的形式化：智能体-环境-奖励三件套，信用分配（哪个动作导致了延迟的奖励）是核心难题，探索-利用权衡是元难题；奖励假说（Sutton："智能=最大化累积奖励的能力"）把目标设定本身变成工程对象——迁移一：投资就是RL问题（部分可观测/延迟奖励/探索利用），是全书架唯一"决策科学本身"的书；迁移二：评估任何AI公司先问三件事——它的奖励函数是什么、谁定义的、能不能被hack（奖励函数设计错误=Goodhart灾难的工业化）。

## 砖坯（可分形为独立砖）
- 信用分配问题：延迟奖励下归因必然带噪——投资复盘的困难不是道德缺陷是数学结构
- 探索-利用权衡：试错仓与理解仓的比例问题是RL元问题的投资版
- 奖励函数审计：公司/算法/KPI的奖励函数是什么、谁定的、能否被hack——Goodhart的工业化形态
- 考古协议自照：先写后看=行为克隆前的自主rollout，权重考古=离线强化学习

## Field Notes
- [2026-10-11] (ai) 成砖：藏书吸收（Sutton & Barto《强化学习》第2版/Reinforcement Learning: An Introduction）；canon-forty硬科学组成员（AI前沿硬席位，用户v4指定方向）；难度与Jaynes同级属全canon第一梯队，深读排期宜后；status=principle=借来未验证，验证后升 law 并分形。
