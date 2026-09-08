# 舆情情报系统（intel）设计

日期: 2026-09-08
状态: 已与用户确认设计方向，待实施
动机: 摩尔线程解禁事件造成 25% 单日亏损——可预知的"时间表事件"没有进入任何预警面。
本系统让事件风险可提前扫描、情报可按需深读。

## 1. 目标与非目标

**目标**
1. 四个舆情子系统，各自独立成模块、可继续扩展第五个：
   - **财报**：预约披露日、业绩预告、财报粉饰信号（量化）、财报原文链接
   - **公告**：解禁、减持、回购、增发等公司公告的抓取、分类、量化
   - **新闻**：个股新闻时间线与热度（不做情绪打分）
   - **投行**：评级与目标价变动历史
2. 覆盖 A / HK / US 三市场，数据源分别建立，统一归一到一套数据模型。
3. 舆情影响最终选股与评价：雷达列进 master.csv → gates DSL 可用；ask / recommend / holding list 输出预警。
4. 全部免费公开接口，零 API key。

**非目标**
- 工具箱内不跑 LLM：intel 负责结构化呈现与量化信号，"专业解读"由 AI agent 按新增 playbook 完成（既有原则）。
- 不做新闻情感打分（正/负词频类粗粒度情绪分不进任何评分）。
- 不修改六支柱 composite 权重——舆情只做否决与预警，不做正面加分（段永平原则：数据只能成为不买的理由）。

## 2. 架构（方案 A：独立 intel 子包 + 双通道）

```
value_genie/intel/
  __init__.py        # import 触发数据源注册（照 fetch/ 惯例）
  model.py           # IntelItem 统一数据模型 + 公告影响映射 + 财报粉饰信号计算
  sources.py         # register_source：扩展 eastmoney + 新增 cninfo/hkexnews/yahoo/stockanalysis
  earnings.py        # 子系统1 财报：预约披露、业绩预告、粉饰信号、原文链接（A/HK/US）
  announcements.py   # 子系统2 公告：解禁/减持/回购/增发（A/HK/US）
  news.py            # 子系统3 新闻：个股新闻时间线（A/HK/US，按需）
  ratings.py         # 子系统4 投行：评级/目标价历史（A/HK/US，按需）
  radar.py           # build_event_radar()：全市场批量事件表 → event_radar.csv + master 合并
  report.py          # intel X 单股深度渲染 + --json
```

扩展轴 = 子系统：新增第 5 个子系统（如龙虎榜、监管处罚）= 新模块 + `sources.py` 一行注册，不改现有代码。

**双通道**
- **雷达通道**（批量、进快照）：`run_fetch()` 尾部、manifest 写入前，`build_event_radar()` 扫描 master 候选 + watchlist 持仓，产出 `event_radar.csv`（事件明细）并把量化列合并进 `master.csv` / `watchlist.csv`。全部走全市场报表类接口（一次拉表、内存 join），不做逐股循环抓取。
- **情报通道**（按需、实时）：`intel X` 命令输出单股深度舆情（新闻时间线、公告清单、投行评级历史、粉饰信号明细、财报原文链接）。

## 3. 统一数据模型（model.py）

```python
@dataclass
class IntelItem:
    market: str          # "A" | "HK" | "US"
    code: str            # 统一快照代码形式（600519 / 00700 / AAPL）
    name: str
    subsystem: str       # "earnings" | "announcements" | "news" | "ratings"
    kind: str            # unlock|holder_cut|buyback|placement|forecast|
                         # report_date|rating|news|filing...
    event_date: date
    title: str
    url: str
    source: str          # eastmoney|cninfo|hkexnews|sec_edgar|yahoo|stockanalysis
    impact: str          # positive|negative|neutral —— 按公告类别静态映射，非情绪打分
    payload: dict        # 结构化明细，见 §4 各 kind 的 payload 定义
```

`impact` 是类别级静态映射（解禁/减持=negative，回购=positive，评级上调=positive…），
不是对文本内容的情绪推断——这层判断留给 AI 解读。

**跨市场语义映射**（同一 kind，不同市场的取数来源）：

| 概念 | A | HK | US |
|---|---|---|---|
| 解禁 | 东财解禁时间表（RPT_LIFT 类报表） | 基石/配售解禁无标准表，配售公告覆盖 | 无解禁概念，锁定期到期见 Form 4/424B |
| 股东减持/增持 | 东财减持计划报表 | 披露易权益披露（DI） | SEC Form 4（内部人交易） |
| 回购 | 东财回购报表 | 披露易购回报表 | EDGAR 8-K 回购公告 |
| 增发/配售 | 东财定增计划 | 披露易配售公告 | EDGAR 424B |
| 业绩预告/预约披露 | 东财 datacenter | 披露易盈警/盈喜公告 | EDGAR 8-K Item 2.02 |

## 4. 数据源（全部免费公开接口）

复用 `fetch/http.py` 的 `Fetcher`（重试/退避/限速/冷却全套），新增单例客户端：`CNINFO`、`HKEX`、`YA`（Yahoo）、`SA`（stockanalysis）。具体端点在实施期验证，最终选定的端点与兜底源记录在 `sources.py` docstring 与 Field Notes。

| 子系统 | A | HK | US |
|---|---|---|---|
| 财报 | 东财 datacenter（预约披露表、业绩预告表）；粉饰信号由已有 a_financials 计算；原文链接=巨潮 | 披露易（盈警/盈喜、年报 PDF）；信号由已有 hk F10/现金流计算 | EDGAR（submissions API 定位 8-K/10-K/10-Q，full-text 检索）；信号由已有 us_financials（XBRL）计算 |
| 公告 | 东财公告列表接口 + 东财解禁/减持/回购/定增 datacenter 报表 | 披露易（HKEXnews 检索）为主，东财港股镜像兜底 | EDGAR full-text + submissions |
| 新闻 | 东财个股新闻接口 | 东财港股新闻接口 | Yahoo Finance 新闻接口 |
| 投行 | 东财研报接口（机构评级 + 目标价） | 东财港股研报接口 | stockanalysis.com（一致评级 + 目标价），Yahoo 兜底 |

**注册表挂法**：`fetch/sources.py` 中扩展 eastmoney 条目的 capabilities（追加 `events:A`、`announce:A`、`news:A`、`ratings:A` 等），并新增 `cninfo`、`hkexnews`、`yahoo`、`stockanalysis` 四个 DataSource 条目（sec_edgar 条目追加 announce/events/financials-text capabilities）。capability DSL 沿用 `"{data_type}:{market}"`。

## 5. 财报粉饰信号（model.py 中的 earnings-quality 计算）

由快照内已有财务数据计算，零额外网络请求，全市场免费覆盖：

| 信号 | 判定（示意，阈值进 config.py） | 数据来源 |
|---|---|---|
| eq_receivables | 应收增速 > 营收增速 + 10pct | a_financials / us_financials(XBRL) |
| eq_inventory | 存货增速 > 营收增速 + 10pct | 同上（可得时） |
| eq_goodwill | 商誉/净资产 > 30% | 同上（可得时） |
| eq_ocf_gap | OCF/净利润 < 0.5（连续两期） | 同上 + a_cashflow |
| eq_nonrecurring | 扣非净利/净利 < 60%（A股专属） | a_financials 扣非列 |

输出：`eq_flags`（计数）+ 明细列表（供 intel X 呈现与 AI 解读）。HK 无扣非概念，仅算可得项。
信号=观察项不是定罪：进入 `risk_flags` 原样呈现，不软化（AGENTS.md 答题规则）。

## 6. 雷达通道（fetch 集成）

### 6.1 执行位置与流程

`pipeline.run_fetch()` 在 `build_master()` / `build_watchlist()` 之后、manifest 写入之前调用：

```
build_event_radar(snapshot_dir, asof_date) -> (radar_df, merge_columns)
  1. 拉全市场事件表（解禁/减持/回购/定增/业绩预告/预约披露，A 全量批表；
     US 用 EDGAR 批量（每日按 form type 拉最新提交）；HK 用披露易/东财镜像批表）
  2. 计算粉饰信号（纯本地计算）
  3. join 到 master 候选 + watchlist 持仓
  4. 写 event_radar.csv（IntelItem 平铺明细：市场/代码/kind/日期/标题/URL/payload 关键列）
  5. 返回待合并列 → pipeline merge 进 master.csv / watchlist.csv
```

断点续跑：event_radar.csv 走 `_load_or_fetch` 惯例；单数据集失败 → 该列 NaN + `manifest.failures` 记录，fetch 不中断。

### 6.2 master.csv / watchlist.csv 新列（MASTER_COLUMNS 扩展）

| 列 | 类型 | 语义 | 无事件时 | 源失败时 |
|---|---|---|---|---|
| unlock_pct_30d | float | 未来30天解禁股数/总股本 % | 0.0 | NaN |
| unlock_pct_90d | float | 未来90天同上 | 0.0 | NaN |
| holder_cut_flag | 0/1 | 存在进行中减持计划（HK=DI 净卖出披露，US=近90天内部人净卖出） | 0 | NaN |
| dilution_flag | 0/1 | 存在进行中增发/配售 | 0 | NaN |
| buyback_active | 0/1 | 回购进行中（正面信号，非红旗） | 0 | NaN |
| report_due_days | int | 距下一预约财报日天数 | 999 | NaN |
| forecast_flag | 0/1/-1 | 业绩预告方向（预增/略增=1，预减/首亏=-1，中性=0） | 0 | NaN |
| eq_flags | int | 粉饰信号计数（§5） | 0 | NaN |
| intel_red | 0/1 | 红旗汇总：unlock_pct_30d≥5 或 holder_cut_flag=1 或 dilution_flag=1 或 eq_flags≥3 | 0 | NaN |

阈值（UNLOCK_RED_PCT=5.0、EQ_FLAG_RED=3、REPORT_DUE_WARN=14）进 `config.py`。
关键语义：**无事件 = 0.0（正面确认），只有源失败才 NaN** ——这样 gates 的 fail-closed 行为只在真正数据缺失时触发，不会因为"没有解禁"而误杀。旧快照缺列时 evaluate_gates 现有行为（WARN + 跳过该 gate）自然兼容。

### 6.3 gates 可用性

雷达列进 master 后，任何策略/用户风格/临时筛选可直接加舆情闸门，如：
`("unlock_pct_30d", "<=", 5.0)`、`("intel_red", "<=", 0)`、`("eq_flags", "<=", 1)`。

### 6.4 大师默认舆情闸门（按各大师人设，用户确认）

| 大师 | 舆情闸门 | 理由 |
|---|---|---|
| buffett | 无 | 事件噪音是市场先生的机会；会计担忧已由 ocf/fcf/borrowed_dividend 闸门覆盖 |
| munger | 无 | 反过来想已由 quality 闸门完成；平常心不追事件 |
| graham | `("dilution_flag", "<=", 0)` | 增发摊薄每股账面价值，直接侵蚀安全边际 |
| livermore | `("unlock_pct_30d", "<=", 5.0)` + `("holder_cut_flag", "<=", 0)` | 事件跳空会击穿他的 10% 止损；已知事件风险前离场是趋势纪律 |
| duan | 无 | 平常心：解禁不改商业模式，不因事件卖票（用户原话"有的大师不会受影响"） |
| sheng | 无 | 注意力与热度是他的燃料；他的风险已由波动率/动量闸门定义 |

用户风格（me）不自动加——由用户/AI 在 set-style 时按需添加。

## 7. 情报通道（intel X 命令）

```
python -m value_genie intel X [--json]        # X 走标准 resolve 链
```

流程：新鲜度门禁（`_check_freshness`，同 ask）→ resolve →
1. 读快照雷达行；不在 master/watchlist 中的股票走单股兜底（照 watchlist 的 per-source fallback 先例：单股查解禁/减持/回购/定增/预告/预约披露）
2. 实时抓：公告清单（近90天，分类+URL）、新闻时间线（近30天）、投行评级历史（近1年）、财报原文链接
3. 粉饰信号明细（快照数据，单股兜底重算）
4. 渲染五个板块：

```
== 舆情情报: 摩尔线程 [A/688795] ==
[事件雷达]  90天内解禁 2026-09-12 占总股本12% (红旗) | 财报预约 10-28 | 减持进行中
[公告时间线] 近90天: 解禁×1 减持×2 回购×0 增发×0（逐条 日期/标题/分类/URL）
[财报信号]  粉饰信号2项：应收增速58%>营收22%；OCF/净利0.4 | 原文: 巨潮链接
[投行评级]  12家覆盖，一致"买入"；最近：中信 08-30 下调至增持 目标价45→38
[新闻时间线] 近30天17条（7日8条）——热度供 AI 结合语境解读，不自动打分
```

`--json` 输出结构化 IntelItem 列表 + 雷达行 + 信号明细（纯 JSON 契约）。

### 7.1 ask 集成

`analyze_stock()` result dict 新增 `intel` 键：雷达行摘要 + 红旗项并入 `risk_flags`（原样呈现不软化）；brief 渲染在 risk flags 计数与 data-as-of 处体现。verdict 措辞规则：存在 intel_red=1 时，verdict 文案自动附红旗提示（不改 verdict 算法本身——否决权在 gates，不在得分）。

### 7.2 recommend / holding list 集成

持仓体检新增"事件预警"块：每只持仓的 解禁倒计时 / 财报日倒计时 / 减持·增发状态 / eq_flags。雷达列合并进 watchlist.csv 后零额外抓取。摩尔线程场景：解禁出现在快照日 → holding list 当天点名。

## 8. 配套改动

- **doctor.py**：新增 event_radar.csv 存在性检查（缺失 → WARN，不 FAIL——舆情缺失允许降级运行）；manifest.failures 中舆情源失败透传 WARN。
- **skills/16-intel.md**：新 playbook。frontmatter: id=intel, triggers=舆情/情报/公告/解禁/研报/评级/财报解读, commands=intel X / screen --strategy ...。正文：AI 解读框架（解禁结构怎么看、评级下调语境、粉饰信号组合、事件与四周期关系），Field Notes 随经验积累。
- **AGENTS.md**：路由表加行（"X的舆情/解禁/公告" → intel skill → `intel X`）；能力清单加舆情子系统；雷达列语义表。
- **README.md**：架构节加 intel 子系统一段。
- **fetch/http.py**：新增 CNINFO/HKEX/YA/SA 四个 Fetcher 单例。
- **config.py**：舆情端点常量 + §6.2 阈值。

## 9. 错误处理与降级

1. 单个子系统/市场源失败：该列 NaN（或 radar 行缺该 kind），`manifest.failures` 记录，doctor WARN，fetch 不中断。
2. 雷达列 NaN 的 gate 行为：fail-closed（与现有 roe 等列一致）；doctor WARN 提示 agent 不要在雷达缺失的快照上跑带舆情闸门的筛选。
3. intel X 单股兜底失败：该板块打印"数据缺失：XX 源失败"，不编造（AGENTS.md 规则 4）。
4. 旧快照（无雷达列）：gates 跳过 + WARN（现有行为）；intel X 提示快照无雷达，全部走单股兜底。

## 10. 测试策略（照 tests/ 现有惯例）

- `test_intel_model.py`：IntelItem 归一化、impact 映射、粉饰信号计算（构造 DataFrame 输入，边界：NaN 列、无扣非数据）
- `test_intel_sources.py`：伪造 API JSON → parse 函数单测（解禁表/减持表/研报/新闻/EDGAR submissions/披露易）
- `test_intel_radar.py`：事件表 fixtures → event_radar.csv 生成 + master 列合并（tmp_path 快照）；无事件=0.0、源失败=NaN 语义
- `test_intel_report.py`：渲染 + --json 结构
- `test_cli.py` 扩展：intel 命令（tmp_path 快照 + mock 单股兜底）、freshness gate 挂载
- `test_masters.py` 扩展：graham/livermore 新 gates 断言
- 网络层 mock 照 `test_http.py` 的 `patch.object(f.session, "get")` 模式

## 11. 实施分期（供 writing-plans 展开）

1. **P1 雷达骨架（A 股先行）**：model + sources 注册 + A 股事件批表（解禁/减持/回购/定增/预告/预约披露）+ 粉饰信号 + radar 集成 fetch + master 列 + doctor + 测试
2. **P2 情报命令**：intel X（A 股全量：公告/新闻/研报 + 渲染 + --json）+ ask 集成 + 测试
3. **P3 三市场补全**：US（EDGAR submissions/full-text、Form 4、Yahoo 新闻、stockanalysis 评级）+ HK（披露易、东财港股镜像）+ 各市场单股兜底
4. **P4 选股与评价收口**：graham/livermore 闸门 + recommend/holding 事件预警块 + skill 16 + AGENTS.md/README + 大师 gates 测试

## 12. 未来扩展（不在本期）

第五子系统挂点：新模块 + sources.py 一行注册 + （可选）雷达新列。候选：龙虎榜、监管处罚/问询函、股权质押、股东户数变化、管理层变动。

## 附录 A：已验证的 A 股事件端点（探针 2026-09-09，P1 直接可用）

全部走 `DC.get_json(config.DC_WEB_URL)`，Eastmoney datacenter 通道：

| 事件 | reportName | 过滤条件 | 关键字段与语义 |
|---|---|---|---|
| 解禁 | `RPT_LIFT_STAGE` | `(FREE_DATE>='{d1}')(FREE_DATE<='{d2}')` | `FREE_DATE` 解禁日；`TOTAL_RATIO` 解禁股/总股本（**小数**，×100=unlock_pct）；`FREE_RATIO` 解禁股/当前流通股本（小数）；`FREE_SHARES` 解禁后流通股本（万股）；`LIFT_MARKET_CAP` 解禁市值（万元）；`NEW` 最新价（元） |
| 股东增减持 | `RPT_SHARE_HOLDER_INCREASE` | `(NOTICE_DATE>='{d}')` | `DIRECTION`（"减持"/"增持"）；`CHANGE_NUM`（万股）；`NOTICE_DATE`/`END_DATE` 窗口；`HOLDER_NAME` |
| 回购 | `RPTA_WEB_GPHG` | `(TDATE>='{d}')` 或 `(GGRQ>='{d}')` | `HGJE` 回购金额（元，JLBZ=CNY）；`HGSL` 回购数量（股）；`GGRQ` 公告日；`TDATE` 交易日；`SCODE`/`SNAME` |
| 定增 | `RPT_SEO_DETAIL` | `(ISSUE_DATE>='{d}')` | `ISSUE_NUM` 发行股数；`ISSUE_SHARE_BEFORE/AFTER` 前后总股本（稀释率=(after-before)/before）；`NET_RAISE_FUNDS` 净募资（元）；`SEO_TYPE`；`ISSUE_DATE` |
| 业绩预告 | `RPT_PUBLIC_OP_NEWPREDICT` | `(NOTICE_DATE>='{d}')(IS_LATEST='T')` | `PREDICT_TYPE`（预增/预减/首亏/扭亏…）；`INCREASE_JZ` 幅度；`NOTICE_DATE` |
| 披露预约 | `RPT_PUBLIC_BS_APPOIN` | `(APPOINT_PUBLISH_DATE>='{d1}')(APPOINT_PUBLISH_DATE<='{d2}')` | `APPOINT_PUBLISH_DATE` 预约日；`IS_PUBLISH`（'0' 未披露）；`REPORT_TYPE_NAME`。三季报预约在 9 月末才挂出，查未来窗口为空是正常时序，不是接口失败 |

**东财 datacenter 探针铁律（写入实施代码注释与 Field Notes）**
1. 字符串过滤值必须用**双引号**：`(SECURITY_CODE="688795")` 可行，单引号在部分报表触发 ANTLR `InputMismatchException`。
2. `RPTA_WEB_GPHG` 调用时**不能带 sortColumns/sortTypes**（"SECURITY_CODE排序列不存在"）；日期字段（FREE_DATE/TDATE/NOTICE_DATE/ISSUE_DATE）范围过滤普遍可行。
3. 过滤字段若非该报表的可过滤列（如 RPT_PUBLIC_BS_APPOIN 的 REPORT_YEAR），整个 filter 会被**静默忽略**返回全表——实现时必须校验返回行数合理性。
4. 单位交叉验证方法：`LIFT_MARKET_CAP(万元)×1e4 / NEW(元)` = 解禁股数，与 `TOTAL_RATIO × 总股本`（来自 quotes）互核。
