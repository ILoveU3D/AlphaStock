---
id: horizon-framework
title: Time-Horizon Framework (超短线/短线/中线/长线)
order: 14
triggers:
  - 短期内最推荐
  - 短期内最被低估
  - 适合中长期持有
  - 适合长期持有吗
  - 超短线
  - 短线有什么机会
  - 中线
  - 长线
  - 持有几年
commands:
  - screen --horizon ultrashort|short|mid|long
  - ask X [--horizon H]
version: 1
updated_at: 2026-09-01T12:00:00
---

# Playbook

Answer holding-period-scoped questions with the horizon lens. The
toolkit measures; you judge. The quantitative layer (factor weights +
momentum windows per horizon) is only half the answer — the other half
is the qualitative overlay below, which no factor table can produce.

## The four horizons

| id | window | weights essence | momentum window |
|---|---|---|---|
| ultrashort | 1-10 交易日 | 注意力/动量为王 | ret_5d+ret_20d |
| short | 10日-3月 | 趋势确认+修复启动 | ret_20d+ret_60d |
| mid | 3月-3年 | 估值修复+业绩兑现 | ret_60d+ret_250d |
| long | 3年+ | 商业模式+现金流 | （权重为0） |

Master mapping (each master has a natural horizon): Buffett/Munger/Duan
→ long, Graham → mid, Livermore → short, Sun → ultrashort. When the
user asks "X 会怎么看 Y", answer within that master's natural horizon.

## Commands

1. "短期内最推荐/最被低估的股票是什么？"
   `python -m value_genie screen --horizon short --top 20`
   (最被低估 → add `--set value=0.4 momentum=0.3` or screen value-heavy
   then check short-window momentum on survivors via `ask --evidence`.)
2. "超短线有什么机会？"
   `python -m value_genie screen --horizon ultrashort --top 20`
3. "X 适合中长期持有吗？"
   `python -m value_genie ask X` — read the four-horizon profile, then
   apply the qualitative overlay below, then commit to a judgment.
4. "过巴菲特门槛的股票里短线动量最好的是谁？"
   `python -m value_genie screen --strategy buffett --horizon short`

## Qualitative overlay (the part factors cannot see)

- ultrashort/short: 事件、情绪、地缘政治、流动性、注意力周期。
  `ret_5d`/`ret_20d`/`vol_20d` 来自 ask --json 的 metrics。
  **每条回答必须带警示**：本工具箱的价值基因不提倡超短线/短线
  交易；给出仓位纪律与退出条件（利弗莫尔的 −10% 线或注意力高潮
  退出），并明确说明短周期受不可预测的突发事件支配。
- mid: 业绩兑现节奏（未来 4-8 个季度）、催化剂（回购/分红/政策/
  行业拐点）、行业景气位置、估值修复的路线（为什么市场会纠错、
  什么事件触发纠错）。
- long: 商业模式耐久性、护城河（毛利率/ROE 的持续性而非水平）、
  技术路线之争、时代趋势。寒武纪模板：中期（3年）AI 推理需求
  爆发是可量化的（growth 因子强）；长期（10年）NPU 路线 vs 通用
  计算/机器人等新场景的路线风险是质性判断 —— 两层结论可以不同，
  "适合中线持有但不适合长线持有"是合法且常见的答案。

## Answer template (per-horizon suitability)

> [单句结论：X 在 H 周期适合/不适合持有]. Horizon profile（vs 本市场
> gated universe）：超短线 S1（P1 百分位）/ 短线 S2（P2）/ 中线 S3
> （P3）/ 长线 S4（P4）—— [最弱周期是 Hw，因为…]. 质性层：[按上面
> checklist 逐项判断，量化覆盖不了的部分明确说"这是我的判断"].
> [风险旗标 verbatim]. Data as of [snapshot date].

## Field Notes
