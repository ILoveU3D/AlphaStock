---
id: evidence-decibel-scale
title: 证据分贝标度：确信度的对数度量
statement: 证据强度=对数似然比，独立证据按db相加：e(H|DX)=e(H|X)+10·log₁₀[似然比]；直觉在对数尺度上工作（Weber-Fechner定律）——"90%确定"与"99%确定"直觉分不清，10db与20db分得清（10:1对100:1）；研究台账应记db增量不记形容词——"强烈看好"是多少db？坏饼+3db好饼-1db式记账，让证据预算有算术。
source: "book:概率论沉思录"
status: principle
tags:
  - evidence
  - bayesian
  - method
  - research
links:
  - "derives-from:jaynes-probability-logic"
  - "refines:heuristic-syllogism-evidence"
  - "refines:bayesian-updating"
version: 1
created_at: 2026-10-12T16:32:00
updated_at: 2026-10-12T16:32:00
---

## 论证
Jaynes第4章（4.7，3510-3564行）："intuitive human sensations tend to be logarithmic functions of the stimulus"——感官对刺激的响应是对数的，确信度同理："Does the difference between the probability of 0.999 and 0.9999 mean a great deal to you?... the difference between evidence of plus 30 db and plus 40 db does have a clear meaning."图灵二战破译Enigma用的同一标度（deciban，布莱切利园的证据称重单位）。第4章坏饼实验：每条证据是固定的db增量，机器人按加法累积——人类心理实验（偷饼者的指控）测出的正是这种加性结构。

迁移（研究与论战纪律）：
1. **形容词换算义务**：台账里"大幅上调/强烈看好"必须翻译成db——大约+10db=证据翻10倍；写不出db数的判断是没做证据称重的判断。
2. **证据预算的算术**：-10db=1/10——一条强独立利空抵消十条弱利好；"我有一百个理由看好"若每条只有+0.5db，总账+50db，但若有两条-20db的反方证据各自独立成立，论点已经翻负——多空辩论的正确格式是db对账，不是理由计数。
3. **与探索式三段论的接口**：Pólya弱三段论给证据的方向（B真则A更可信），db给证据的大小——方向×大小合起来才是完整的证据称重机；只有方向没有大小的论证（"这印证了我的观点"）欠一个数。

## Field Notes
- [2026-10-12] (ai) 成砖：《概率论沉思录》深读分形（第4.7节+第5章Pólya对接）。图灵deciban是本砖的历史锚点。尚未经对话验证，status=principle。
