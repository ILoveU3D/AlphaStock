# 荐股机制 v2 重设计实施计划（2026-09-29 晚）

背景：日间自检（8 项发现 F1-F8）确认三核排序在实际运行中退化为 FCF 收益率单因子筛，
且量化代理 top15 预筛使 AI 只能否决不能选择（架构层违反段永平原则）。
用户已拍板五项决定（D1-D5）+ 两条追加（短线手段、profiles 原型方向）。

## 用户裁决（不可违反）

- D1 量化只否决，AI 做选择：L1 产出 = 宽池+否决清单，不再 top15 预筛；
  最终排序发生在 AI 三核判断层。
- D2 缺核 = 插市场平均分 + core_gaps 强制念出 + doctor 缺核率盯数据源修复
  （塔砖 recall-is-not-verdict note v2 已记录）。
- D3 文化核无蒸馏时只否决不打分（文化话题后续专门讨论）。
- D4 短线地板验证生意真实性，不验证价格：business 核达标 + 全部否决项；
  DCF 核降级为"失败变持有"诚实备注；NVDA/AAPL 类因此可进短线、不进长线。
- D5 A/HK/US 三市场统一：lanes/三核/否决同构；港股补 stage-1 基本面。
- 短线手段（塔砖 weekly-trend-daily-pullback, observation）：周K明显上升趋势
  + 日K回撤时买入，赌趋势惯性；地板必须是真生意。
- profiles：本地-only（永不推送），AI 读财报+intel 蒸馏商业模式/文化，
  schema 预留可移植数据集；本次只做原型。

## Phase 0：探针（网络，小步）

- 东财 HKF10 批量基本面报表（HK stage-1 补 ROE/毛利率/负债率，使车道B在HK生效）
- HK/US 一致预期源有无（无则 cycle_trap 守卫声明 gap，不伪造）
- US fcf_yield 缺口回补（SEC companyconcept 单股回补可行性；FUTU/FDS 类缺 FCF）
- 产出：探针脚本放 data/（可再生区），结论一行写进 Phase 1/2 任务注释

## Phase 1：L1 宽池化（核心翻转）

- consensus.py：masters_vote 产出保留 vote/veto 列；新增池输出语义——
  全候选 + 每只 veto_hard/红旗/缺核 标注，不再默认 head(15)。
- CLI masters-vote：默认输出宽池+否决清单（core_score 仅展示，可 --top N 截显示）；
  --json 全量。
- skills/18 改写 L1-L4：L1=宽池+否决清单；L2=红旗；L3=AI 从宽池选深评名单
  （选择责任在 AI，书面论证义务）；L4=融合裁决+分舱+时间窗口。
- AGENTS.md answer shape #5 同步改写。
- 测试：池模式输出、否决标注、无 top 截断回归锁。

## Phase 2：缺核诚实化

- cores.py：缺核插**所在市场宇宙均值**（NaN 不进均值）；core_gaps 原由保留；
  输出照常声明。
- doctor：新增每市场三核缺失率（数据健康度指标）。
- 测试：插值数学（缺核=市场均值）、gaps 声明不丢、doctor 缺核率字段。

## Phase 3：文化核退化

- cores.py：文化代理分不再进 core_score 均值（无蒸馏时）；其否决语义
  （intel_red/减持/粉饰/借钱分红）全部保留在 L2。
- 有蒸馏行（profiles 原型产出）才恢复文化打分——接口预留，原型接入即生效。
- 测试：无蒸馏时 core_score=business/dcf 两核逻辑、否决列不受影响。

## Phase 4：短线/超短线融合路径

- kline 因子新增：weekly 趋势（日 kline 重采样：close>MA20W 且 MA10W>MA20W，
  26 周涨幅>0 → weekly_uptrend 0/1）、pullback_from_high（距 60 日高点回撤%，
  甜点区 -5%~-15%）。
- 短线排序键（horizon=short/ultrashort 时替换 core_score 排序角色）：
  地板 = core_business 达标 + 全部否决项 + weekly_uptrend=1；
  排序 = 回撤甜点区 + ret_60d≥0 + 波动/流动性 + intel 热度。
- DCF 核降级为输出备注（reverse DCF 隐含长期回报一句话，诚实声明付溢价代价）。
- 输出强制行：短炒警示、-7% 硬止损、时间止损、仓位上限（按 14 号 playbook）。
- masters-vote --horizon short|ultrashort 走完整 L1-L4（短线推荐也融合）。
- 测试：weekly 重采样、回撤因子边界、地板否决、输出纪律行存在性。

## Phase 5：profiles 原型（本地-only）

- 存储：raw → data/profiles/raw/（可再生，可日清）；
  assessment → 顶层 profiles/（untracked + .gitignore，永不推送，本地持久）；
  schema 稳定（source/raw_hash/scores/论证文本），为未来可移植数据集留形。
- 抓取：按需（深评名单逐只抓），A/HK 东财 F10 + US SEC/stockanalysis
  （复用 2026-09-29 探针结论）；不做全量批量。
- 蒸馏闭环：AI 读 intel 财报速读+公告+新闻+原文 → assess 回写 →
  文化核恢复打分（Phase 3 接口）。
- _redesign_keep_profiles/ 里 3 份既有蒸馏（600900/NVDA/HRMY）迁移进新 schema。
- 测试：schema 往返、原子写、gitignore 生效（git status 不见 profiles/）、
  蒸馏接入文化核。

## Phase 6：文档与塔

- skills/18（L1-L4 + 短线路径 + 分舱纪律）、AGENTS.md（routing + answer shape）、
  README 能力行、14 号 playbook 交叉引用。
- 塔：weekly-trend-daily-pullback 已在塔（observation）；实施完成后
  note 记录校准结果。

## 明确排除

- ETF 通道（用户：后面有需求再说，只留接口位置）。
- profiles 全市场批量抓取（原型只做按需）。
- 文化话题深聊（用户：后面专门讨论）。
- users/ + trading/ 远端历史清洗（用户已选"彻底清除远端历史"，属另一独立操作，
  本次不动；远端分支已删，无暴露）。

## 验证

- 每 Phase 独立测试绿后推进；全程 python -B -m pytest tests -q。
- 端到端：masters-vote（宽池）→ 缺核插值声明 → 短线 --horizon short 输出
  纪律行 → profiles 蒸馏一只 → 文化核生效。
- 提交：Phase 1-4 一个 commit（机制 v2），Phase 5 一个 commit（原型，不含数据），
  Phase 6 一个 commit（文档）。用户自行开 PR；profiles/ 永不推送。
