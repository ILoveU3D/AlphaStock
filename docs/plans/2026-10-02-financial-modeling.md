# 财务建模能力设计（financial modeling）

日期：2026-10-02 ｜ 状态：待用户评审 ｜ 触发：用户要求具备"基于财报/审计/尽调材料构建可调假设财务模型 + 可比公司估值表"的能力，对标阿里通义点金的财务建模 Agent，并融合进荐股/持仓/评价日常流程，建模时机由 AI 决定。

## 1. 定位与对标

通义点金形态：长财报切块入向量库 → ~20 个职能 Agent → 粘成尽调报告，底层是 DianJin-R1 专用模型。本工具箱架构不同：**箱内无 LLM，AI agent 即推理层**；缺的是"财务建模 Agent 手里的工具"。本设计补齐三块工具——多年三表历史、可调假设正向估值引擎、comps 表——并以融合层接入既有 QMF/三核流程。

第三方库结论：开源实现（finmodels 等）玩具级，且仓库铁律禁止 vendor（pandas+requests only，无 libs/）。估值引擎是纯函数，自写最小实现，借鉴设计不抄代码。

## 2. 方案取舍

| 方案 | 结论 |
|---|---|
| A. 按需单股拉取 + 本地模型库 | **采用**。仿 profile 模式：AI 决定建模时才拉该股多年财报，`models/` 本地-only |
| B. 快照管线内建多年财报 | 排除。全候选拉历史重且浪费，建模是 L3 个案工作 |
| C. 第三方估值库 | 排除。vendor 禁令 + 质量不达标 |

## 3. 架构

新子包 `value_genie/model/`，四模块 + 一个本地目录：

```
value_genie/model/
  history.py   # 多年三表历史拉取（按需、单股、fail-closed）
  engine.py    # 驱动因子 FCFF DCF（纯函数，无 IO）
  comps.py     # 可比公司估值表
  store.py     # 假设/结果/材料 IO（models/ 本地-only）
models/               # gitignored，LOCAL-ONLY，永不推送（同 profiles/ 规则）
  <market>/<code>/
    history.json      # 多年三表，带 as_of / unit / currency
    assumptions.json  # 可调假设，带 updated_at + 调整理由 changelog
    result.json       # 最近一次 build 输出
    raw/              # 审计意见段/尽调材料投喂入口（文本）
```

### 3.1 history.py（多年三表历史）

- A：东财 F10 历史报表 datacenter 接口（利润表/资产负债表/现金流量表；reportName 需探针，遵守 filter DSL 探针铁律：日期单引号、字符串双引号、9201 空窗口合法）
- HK：东财 HKF10 财务历史接口（同探针流程）
- US：SEC companyconcept 多年 XBRL（Revenue / NetIncome / OCF / Capex / D&A / Cash / Debt / Shares），复用现有 SEC http helper
- 标准化输出：每年 `{revenue, ebit, net_income, da, capex, ocf, cash, debt, shares}`（缺项 null 并声明）；网络入口模块级（monkeypatch 边界）；源失败返回 None，不覆盖既有文件

### 3.2 engine.py（驱动因子 FCFF DCF，纯函数）

公式：`FCFF_t = EBIT_t × (1−tax) + D&A_t − capex_t − ΔNWC_t`

假设 schema（assumptions.json）：

```json
{
  "version": 1,
  "horizon_years": 5,
  "wacc": 0.10,
  "terminal_g": 0.025,
  "tax_rate": 0.15,
  "scenarios": {
    "bear": {"prob": 0.25, "revenue_growth": [0.05, 0.04, 0.03, 0.03, 0.02], "ebit_margin": [0.10, 0.11, 0.12, 0.12, 0.12], "da_pct_rev": 0.03, "capex_pct_rev": 0.05, "nwc_pct_drev": 0.10},
    "base": {"prob": 0.50, "...": "..."},
    "bull": {"prob": 0.25, "...": "..."}
  },
  "net_debt": null,
  "shares": null,
  "changelog": [{"at": "2026-10-02", "key": "base.revenue_growth", "from": "...", "to": "...", "reason": "读年报审计意见后下调"}]
}
```

- 三情景 × 概率加权 → 概率加权每股内在价值（用户 2026-09-28 mandate：情景×概率代替点估计）
- EV→股权桥：`equity = EV − net_debt`；`per_share = equity / shares`（net_debt/shares 默认取 history 最近年，可覆盖）
- 敏感性矩阵：base 情景 WACC × terminal_g（5×5）
- 复用 `strategy/cores.py: implied_growth` 输出 reverse-DCF 隐含增速做互证行
- WACC / terminal_g 默认 = `config.DCF_DISCOUNT` / `config.DCF_TERMINAL_G`（与塔公理一致）

### 3.3 comps.py（可比公司估值表）

- Peer 集：快照 master.csv 同行业（industry 字段）同市场，剔除自身，按市值接近度取 ≤10 家
- 倍数：PE(TTM)/PS/PB 现成；EV/EBITDA 尽力而为（EV = 市值 + debt − cash，来自 history；缺项声明并排除该倍数，绝不编造）
- 产出：peer 倍数明细表 + 中位倍数 → 目标股隐含每股价值区间（低/中/高）
- 用途纪律（写入 skill）：comps 只作参照互证，不作买入论证（DCF 第一原则）

### 3.4 store.py 与默认假设

- 首次 `model fetch` 后自动生成默认假设：收入增速/利润率取 history 近 3 年中位数，capex/DA/NWC 比率取近 3 年均值——`build` 开箱即用，AI 读材料后再调
- 所有写操作原子化（复用 atomic.py）；assumptions 每次 `set` 追加 changelog（key/from/to/reason，reason 必填）
- `models/` 加入 .gitignore，注释同 PROFILES_DIR 的本地-only 规则

## 4. 融合层（用户 mandate 2026-10-02：融入荐股/持仓/评价，AI 决定建模时机）

### 4.1 建模触发条件（写入 skills/19，AI 自律执行）

- **必建**：masters-vote / recommend 的 L3 深评短名单候选，进 L4 裁决前
- **必建**：holding-deep-review 中论点漂移或大幅波动的持仓；钥匙孔季度证伪检查
- **选建**：用户问"评价 X"且无模型或模型已 stale
- **不建**：漏斗宽池扫描（建模是 L3 个案工作）；D4 战术/短炒模式（DCF 已降级为"失败变持有"注记）

### 4.2 ask X 集成

`ask X` 检测到 `models/<mkt>/<code>/result.json` 存在时，输出模型摘要块（概率加权价值 vs 现价、三情景、comps 区间、模型 as-of）；stale 则标注。无模型时行为不变。

### 4.3 core_dcf 升级钩（D3 平行机制）

现状：core_dcf = fcf_yield → reverse-DCF 隐含增速的绝对锚定分。平行于 D3 文化钩（profile 蒸馏激活 core_culture）：

- `model build` 产出概率加权 upside = (weighted_value − price) / price
- `add_core_scores(..., dcf_model=...)` 接受模型 upside 序列，存在时 core_dcf 改用模型锚（`config.CORE_ANCHORS["model_upside"]`，如 −30%→0 / +50%→100，实施时定稿进 config）
- `core_gaps` 标注 `DCF_MODELED (as-of ...)`；无模型股票维持现锚定，排名键仍是 core_score 唯一
- **staleness**：模型钉住 history as-of；新报告期出现 → STALE → 掉出打分（回到默认锚），直至 rebuild（同 profile raw_hash 规则）

### 4.4 审计/尽调材料工作流

1. AI 判定需建模（4.1 条件）→ `model fetch X` 自动抓交易所披露的结构化报表
2. 需要审计意见/关键审计事项等文本时：A/HK 年报 PDF 暂由用户投喂到 `models/<mkt>/<code>/raw/`（或 AI 用 WebFetch 抓 SEC 10-K HTML 段落——US 可行）；AI 读材料 → `model set` 调假设（changelog 必填理由）→ `model build` 重算
3. **后续增强（本次不做）**：巨潮年报 PDF 自动解析需 pdf 库入全局 Python，届时征求用户安装

## 5. CLI 规格（全部 --json 纯输出）

| 命令 | 行为 | 新鲜度闸门 |
|---|---|---|
| `model fetch X` | 拉多年三表 → history.json（不存在才拉，--force 刷新） | 无（历史报表） |
| `model build X` | history+assumptions → 情景估值+敏感性+comps → result.json | **有**（comps/upside 用价） |
| `model show X` | 打印最近 result（摘要或 --json 全量） | 无 |
| `model set X key=value ...` | 调假设（--reason 必填），追加 changelog | 无 |
| `model list` | 建模覆盖度 + staleness 报告 | 无 |

console 输出遵守答案形态铁律：结论先行、单位齐全、data-as-of 行；--json 无 banner 无副作用文件。

## 6. config 新增

```python
MODELS_DIR = BASE_DIR / "models"   # LOCAL-ONLY, gitignored, never pushed
MODEL_DEFAULT_SCENARIOS = {...}    # bear/base/bull 概率默认 0.25/0.50/0.25
MODEL_SENSITIVITY_WACC = (0.08, 0.09, 0.10, 0.11, 0.12)
MODEL_SENSITIVITY_TG   = (0.015, 0.02, 0.025, 0.03, 0.035)
CORE_ANCHORS["model_upside"] = (-30.0, 50.0)   # percent -> 0..100
```

## 7. 测试计划（python -B -m pytest tests -q）

- engine：手算 DCF 用例（单情景固定现金流对拍）、FCFF 公式逐项、情景概率加权、EV→股权桥、敏感性矩阵单调性（WACC 升 → 价值降）
- store：assumptions 往返、changelog 追加、原子写
- comps：peer 选择（同行业/剔自身/市值接近/上限 10）、缺 EV 项声明
- history：三市场解析器 fixture（monkeypatch 网络边界）、fail-closed 不覆盖
- CLI：--json 纯净度、build 闸门行为（FAIL 退出码 1）

## 8. 集成清单

- `value_genie/model/` 四模块 + `__main__.py` model 子命令注册
- `config.py`：MODELS_DIR 等（见 §6）
- `.gitignore`：models/
- `analyze.py`：ask 输出模型摘要块（§4.2）
- `strategy/cores.py`：`add_core_scores` 加 dcf_model 参数 + core_gaps 标注（§4.3）
- `AGENTS.md`：路由表加 model 行 + 触发条件引用
- `skills/19-financial-modeling.md`：触发条件、工作流、comps 纪律、材料投喂流程（编号 19，19 前无占用）

## 9. 范围外（YAGNI）

- 完整三表勾稽（IS/BS/CF 逐年联动）——驱动因子 FCF 已够决策
- 巨潮 PDF 自动解析、LBO 模型、precedent transactions、models/ 的 git 跟踪
- 人类交互界面（AI 是唯一 UI）
