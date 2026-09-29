# QMF 三核架构改造（商业模式 / 企业文化 / DCF）

## Context

用户质询（2026-09-29）确认：现有漏斗的 value/growth/quality 百分位混合排序不科学——它把"低倍数"当"低估"的代理变量，数学上必然排除 NVDA/AAPL/TSM/BRK 类复利机器，且手拍权重无样本外验证。用户新框架（mandate）：**商业模式、企业文化、DCF 估值 = 三个等价核心负责排序；其他一切指标（六柱量化、大师投票/排名）只能作为"不选的理由"（veto-only）**。这是段永平原则（数据只能成为不买的理由）的架构化。

已确认决策：① 硬否决 = 七大师全否（0 票）或红旗（intel\_red/借钱分红/profit\_spike/cycle\_trap），单个大师不过仅展示；② US Form 4 解析留 Phase 2，Phase 1 文化分用现有字段+gap 如实声明；③ DCF 锚点 r=10%、永续 g=2.5%、10 年 fade，隐含 g≤-5%→100 分、≥15%→0 分。

## 架构原则（代码强制）

排序键唯一：`core_score` = 三核等权均值（锚点绝对映射，非百分位）。六柱分、composite\_score、vote\_count、mean\_composite 全部降级为展示/否决用途，不驱动任何排序。

## 1. config.py 新增锚点

```python
CORE_ANCHORS = {  # (差→好) 线性截断映射 0-100
  "cash_conversion": (50.0, 150.0),  # OCF/净利 %
  "gross_margin": (20.0, 60.0), "roe": (5.0, 25.0),
  "capex_to_ocf": (1.0, 0.1),         # 反向：重→轻资本
  "fcf_yield": (0.0, 8.0),            # %
}
DCF_DISCOUNT = 0.10; DCF_TERMINAL_G = 0.025; DCF_FADE_YEARS = 10
DCF_IMPLIED_G_RANGE = (-0.05, 0.15)
LANE_A_CAP = 120; LANE_B_CAP = 80      # 合计 = CANDIDATES_PER_MARKET
LANE_A_GATES = {"pe_ttm<=": 30.0, "pb<=": 4.0, "ps<=": 6.0}   # 任一满足
LANE_B_GATES = {"roe>=": 15.0, "gross_margin>=": 40.0, "debt_ratio<=": 60.0}  # 全部满足
DCF_FUNNEL_EARNINGS_HAIRCUT = 0.7      # 漏斗阶段 FCF≈0.7×E 的近似折让
```

阈值依据：Lane B 借用 Buffett 既有门；Lane A 为 Graham pe\_pb≤22.5 的松动版。

## 2. 新模块 value\_genie/strategy/cores.py

* `_anchor(s, lo, hi)`：线性截断 0-100，NaN 保留。

* `business_score(df)`：cash\_conversion/gross\_margin/roe/capex\_to\_ocf/fcf\_yield 五子项可用值等权均值。

* `culture_score(df)` → (score, gap)：三子项——分红诚实（borrowed\_dividend 0→100/1→0）、内部人一致（A 股 holder\_cut\_flag/dilution\_flag/buyback\_active，复用 radar 列）、账面诚实（eq\_flags 计数映射 + intel\_red 直接 0）。HK/US 仅有 borrowed\_dividend → 单组件打分 + gap "insider/buyback data A-only"。

* `dcf_score(df)`：由 fcf\_yield（local-currency 年化 FCF/市值，价格市值约去，纯函数）二分反解隐含 g（r/tg/fade 用锚点，界外截断），锚点映射为 `core_dcf`，输出 `dcf_implied_g`。fcf\_yield NaN → NaN + gap。

* `add_core_scores(df)`：加 `core_business/core_culture/core_dcf/dcf_implied_g/core_score/core_gaps` 六列；core\_score 缺核时可用项重归一并记 gap。

## 3. master.csv 与 pipeline.py

* `MASTER_COLUMNS` 追加：`lane, core_business, core_culture, core_dcf, dcf_implied_g, core_score, core_gaps`。

* `add_core_scores` 拆两步：master 构建时算基本面核（business+dcf）；radar 合并后重算 culture 两列二次写盘（radar 合并在 master 写出后，pipeline.py L1016 附近）。

* **漏斗双车道**（废除 stage1\_score 准入）：

  * `lane_a` = LANE\_A\_GATES 任一满足（错杀道；pe>0/rev\_yoy>0 已由 apply\_gates 保证）；

  * `lane_b` = LANE\_B\_GATES 全部满足（复利道，无便宜门）；

  * 道内排序用 stage-1 可得三核近似：business 子集（roe/gross\_margin/cash\_conversion）+ `0.7/pe_ttm` 作 FCF 代理的 dcf 近似（注释声明近似，终排以 master 精确值为准）；

  * `lane_a.head(120) ∪ lane_b.head(80)` 去重打 `lane` 列，不足 200 由 lane\_a 补齐；

  * HK 例外：stage-1 无基本面 → lane\_b 自然为空，manifest 如实记 `hk_lane_b=0`，不新增抓取。

  * 删 `stage1_blend`/`FUNNEL_WEIGHTS` 调用（函数标记 deprecated 或直接移除），stage1\_score 从 master.csv 消失。

## 4. consensus.py（否决语义 + 新排序键）

* 新增 `veto_hard = (intel_red==1)|(borrowed_dividend==1)|profit_spike`（快照可算部分）；cycle\_trap 属 live pass，CLI 层排除。

* `rank_consensus` 排序键改 `["core_score", "vote_count"]` 双降序（vote\_count 仅 tie-break/展示）。

* 池过滤移 CLI：`pool = df[(vote_count>=1) & (~veto_hard)]`；live pass 后排除 cycle\_trap（cycle\_warn 仍展示）。

* mean\_composite 继续算，注释 "context only, never ranks"。

## 5. report.screen / recommend / analyze / __main__

* `screen()`：gates 过滤不变（veto-only 天然成立）；去 `apply_composite`+`rank_top` 排序，改 `add_core_scores` 后按 core\_score 降序取 top\_n；`--weights` 不再影响排序（仅供 analyze profile），docstring 明说；展示列加四核列，composite\_score 保留为 context。旧快照缺核列 → 纯函数即时回填（同柱分回填模式，无 IO）。

* `recommend.py` 调 screen 处自动继承；健康报告的 composite\_score 展示不动。

* `analyze.py`：`analyze_stock` 增 `result["cores"]`（单行 add\_core\_scores + dcf\_implied\_g + gaps，绝对锚点无需 peer frame）；render\_brief 增 "three cores (absolute anchors)" 块；--json 同步。

* `__main__.py cmd_masters_vote`：池过滤按 §4；表加 `core/dcf_g` 列；flags 附 veto 来源；结尾行改 "L1=veto filter（门+红旗只能排除）；排序=三核等权；L3/L4 见 skills/18"。

## 6. 文档（单独提交，用户手册类）

* skills/18-fused-quant-master.md：L1-L4 语义改写（L1=veto filter、L2=红旗、L3=AI 三核深评+书面论证、L4=融合裁决）。

* AGENTS.md 路由表/answer-shape 同步。

* `skill note fused-quant-master`/`data-ops` 各记一行变更。

## 7. 测试

新增 `tests/test_cores.py`：锚点边界（恰等于 lo/hi）、全缺输入→NaN+gap、reverse-DCF 已知解析（y=r−tg 时 g≈0）、HK/US culture gap 声明、core\_score 缺核重归一。

必改（排序键断裂点）：

* `test_consensus.py::test_mean_composite_and_ranking` → 改 core\_score 单调；`_frame()` 补核输入列；新增 veto\_hard 断言。

* `test_report.py` 的 composite 期望序/数值、custom\_weights、首名断言 → fixture 补核输入列，按 core\_score 重排期望。

* `test_pipeline.py::test_stage1_blend_ranks` → 替换为 lane 测试（Lane A 命中/Lane B 门/去重/cap/HK lane\_b 空）。

* 其余 composite 展示断言保留（列仍在）。

## 8. Phase 2 follow-ups（本次不做，core\_gaps+文档声明）

US Form 4 XML 解析（交易码/角色/金额聚合）、US 回购 frame、A 货币资金净现金、HK F10 多期持久化（已抓 12 期被丢弃）、多年 FCF CAGR、ROIC、股本稀释史。

## 9. 验证

1. `python -B -m pytest tests -q` 全绿；
2. 现有快照 `masters-vote --json --no-check`：core\_score 排序、veto 排除生效；
3. `screen --strategy duan --no-check` 核序；`ask 600519 --no-check` 出三核块；
4. 东财恢复后完整 fetch，验证新列、lane 计数、NVDA 类复利机器能否经 Lane B 首次进入候选池（召回实证）。

