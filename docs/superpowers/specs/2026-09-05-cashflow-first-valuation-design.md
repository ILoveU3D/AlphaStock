# 现金流优先的估值体系升级 — 设计文档

日期：2026-09-05（v2）
状态：已与用户逐项确认（四点建议 → 三次决策问答 → v1 六节通过 →
用户三点修订：港股补齐 / 借钱分红机制 / 大师策略吸收 → v2 通过）

## 背景与用户诉求

用户对一期持仓复盘提出四点策略改进：

1. **DCF 优先于 PE**：PE 代表过去，DCF（未来现金流折现）才是估值本质（巴菲特：
   DCF 是唯一规则）。
2. **怀疑分红率**：借钱分红是造假，必须检测并一票否决。
3. **负债与现金流的来源/去向**：负债怎么来的、准备怎么处理；现金流怎么来的、
   准备怎么处理——判断股票好坏的核心四问，必须深刻理解。
4. **充分吸收格雷厄姆烟蒂股判断**：安全边际算术。

v2 修订（用户 2026-09-05 二轮反馈）：

5. **港美股尽量完善**：港股想办法搞数据（已找到东财港股现金流量表接口）。
6. **借钱分红的机制**（用户阐述，写入 rationale）：A 股现行再融资规则要求近年
   现金分红记录，分红是再融资资格的"敲门砖"；现金流出问题的公司会"保资格式
   分红"——先分红满足监管条件，再通过增发/借款把现金拿回来。这不是回报股东，
   是融资技术动作，必须毙掉。
7. **大师策略同步吸收**：现金流优先不是只改用户风格，buffett/munger/graham/duan
   四位基本面大师的 gates 同步升级。

## 用户确认的关键决策

| 决策点 | 结论 |
|---|---|
| DCF 落地深度 | FCF 一阶近似（fcf_yield 因子），不做三阶段折现模型 |
| 六支柱权重 | value 0.15→0.10，growth 0.30→0.25，quality 0.30→0.25，safety 0.15 不变，momentum 0.05 不变，cashflow 0.05→0.20（和为 1.00） |
| 借钱分红处理 | 硬门槛一票否决（用户风格 gates + 虚拟盘买入前 + 四位大师 gates），ask 旗标保留可见 |
| 量化覆盖 | **三市场全覆盖**（v1 的"港股仅定性"作废）：港股走东财 `RPT_HKF10_FN_CASHFLOW_PC` |
| 因子口径 | **新现金因子一律年报口径**（12 个月完整值），三市场一致 |
| ocf_yield 修正 | 切换年报口径（连带修复巴菲特门槛被期中数据扭曲的现存 bug） |

## 0. 借钱分红 rationale（机制，用户阐述）

A 股现行再融资规则要求近年现金分红记录，分红因此成为再融资资格的"敲门砖"。
现金流恶化的公司会"保资格式分红"：先分红满足监管条件，再通过增发/借款把
现金拿回来。这不是回报股东，是融资技术动作。

检测式 `div_paid > fcf 且 div_paid > ocf×0.5 且 net_fin_cf > 0` 捕捉的正是
"分红出去的钱从筹资端回来"的同期模式：

- 条件 1（div > fcf）：分红超出自产生现金的能力；
- 条件 2（div > ocf×0.5）：排除"借钱搞资本开支顺便小额分红"的成长公司误伤；
- 条件 3（net_fin_cf > 0）：同报告期筹资端净流入——钱确实是"借/融"来的。

语境标注：机制在 A 股最强（监管明文）；港美无此监管耦合，但"分红靠筹资
支撑"作为危险信号同样成立，旗标文案区分语境。

## 1. 数据层（fetch）

### A 股（`value_genie/fetch/fundamentals.py`）

- 现有 `a_cashflow.csv`（期中累计口径）**不动**，继续喂 `cash_conversion`。
- 新增**年报期**抓取：同一 `RPT_DMSK_FN_CASHFLOW` 接口、最近一个
  12-31 报告期（带上一期回填），输出新文件 `a_cashflow_annual.csv`，
  schema `code, report_date, ocf, capex, net_fin_cf`：
  - `NETCASH_OPERATE` → ocf
  - `CONSTRUCT_LONG_ASSET` → capex（购建固定资产/无形资产/长期资产支付的现金）
  - `NETCASH_FINANCE` → net_fin_cf
- 字段已随现有请求的 `columns: "ALL"` 返回，成本仅为一期额外翻页
  （全市场约 +23 页 × 0.4s）。
- A 股分红支付额**近似**：`div_paid ≈ dividend_yield/100 × market_cap`
  （trailing 股息率 × 市值，年报口径无当日股息支付额字段）。

### 港股（同文件 + `fetch/pipeline.py` deep pass）

- 新增 per-stock 抓取 `RPT_HKF10_FN_CASHFLOW_PC`（长表：
  STD_ITEM_CODE + STD_ITEM_NAME + AMOUNT），并入现有 HK F10 循环，
  200 只 × 1 次调用（pageSize=100 覆盖约 3 个报告期），支持当日 resume。
- **港股财年不统一**（3/6/9/12 月年结都有）：年报行用
  `REPORT_DATE − START_DATE` 跨度在 **330–400 天**识别，不硬编码 12-31。
- 提取科目 → 新文件 `hk_cashflow.csv`，schema 同 A 股年报表 +
  `div_paid`：
  - `003999` 经营业务现金净额 → ocf
  - `005005 购建固定资产 + 005007 购建无形资产及其他资产` → capex
  - `007004 已付股息(融资)` → **div_paid 直取（无需近似）**
  - `007999` 融资业务现金净额 → net_fin_cf
- 副产品：港股 `ocf_yield` 数据源从 MAININDICATOR（期中口径、57% 填充）
  切换到本表年报行——填充率与口径同时改善。

### 美股（SEC EDGAR frames，同文件）

- 新增 3 个 frame 抓取（复用现有 frames 机制，每个 = 1 次批量调用）：
  - `PaymentsToAcquirePropertyPlantAndEquipment` → capex
  - `PaymentsOfDividendsCommonStock` → div_paid
  - `NetCashProvidedByUsedInFinancingActivities` → net_fin_cf
- `us_financials.csv` 新增列 `capex, div_paid, net_fin_cf`；cy frame 本为
  年度口径，与全局年报基准一致。

### 兼容性

- 当日 fetch 复用（resume）：新文件缺失 → pipeline 容错 NaN；旧 snapshot
  无新列同样 NaN 容错，不崩溃。
- HK deep pass 当日已抓过 → `hk_cashflow.csv` 复用（与 hk_f10.csv 同机制）。

## 2. 因子层（`value_genie/strategy/factors.py` + `fetch/pipeline.py`）

新增 3 个 master 列（进 `MASTER_COLUMNS`，插在 `ocf_yield, cash_conversion`
之后），**全部年报口径，三市场一致**：

| 因子 | 定义 | 说明 |
|---|---|---|
| `fcf_yield` | `(ocf − capex) / market_cap × 100` | DCF 一阶近似（自由现金流收益率） |
| `borrowed_dividend` | 0/1：`div_paid > fcf` 且 `div_paid > ocf×0.5` 且 `net_fin_cf > 0` | 借钱分红嫌疑（机制见 §0） |
| `capex_to_ocf` | `capex / ocf` | 再投资强度（现金流"怎么处理"），ask 展示用，不进支柱 |

实现位置：pipeline 专用函数（master 构建时调用——需要 market_cap 与
年报现金流 join；`add_derived_factors` 只做列内派生，不适合）。

- **ocf_yield 年报口径修正（连带 bug fix）**：现有实现用最新报告期累计值
  （当前=半年报 6 个月）除以市值，年中时段系统性低估约一半，巴菲特
  `ocf_yield>=5` 门槛实际一直在错杀。修正后 A/HK 用年报 ocf（US 本为年度
  cy frame，不变）。`cash_conversion` 保持期中/期中匹配，不动。
- **缺失语义**：年报现金流缺失 → 三因子 NaN；`borrowed_dividend` 写入
  master 时 `fillna(0)`（无罪推定，gate 可用），数据缺失由既有
  "incomplete data" 旗标在 ask 中提示。
- **支柱评分**：`PILLAR_FACTORS["cashflow"]` 追加 `("fcf_yield", 1)`；
  `capex_to_ocf`、`borrowed_dividend` 不进支柱（前者方向争议留给定性层，
  后者是排除项不是评分项）。value 支柱组成不变（DCF 重视由权重体现）。

## 3. 风格层（CLI，运行时执行，非代码改动）

```
user set-style me \
  --weight value=0.10 growth=0.25 quality=0.25 safety=0.15 momentum=0.05 cashflow=0.20 \
  --gate borrowed_dividend<=0 --gate debt_ratio<=60
```

- 保留现有 gates：`ret_20d<=-3, roe>=10, rev_yoy>=0`。
- `debt_ratio<=60`：负债硬约束（巴菲特线），落实四问中"负债"的量化层。
- 写入 `users/me.json`（CLI 原子写，不动手改文件）。

## 3a. 大师策略吸收（`value_genie/strategy/masters.py`）

| 大师 | 改动 | 理由 |
|---|---|---|
| buffett | gates += `borrowed_dividend<=0`, `fcf_yield>=4` | owner earnings 本就是他的 DCF 口径，两道门都是原教旨 |
| munger | gates += `borrowed_dividend<=0` | 伪造现金回报 = 不 wonderful |
| graham | gates += `borrowed_dividend<=0` | 防御型投资者标准本含"长期分红记录 + 财务审慎" |
| duan | gates += `borrowed_dividend<=0` | 分红造假 = 不"本分" |
| livermore / sheng | **不动** | 纯价格/注意力流派，加基本面门槛违反方法论纯度 |

- 权重一律不动（已按各大师终身风格校准；现金流权重 0.15-0.20 原本就高）。
- `AGENTS.md` 大师门槛表（buffett 行）同步更新；graham 行 gate 列补注。

## 4. 输出层（`value_genie/report.py` / `analyze.py`）

- `ask X`：
  - 新增展示 `fcf_yield`、`capex_to_ocf`（与 PE/PB 并列，有值时）。
  - `borrowed_dividend == 1` → 风险旗标 verbatim：
    `"borrowed dividend: 年报分红超过自由现金流且筹资净流入（A 股语境：保再融资资格的借钱分红，危险信号）"`。
- `screen --strategy me` / `recommend --user me` / 大师屏：新 gates 自动生效
  （gate DSL 走 master 列，无需额外改动）。

## 5. 判断层（Field Notes，append-only；不改 Playbook 正文）

实施完成后通过 `skill note` 追加：

- **trading**（S001 框架 v2）：
  1. 估值锚从 PE → FCF 收益率（DCF 一阶）；
  2. 买入前强制四问并写进 `--note`：负债怎么来的？准备怎么处理？
     现金流怎么来的？准备怎么处理？
  3. `borrowed_dividend=1` 一票否决（机制见 spec §0）；
  4. 烟蒂备用仓：无好机会时的备选配置（银行/保险/稳健）必须过 graham 屏
     （`pe_pb<=22.5` 现成派生因子）——格雷厄姆安全边际算术，不做价格目标。
- **holding-deep-review**：四问测试 + DCF 三问（未来现金流从哪来/多少/
  什么折现率）+ 借钱分红检查。
- **single-stock-analysis**：FCF 视角解读 + `borrowed_dividend` 旗标含义。

## 6. 测试（TDD，`python -B -m pytest tests -q`）

- `fcf_yield` 计算：正常值 / capex>ocf（负 FCF）/ NaN 容错。
- `borrowed_dividend` 边界：
  - 真阳性：div>fcf、div>ocf×0.5、net_fin>0 → 1；
  - 假阳反例：ocf=100, capex=120, div=5, net_fin=+50 → 0（借钱搞资本开支）；
  - 净筹资为负 → 0；div_paid 缺失 → 0。
- A 股年报表：年报期选取（含回填）、新列解析、传递到 master。
- HK 现金流量表解析：
  - 长表→宽表（科目映射 003999/005005+005007/007004/007999）；
  - 财年识别：12 月年结、3 月年结（START_DATE 跨度≈365 天）两种 fixture；
  - 缺科目容错（某科目无行 → NaN）。
- US：frames 新列 join。
- ocf_yield 年报口径：A 股年报 join 后的数值断言。
- gate 语义：`fillna(0)` 后 `borrowed_dividend<=0` 排除生效；被标记行被
  用户风格屏与大师屏（buffett）同时排除。
- 旧 schema 快照（无新列/新文件）容错。
- CLI `user set-style` 端到端（权重和 gates 落盘）。

## 明确不做

- 完整三阶段 DCF 模型（假设敏感，筛选器场景下是假设戏法）；
- Playbook 正文改写（append-only 是系统可信性的基础，正文走人工通道）；
- `capex_to_ocf` 进支柱评分（方向争议留给定性层）；
- 跨年度"分红-融资"链条检测（同年期模式已捕捉主要信号，跨年检测需多期
  数据，v1 不做）；
- `cash_conversion` 口径修正（期中/期中匹配，无扭曲，保持现状）。
