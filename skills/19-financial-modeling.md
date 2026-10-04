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
  - model gather X
  - model write X
  - model show X
  - model lint X
  - model status
  - model fetch X
  - model build X
  - model set X
  - model list
version: 7
updated_at: 2026-10-04T18:15:32
---

# 19 · Financial Modeling（财务建模）

Triggers: 建模 / 财务模型 / DCF / 估值模型 / comps / 可比公司 / model X

## 范式（2026-10-03 用户定稿）

**模型 = AI 对一家公司的完整认知档案，不是估值计算器。** AI 一家一家
单独建模，无脚本批量；脚本是 AI 的手，不是 AI 的替代。建模中缺工具
就加工具，缺砖就 `tower add`——通过全市场建模强化量化工具和巴别塔，
一切为了让 DCF 北极星更强。

产物本地-only（models/，永不推送）、可更新、可复用、动态输入输出；
**信息量必须 ≥ 该公司财报，否则是不合格建模**（`model lint` 机器校验：
三件套完整性 + 世界叙事权重依据 + 文本量 ≥ 素材 30%）。

## 工作流（协作循环，不是流水线）

1. `model gather X [--peers 688256,688041]` —— 机器聚合素材到
   `models/<mkt>/<code>/raw/`：上市以来全历史三表 + intel 事件 +
   公司自述原文 + 年报文本（A：MD&A/主营构成/核心题材/机构预测/
   高管简历；US：10-K Item1/7）+ 法定披露全文（A：历年年报+招股
   书 PDF，raw/filings/）+ 同行（master 缺失时 AI 显式指定同行集）
2. **AI 读素材**：raw/ 全部 + `intel X` + 塔砖（`tower search` 相关
   主题——创新/飞轮/文化先查塔，如 gpu-platform-cocreation 的
   共创循环写法）
3. `model write X key=@file --reason "..."` —— AI 写理解层
   （model.json）。机器只强制三件套：
   - `business_flywheel.text` —— 钱从哪来、怎么转、哪环会断
   - `culture.vision / current_state / evidence` —— 愿景/现状/行为证据
   - `reverse_dcf.implied_world / my_world / gap` —— 现价隐含的
     世界 vs 我信的世界
   其余全开放：`world_narratives`（每个=完整世界假设"发生了什么→
   飞轮第N环接通"，weight 由 AI 估且 `weight_basis` 必填——权重即
   论证）、`dimensions`（AI 自由维度，50个1000个都行）、
   `falsification_monitor`
4. `model lint X` —— 合格线校验；INCOMPLETE 的档案不进 core_dcf 钩
5. `model build X`（估值层：情景×概率 FCFF + comps，旧机制）——
   世界叙事的 drivers 落到 assumptions 后跑；show 同时呈现档案+估值
6. `model status` —— 全市场建模覆盖度

## 何时建模（AI 自律触发条件）

- **必建**: masters-vote / recommend 的 L3 深评短名单候选，进 L4 裁决前
- **必建**: holding-deep-review 中论点漂移或大幅波动的持仓；钥匙孔季度证伪检查
- **全市场战役**: 钥匙孔/持仓 → L3 → 漏斗候选 → 按行业能力圈逐家推进
- **不建**: 漏斗宽池扫描；D4 战术/短炒模式

## 红线

- 理解层只能由 AI 写——机器聚合素材但永不生成 model.json 的内容
- 权重没有 weight_basis = 占位值，输出打标，不算 AI 判断
- 缺科目（A股股本、HK capex/现金负债）绝不编造——gaps 声明
-  comps/倍数只作互证参照，不作买入论证（DCF 第一）
- resolve 对 out-of-universe 新股：代码形式现在直接用（2026-10-04
  修复：`A:688795` / `HK:02555` / `US:AAPL` 前缀形式全支持）；
  中文名仍走 searchapi fallback 链
- models/ 是本地-only 专有判断，永不推送

## Field Notes

- 2026-10-03 工作台上线：archive.py（model.json + lint）+ gather.py
  （多源聚合，fail-closed 互不阻塞）。摩尔线程试跑：全历史 2022-2025
  四年三表到手（营收 4609万→15亿）
- 2026-10-04 年报文本源上线（fetch/annual.py，探针定稿
  data/probe_mdna.py）：A股 emweb BusinessAnalysis 三连——jyps 经营
  评述（MD&A，**只给最近一期**，翻页无效，茅台实测同样）+ zygcfx
  主营构成（分产品收入/成本/毛利率，茅台 37 期约 10 年）+ zyfw
  经营范围；OperationsRequired 给核心题材 hxtc + 机构预测 jgyc
  （多年 YEAR1-4/EPS/PE）+ 研报评级 ybzy（**投行分析源**）；
  CompanyManagement 给高管简历（文化层证据，NV 系背景实证级）。
  US 走 SEC 10-K Item 1/7 切段（stdlib HTML 剥标签，取最后出现
  跳过目录）。HK 披露易 PDF 无解析库 → gap。
- 2026-10-04 PDF 全文源上线（fetch/filings.py，pypdf 已全局装，
  软依赖不 vendor）：A股走巨潮 cninfo——topSearch 查 orgId →
  hisAnnouncement 按 category_ndbg_szsh（年报，剔除摘要，默认
  近 5 份 FILINGS_MAX_REPORTS）/ searchkey=招股（招股书，剔除
  提示性公告）→ static.cninfo.com.cn 文字版 PDF（实测 230 页/
  22万字符/~10s）；slice_mdna_a 按「第X节 管理层讨论与分析」
  切段（前 5% 命中视为目录跳过，切到下一节标题，<2000字符判
  失败）。gather 落盘 raw/filings/*.txt 全文 + *_mdna.txt 切段
  + raw/filings.json 索引。HK/US 招股书暂 gap（US 年报已由
  annual.py 10-K 覆盖）
- [2026-10-04 15:41] (ai) HK mainindicator history: annual rows must be picked by REPORT_TYPE ending 年报, never by 12-31 date — non-Dec fiscal years (03306 Jun-end, 03998 Mar-end) starve or mis-date otherwise; fixed in model/history.py 2026-10-04, tests test_parse_mainindicator_dec_fy / test_jun_fy_interim_is_not_annual / test_mar_fy_not_starved
- [2026-10-04 16:15] (ai) HK CNY-reporters (CNY statements, HKD price): engine has no FX layer — set shares=total_shares x 0.91 FX so per-share outputs are HKD (result currency label stays CNY but values are HKD, declared in --reason); engine caps 3 scenarios so 4-scenario dossiers fold tail into bear at the probability-weighted anchor (exact weighted preservation); dividend-claim translation (tax=0 net_debt=0 da/capex/nwc=0 margin=D0/rev) for leveraged payers where honest FCFF equity is negative (00991: 5.0x net debt/mcap — the H-share price IS the discounted dividend policy, not an FCFF residual); engine tax_rate=0 or-bug fixed 2026-10-04 with regression test
- [2026-10-04 17:24] (ai) engine 的 terminal_g/wacc/horizon_years or-bug 已同 tax_rate 一并修复（_or_default 显式 None 检查 + 回归测试 test_terminal_g_zero_is_respected）：0.0 是合法终值增速——BKE 档案核心论点 g=0 带宽震荡曾被 or 静默换成默认 0.025，终值虚增约 20%
- [2026-10-04 17:24] (ai) US 顶层 history.json 若 fetched_at 早于 2026-10-04 14:37 的 history.py 修复，companyfacts 财年帧错位两年且缺最新 10-K 年（BKE/HRMY 实证：10/2 拉取把 FY2023 标成 FY2025）——重建估值层前必须 model fetch --force 并与 raw/history.json 比对最后一年；另：理解层 10/4 重写而估值层仍停留在旧机制小 assumptions（<2KB）= 未重建信号
- [2026-10-04 18:15] (ai) engine-fix rebuild acceptance: after fixing the or-default zero-swallowing bug, rebuilt all 15 valuation layers and verified anchors via weighted_per_share delta (<0.005%) + result.history_hash == history.json hash; deliberate zero-paradigm params (HK dividend-discount tax_rate=0, BKE terminal_g=0) survived the fix intact — anchor-diff + hash check is the acceptance procedure for any post-engine-fix rebuild
