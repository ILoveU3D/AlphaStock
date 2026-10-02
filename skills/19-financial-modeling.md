---
id: financial-modeling
title: Financial Modeling — 财务建模 Playbook
order: 19
triggers:
  - 建模
  - 财务模型
  - DCF
  - 估值模型
  - comps
  - 可比公司
commands:
  - model fetch X
  - model build X
  - model show X
  - model set X
  - model list
version: 1
updated_at: 2026-10-02T12:00:00
---

# 19 · Financial Modeling（财务建模）

Triggers: 建模 / 财务模型 / DCF / 估值模型 / comps / 可比公司 / model X

## 何时建模（AI 自律触发条件）

- **必建**: masters-vote / recommend 的 L3 深评短名单候选，进 L4 裁决前
- **必建**: holding-deep-review 中论点漂移或大幅波动的持仓；钥匙孔季度证伪检查
- **选建**: 用户问"评价 X"且无模型或模型 STALE
- **不建**: 漏斗宽池扫描；D4 战术/短炒模式（DCF 已降级为"失败变持有"注记）

## 工作流

1. `python -m value_genie model fetch X` 拉多年三表（history.json，缺科目看 gaps）
2. 读材料：`profile show X` + `intel X` + `models/<mkt>/<code>/raw/` 中的审计意见/尽调投喂
3. 首次 `model build X` 生成默认假设（历史中位数）；读材料后用
   `model set X base.revenue_growth=0.25,0.22,0.18,0.15,0.12 wacc=0.11 --reason "读年报审计意见后上调"`
   调整（--reason 必填，进 changelog）
4. `model build X` 重算 → 三情景×概率加权价值 + 敏感性 + comps 隐含区间
5. 论证纪律：DCF 第一（reverse-DCF 隐含预期为起点）；comps 只作参照互证，不作买入论证
6. STALE（新报告期）→ 重新 fetch + 复核假设 + build；模型结果经 DCF 钩进入 core_dcf（core_gaps 标 DCF_MODELED）

## 红线

- 缺科目（A股股本、HK capex/现金负债）绝不编造——gaps 声明，per-share 不可信时说不可信
- A 股模型必手填 assumptions.shares（F10 股本）后才可信 per-share 输出
- models/ 是本地-only 专有判断，永不推送
