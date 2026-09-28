---
id: world-model-reassigns-graphics
title: 世界模型重排图形：渲染从生产者变为教科书
statement: 世界模型=学到的渲染器+学到的物理（latent+扩散到像素，输入输出契约与传统管线相同，中间换成权重）；纯WM训练/推理=加速器友好负载，故WM训练不是全功能GPU的护城河（自我修正2026-09-26：北大EvoPhys 5D世界模型可在MUSA训=沐曦寒武纪亦可切）；图形的存续位置在两处：一、数据管线——渲染为WM提供结构与控制信号（深度/分割/边缘图，Cosmos-Transfer1即以仿真渲染为控制输入），渲染是WM的教科书，WM把教科书读逼真；二、端侧混合渲染——引擎渲确定性部分加WM生成不确定部分同帧并发；且WM正在3D化（3DGS/Marble/空间智能），3D表征是图形母语。WM风险=无守恒律兜底（物理引擎不让能量爆炸，学到的模型长时序漂移），故当前用于数据增广与评估而非替代物理引擎；趋势=手写物理与学习物理合并（Newton可微引擎=NV加DeepMind加迪士尼）。
source: "conversation:2026-09-26"
status: hypothesis
tags:
  - world-model
  - graphics
  - GPU
links:
  - "refines:edge-inference-flips-ai-games"
  - "applies-to:gpu-platform-cocreation"
version: 1
created_at: 2026-09-26T23:34:01
updated_at: 2026-09-26T23:34:01
---

## 论证
（待论证）
