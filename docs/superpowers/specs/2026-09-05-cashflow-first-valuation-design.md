# 现金流优先的估值体系升级 — 设计文档

日期：2026-09-05
状态：已与用户逐项确认（四点建议 → 三次决策问答 → 设计六节全部通过）

## 背景与用户诉求

用户对一期持仓复盘提出四点策略改进：

1. **DCF 优先于 PE**：PE 代表过去，DCF（未来现金流折现）才是估值本质（巴菲特：
   DCF 是唯一规则）。
2. **怀疑分红率**：借钱分红是造假，必须检测并一票否决。
3. **负债与现金流的来源/去向**：负债怎么来的、准备怎么处理；现金流怎么来的、
   准备怎么处理——判断股票好坏的核心四问，必须深刻理解。
4. **充分吸收格雷厄姆烟蒂股判断**：安全边际算术。

## 用户确认的关键决策

| 决策点 | 结论 |
|---|---|
| DCF 落地深度 | FCF 一阶近似（fcf_yield 因子），不做三阶段折现模型 |
| 六支柱权重 | value 0.15→0.10，growth 0.30→0.25，quality 0.30→0.25，safety 0.15 不变，momentum 0.05 不变，cashflow 0.05→0.20（和为 1.00） |
| 借钱分红处理 | 硬门槛一票否决（用户风格 gates + 虚拟盘买入前），ask 旗标保留可见 |
| 量化覆盖 | A 股 + 美股；港股数据源无现金流量表，仅定性标注 |

## 1. 数据层（fetch）

### A 股（`value_genie/fetch/fundamentals.py`）

- `A_CASHFLOW_MAP` 新增映射：
  - `CONSTRUCT_LONG_ASSET` → `capex`（购建固定资产、无形资产和其他长期资产
    支付的现金）
  - `NETCASH_FINANCE` → `net_fin_cf`（筹资活动现金流净额）
- **零额外 API 调用**：现有请求已带 `columns: "ALL"`，字段随响应返回，
  当前在 `_parse_cashflow` 被丢弃，仅保留 `NETCASH_OPERATE`。
- `a_cashflow.csv` schema 由 `code, report_date, ocf` 扩展为
  `code, report_date, ocf, capex, net_fin_cf`。
- `num()` 数值化 + `merge_a_periods` 回填逻辑对新列同样生效。

### 美股（SEC EDGAR frames，同文件）

- 新增 3 个 frame 抓取（每个 = 1 次批量 API 调用，复用现有 frames 机制）：
  - `PaymentsToAcquirePropertyPlantAndEquipment` → `capex`
  - `PaymentsOfDividendsCommonStock` → `div_paid`
  - `NetCashProvidedByUsedInFinancingActivities` → `net_fin_cf`
- `us_financials.csv` 新增列 `capex, div_paid, net_fin_cf`。
- fetch 时间增加：分钟级（3 次调用 + 解析）。

### 港股

- 不动。当前 F10 源无现金流量表，`cashflow_score` 继续为 NaN，
  ask 输出如实标注"港股无现金流数据源"。

### 兼容性

- 当日 fetch 复用（resume）：旧 schema 文件缺新列 → pipeline 侧对缺失列
  容错为 NaN，不崩溃；次日新 snapshot 目录自然全量重抓。
- 旧快照（`data/snapshots/*` 无新列）读取路径同上，NaN 容错。

## 2. 因子层（`value_genie/strategy/factors.py` + `fetch/pipeline.py`）

新增 3 个 master 列（进 `MASTER_COLUMNS`，插在 `ocf_yield, cash_conversion`
之后）：

| 因子 | 定义 | 说明 |
|---|---|---|
| `fcf_yield` | `(ocf − capex) / market_cap × 100` | DCF 一阶近似（自由现金流收益率），单位与 `ocf_yield` 现有口径一致（百分数） |
| `borrowed_dividend` | 0/1：`div_paid > fcf` 且 `div_paid > ocf×0.5` 且 `net_fin_cf > 0` | 借钱分红嫌疑。第二条件防误伤：借钱搞资本开支顺便小额分红（成长公司）不算 |
| `capex_to_ocf` | `capex / ocf` | 再投资强度（现金流"怎么处理"），ask 展示用，不进支柱评分 |

实现位置：pipeline 专用函数（master 构建时调用，逐行计算——需要
market_cap 与现金流列 join，`add_derived_factors` 只做列内派生，不适合）。

- **A 股分红支付额近似**：`div_paid ≈ dividend_yield/100 × market_cap`
  （trailing 股息率 × 市值）。近似误差已知并接受；美股用 frame 真值。
- **缺失语义**：现金流数据缺失（港股、部分 A/US 行）→ 三因子 NaN；
  `borrowed_dividend` 在写入 master 时 `fillna(0)`（无罪推定，gate 可用），
  数据缺失由既有 "incomplete data" 旗标在 ask 中提示。
- **支柱评分**：`PILLAR_FACTORS["cashflow"]` 追加 `("fcf_yield", 1)`；
  `capex_to_ocf`、`borrowed_dividend` 不进支柱（前者方向有争议，后者是
  排除项不是评分项）。value 支柱组成不变（DCF 重视由权重体现）。

## 3. 风格层（CLI，运行时执行，非代码改动）

```
user set-style me \
  --weight value=0.10 growth=0.25 quality=0.25 safety=0.15 momentum=0.05 cashflow=0.20 \
  --gate borrowed_dividend<=0 --gate debt_ratio<=60
```

- 保留现有 gates：`ret_20d<=-3, roe>=10, rev_yoy>=0`。
- `debt_ratio<=60`：负债硬约束（巴菲特线），落实四问中"负债"的量化层。
- 写入 `users/me.json`（CLI 原子写，不动手改文件）。

## 4. 输出层（`value_genie/report.py` / `analyze.py`）

- `ask X`：
  - 新增展示 `fcf_yield`、`capex_to_ocf`（与 PE/PB 并列，A/US 有值时）。
  - `borrowed_dividend == 1` → 风险旗标 verbatim：
    `"borrowed dividend: 分红超过自由现金流且净筹资为正（借钱分红嫌疑）"`。
- `screen --strategy me` / `recommend --user me`：新 gates 自动生效，
  无需额外改动（gate DSL 走 master 列）。

## 5. 判断层（Field Notes，append-only；不改 Playbook 正文）

实施完成后通过 `skill note` 追加：

- **trading**（S001 框架 v2）：
  1. 估值锚从 PE → FCF 收益率（DCF 一阶）；
  2. 买入前强制四问并写进 `--note`：负债怎么来的？准备怎么处理？
     现金流怎么来的？准备怎么处理？
  3. `borrowed_dividend=1` 一票否决；
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
- A 股：`_parse_cashflow` 新列解析、`merge_a_periods` 回填、新列传递到 master。
- US：frames 新列 join。
- gate 语义：`fillna(0)` 后 `borrowed_dividend<=0` 排除生效；被标记行被
  用户风格屏排除。
- 旧 schema `a_cashflow.csv`（3 列）容错。
- CLI `user set-style` 端到端（权重和 gates 落盘）。

## 明确不做

- 完整三阶段 DCF 模型（假设敏感，筛选器场景下是假设戏法）；
- 港股现金流换源（成本高、收益低）；
- Playbook 正文改写（append-only 是系统可信性的基础，正文走人工通道）；
- `capex_to_ocf` 进支柱评分（方向争议留给定性层）。
