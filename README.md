# AlphaStock

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Markets](https://img.shields.io/badge/Markets-A%E8%82%A1%20%7C%20%E6%B8%AF%E8%82%A1%20%7C%20%E7%BE%8E%E8%82%A1-orange)
![Tests](https://img.shields.io/badge/Tests-290-brightgreen)

全市场价值投资研究工具库，覆盖 A 股 / 港股 / 美股。既是**人类可用的交互式选股器**，也是 **AI 助手可自主调用的金融研究工具库**——任何 AI 进入仓库后读取 [`AGENTS.md`](AGENTS.md) 即可专业地回答投资问题。

内置**六位投资大师策略**（巴菲特 / 芒格 / 格雷厄姆 / 利弗莫尔 / 段永平 / 孙宇晨），每位按其**一生风格精华**校准权重与硬门槛——不是刻板印象，而是真实进化后的方法论：巴菲特的"所有者收益"、芒格的"反过来想"、格雷厄姆的"22.5 法则"、利弗莫尔的"关键点+机械止损"、段永平的"不懂不做+不止损"、孙宇晨的"注意力经济"。

内置**持有周期维度**：超短线（1-10 交易日）/ 短线（10日-3月）/ 中线（3月-3年）/ 长线（3年+）四个视角，每个周期有自己的权重、动量测量窗口与门槛——"寒武纪适合中线但不适合长线持有"这类问题第一次有了量化+质性的双层回答框架。

## 两条使用路径

```
人类路径                        AI 路径
┌─────────────────┐            ┌──────────────────────────┐
│ streamlit run    │            │ 读 AGENTS.md → 路由表      │
│   app.py         │            │ ask / compare / overview  │
│ 仪表盘 + 技能管理  │            │ screen --horizon / skill  │
└─────────────────┘            └──────────────────────────┘
```

## 快速开始

```bash
git clone <your-repo-url>
cd alphastock
pip install -r requirements.txt

python -m value_genie fetch          # 拉取全市场数据快照
python -m value_genie screen         # 命令行选股 Top 20（默认 balanced）
python -m value_genie screen --strategy graham   # 用格雷厄姆策略筛选
python -m value_genie screen --horizon short     # 短线周期筛选（10日-3月）
python -m value_genie ask 茶百道      # 单股速览 + 四周期剖面（AI 入口）
streamlit run app.py                 # 交互式网页
```

一键运行测试 + 生成六大大师今日推荐：`python run_recommendations.py`（自动探测 venv）。

运行测试：`python -B -m pytest tests -q`

## 核心能力

| 能力 | 说明 | 命令 |
|---|---|---|
| **全市场选股** | A 股 ~5,400 + 港股 ~2,700 + 美股 ~9,000 只进入初筛，六支柱评分排序 | `screen` |
| **持有周期维度** | 超短线/短线/中线/长线四套权重+动量窗口+门槛；可与任意策略正交组合 | `screen --horizon short` |
| **单股分析** | 实时报价 + 快照基本面 + K 线指标 + **四周期适合度剖面** → 结论 + 百分位 + 风险旗标 | `ask 茶百道 [--evidence] [--json] [--horizon H]` |
| **多股对比** | 2 只以上并排比较：谁更便宜、谁增长更快 | `compare 茶百道 古茗` |
| **市场概览** | 估值中位数、板块分布、宽度指标、Top 名单 | `overview --markets HK --top 10` |
| **持仓深度审视** | 商业模式/护城河/文化/赚钱亏钱路径五维 + 双大师框架 + 组合层风险 | `ask X --evidence` per holding |
| **数据体检** | 快照年龄、K 线新鲜度、覆盖量、失败记录 | `doctor` |
| **数据新鲜度门槛** | 价格敏感命令（ask/compare/overview）代码强制检查：快照缺失/过期>7天直接拦截，过期但可用则警告 | 自动（`--no-check` 可跳过） |
| **策略切换** | 4 预设 + 6 投资大师 + 自定义权重，换策略不重新拉数据 | `screen --strategy buffett` |
| **投资大师** | 六位大师按知名度排序，各自权重+硬门槛+**天然持有周期**忠实还原其方法论 | `strategy list` |
| **技能系统** | 14 个 AI 剧本 + 自我进化（经验遗传）+ 人工微调 | `skill list / note / edit` |
| **交互式网页** | 快照切换、市场勾选、排名表、气泡图、K 线、雷达图 | `streamlit run app.py` |
| **增量更新** | 按日快照落盘，新鲜数据自动复用，二次运行大幅提速 | `fetch`（加 `--refresh` 强制全量） |

## CLI 参考

```bash
# 数据采集
python -m value_genie fetch [--markets A,HK,US] [--refresh]

# 选股筛选（预设 + 大师策略 + 周期视角，可自由组合）
python -m value_genie screen [--strategy balanced|buffett|munger|graham|livermore|duan|sheng|garp|...]
                             [--horizon ultrashort|short|mid|long]
                             [--set value=0.5 quality=0.5]
                             [--top 20] [--markets A,HK] [--snapshot 20260831]

# 策略 / 周期 / 数据源注册表
python -m value_genie strategy list     # 所有策略 + 各自天然持有周期
python -m value_genie horizon list      # 四个持有周期（权重+动量窗口+门槛）
python -m value_genie source list       # 所有数据源

# AI 研究工具
python -m value_genie ask 茶百道 [--evidence] [--json] [--horizon mid] [--no-check]
python -m value_genie compare 茶百道 古茗 [--no-check]
python -m value_genie overview [--markets A,HK] [--top 10] [--no-check]
python -m value_genie doctor

# 技能管理
python -m value_genie skill list
python -m value_genie skill show single-stock-analysis
python -m value_genie skill note single-stock-analysis "经验内容"
python -m value_genie skill edit single-stock-analysis --add-trigger "X还能买吗"
```

`ask` 系列始终拉取**实时报价**，基本面与百分位来自最新快照；名称 / 代码 / 英文 ticker 均可解析（中文直接可用）。

## 面向 AI 的研究武器库

任何 AI 助手（Claude Code / Trae / Cursor）进入仓库后自动读取 [`AGENTS.md`](AGENTS.md)。这不是一堆查询命令，而是一套可自由组合的研究工作流引擎——**工具保证数据、门槛、排序永远正确，AI 贡献数据里没有的东西：叙事、事件、常识与判断**。

### 基础路由（一问一答）

| 用户问 | AI 执行 |
|---|---|
| "你怎么看待茶百道？" | `ask 茶百道` |
| "给我看证据" | `ask 茶百道 --evidence` |
| "茶百道和古茗哪个好？" | `compare 茶百道 古茗` |
| "现在港股有什么机会？" | `overview --markets HK` |
| "数据新鲜吗？" | `doctor` |
| "巴菲特会怎么看X？" | `screen --strategy buffett` + `ask X --evidence` |
| "芒格会怎么看X？/ 反过来想" | `screen --strategy munger` + `ask X --evidence` |
| "格雷厄姆会怎么看X？/ 市场先生" | `screen --strategy graham` + `ask X --evidence` |
| "利弗莫尔会怎么看X？" | `screen --strategy livermore` + `ask X --evidence` |
| "段永平会怎么选X？" | `screen --strategy duan` + `ask X --evidence` |
| "孙宇晨会怎么看X？" | `screen --strategy sheng` + `ask X --evidence` |
| "审视我的持仓 / 深度分析持仓" | 13 号剧本：逐仓 `ask --evidence` + 双大师框架 + 组合层 |
| "短期内最推荐/最被低估的股票？" | `screen --horizon short`（+value 加重 `--set`） |
| "超短线/短线有什么机会？" | `screen --horizon ultrashort`（必须附短炒警示） |
| "X适合中长期持有吗？" | `ask X` 四周期剖面 + 14 号剧本质性层 |

### 进阶玩法（组合拳）

**① 六大师圆桌** — 同一只股票，六种灵魂。`screen --strategy` 跑六遍 + `ask X --evidence`：巴菲特看现金流、芒格反过来想、格雷厄姆算安全边际、利弗莫尔找关键点、段永平问商业模式、孙宇晨嗅注意力。**分歧本身就是信号**——价值派看多而趋势派看空 = 左侧机会区；六人共识 = 大概率已定价。

**② 四周期时钟** — 同一只股票，四台时钟。`ask X` 的四周期剖面直接告诉你它在哪个周期排名最强：茅台式"长线 81 分位 / 超短线 9 分位"（质地股弱短期动量）与周生生式"短线 99.8 分位"（修复启动）是两种完全不同的机会。"适合中线不适合长线"是合法且常见的结论——中期业绩爆发与长期路线风险可以并存（寒武纪模板）。

**③ 逆向尸检（芒格式）** — 别问"它会涨吗"，问"它怎么会死"。`ask X --json` 拿结构化数据，AI 列举所有死法（利润见顶、杠杆断裂、解禁砸盘、技术替代、政策反噬），再逐条对照指标验证。想清楚死法，才配享受涨势。

**④ 持仓体检** — "我 84 美元建仓了 PDD"：AI 对每个仓位跑 `ask` + 联网拉取当日政策/地缘/情绪四要素，输出入场质量评估、加仓窗口、财报验证点、硬止损与止盈区间——把"拿多久"的时间问题，翻译成"什么条件触发就走"的事件问题。深度版见 13 号剧本：五维基本面（商业模式/护城河/文化/赚钱路径/亏钱路径）+ 双大师框架 + 组合层同源风险。

**⑤ 跨市场对峙** — 同一条主线，三个市场，三种定价。`compare` + `overview --markets A,HK`：A 股油运、美股 Dorian LPG、港股中海油共享同一个地缘溢价，AI 找出定价最便宜的那个入口。

**⑥ 策略混血 / 周期混血** — `--set value=0.3 quality=0.3 momentum=0.4`：格雷厄姆的便宜 + 芒格的质量 + 利弗莫尔的趋势。更进一步 `--strategy buffett --horizon short`：**过巴菲特硬门槛的股票里，短线动量最好的是谁**——大师的品味，短线时钟，两个维度正交组合。

**⑦ 每日晨报流水线** — `python run_recommendations.py` 出原始名单（自动跑测试 + 六大师筛选）→ AI 做增量复核：联网核查今日政策与地缘，剔除逻辑受损的标的（快照价早于暴跌的股票、盈利全靠战争溢价的周期顶），浓缩成 5 只带风险触发器的可执行名单。**工具负责不会错的部分，AI 负责数据里没有的部分。**

**⑧ 数据侦探** — `doctor` 体检数据；AI 发现"昨天还在推荐榜的股票今天消失"→ 追查到 SEC 抓取缺口 → `skill note data-ops "..."` 记录盲区。工具的每个盲区被记录、被继承、被下一个 agent 修复——这就是下面的自我进化。

### 技能（skills）与自我进化

`skills/` 目录收录 14 个剧本（6 通用 + 6 投资大师 + 持仓深度审视 + 时间维度框架），每个带触发词与操作步骤。技能是**活文档**，进化分两层：

- **知识层（AI 自主进化）**：AI 回答问题后学到经验，执行 `skill note <id> "经验内容"` 追加一行笔记，自动版本化落盘，后续**所有** AI 自动继承——每个 agent 都站在前任的肩膀上
- **策略层（人类把关）**：笔记经 Streamlit Skills Manager 人工晋升进剧本正文；策略权重与门槛只由人修改

这是有意的分权设计：**AI 进化知识，人类进化策略**——append-only 契约保证 agent 永远不会悄悄改自己的脑。每次修改自动版本化，`skills/.backup/` 保留最近 10 版可回滚。

## 架构

```
Stage 1   全市场行情（clist 分页，100% 覆盖）
          + A 股批量财务（东财 datacenter，含现金流）
          + 美股批量财务（SEC EDGAR XBRL，含经营现金流）
              ↓  硬性门槛 + 初筛评分 → 每市场 Top ~200
Stage 2   候选股日 K 线（东财主源 + 腾讯备源，前复权 300 日）
          + 港股 F10 逐股财务
              ↓  终评六维得分 → master.csv
策略引擎   预设 / 大师策略 / 周期视角 / 自定义权重 → 派生因子(pe_pb 等)
              → 门槛过滤 → 动量窗口按周期切换 → 综合分排名
              ↓
           CLI / CSV / Markdown / Web UI / AI 工具
```

数据按日快照存放：

```
data/snapshots/YYYYMMDD/
├── manifest.json          # 运行清单
├── a_quotes.csv           # A 股全市场行情
├── a_financials.csv       # A 股批量财务
├── us_financials.csv      # 美股 SEC 财务
├── hk_f10.csv             # 港股深度财务
├── kline/A_600519.csv     # 候选股日 K 线
└── master.csv             # 终评主表（六支柱得分）
```

## 评分方法

六支柱因子（各因子先转为**市场内百分位**再取均值，避免跨市场货币与会计口径错配）：

| 支柱 | 因子 | 方向 |
|---|---|---|
| 估值 Value | PE(TTM) / PB / PS / 股息率 / PE×PB（格雷厄姆 22.5 法则派生列） | 越便宜越高分 |
| 成长 Growth | 营收同比 / 净利润同比 / 最新季营收同比 | 越高越好 |
| 质量 Quality | ROE / 毛利率 / 净利率 / 资产负债率 | 后者越低越好 |
| 安全 Safety | 52 周位置 / 波动率 / 距 52 周高点回撤 | 越低位越稳越高分 |
| 动量 Momentum | 近 5 日 / 近 20 日 / 近 3 月 / 近 12 月涨幅（窗口按周期切换） | 越高越好（趋势跟随） |
| 现金流 Cashflow | 经营现金流/市值 / 现金流/净利润 | 越高越好（盈利含金量） |

综合分 = 六支柱加权平均；某支柱缺数据时按剩余权重归一化，少于 3 个支柱不计综合分。旧快照缺 momentum/cashflow/短窗口列时：动量即时从 K 线补算（含 ret_5d/ret_20d/vol_20d），现金流缺失则权重归一并告警——**旧快照无需重抓**。

### 持有周期维度（`horizon list`）

| 周期 | 窗口 | 权重本质（估/成/质/安/动/现） | 动量窗口 | 门槛 |
|---|---|---|---|---|
| **ultrashort 超短线** | 1-10 交易日 | 注意力/动量为王（0/25/5/0/70/0） | ret_5d+ret_20d | 波动率市场内前 50%， ret_5d≥0 |
| **short 短线** | 10日-3月 | 趋势确认+修复启动（20/20/10/15/35/0） | ret_20d+ret_60d | ret_20d≥0 |
| **mid 中线** | 3月-3年 | 估值修复+业绩兑现（30/30/20/10/10/0） | ret_60d+ret_250d | — |
| **long 长线** | 3年+ | 商业模式+现金流（15/20/35/10/0/20） | （权重为 0） | — |

三种用法：`--horizon` 单独用 = 周期即策略；`--strategy X --horizon Y` = 保留大师权重门槛、只切换动量时钟；`ask X` = 自动输出四周期适合度剖面。**价值基因主张中长线**；超短线/短线回答必须附警示与仓位纪律。

### 预设策略

| 预设 | 估值 / 成长 / 质量 / 安全 / 动量 / 现金流 | 灵感 |
|---|---|---|
| **Balanced**（默认） | 35 / 25 / 30 / 10 / 0 / 0 | 多因子均衡 |
| Magic Formula | 50 / 0 / 50 / 0 / 0 / 0 | Greenblatt 神奇公式 |
| GARP | 25 / 45 / 30 / 0 / 0 / 0 | 合理价格的成长 |
| Deep Value | 55 / 0 / 25 / 20 / 0 / 0 | 深度价值 |
| Custom | 网页滑块自定义 | — |

### 投资大师策略（按知名度排序，带硬门槛与天然周期）

每位大师按其**一生风格精华**校准——反刻板印象版：

| # | 大师 | 方法论精髓 | 权重（估/成/质/安/动/现） | 门槛 | 天然周期 |
|---|---|---|---|---|---|
| 1 | **巴菲特** | 从烟蒂进化到特许权；所有者收益 > 会计利润；浮存金引擎 | 25/5/40/10/0/20 | ROE≥15%, 毛利率≥40%, 负债率≤60%, OCF yield≥5% | 长线 |
| 2 | **芒格** | 反过来想（门槛即排除清单）；坐等投资法；便宜平庸才是陷阱 | 15/15/50/5/0/15 | ROE≥20%, 毛利率≥40%, 负债率≤50% | 长线 |
| 3 | **格雷厄姆** | 安全边际是算术不是信仰；22.5 法则（PE×PB≤22.5）；分散=认知诚实 | 50/5/15/20/0/10 | PE×PB≤22.5, 负债率≤50%, ROE≥10% | 中线 |
| 4 | **利弗莫尔** | 关键点交易；坐等大波动；机械止损 10%；纯价格行为不看基本面 | 0/15/10/5/70/0 | ret_60d≥0, 波动率市场内前 50%, 52 周位置≥60% | 短线 |
| 5 | **段永平** | 商业模式优先；不懂不做；不止损（仓位纪律在买入前完成）；拿 10 年 | 20/10/45/10/0/15 | ROE≥20%, 毛利率≥40%, 波动率市场内后 40% | 长线 |
| 6 | **孙宇晨** | 注意力是唯一稀缺资产；叙事领先于资金流；在注意力高潮离场；高 Beta 是偏好 | 0/35/10/0/55/0 | ret_60d≥0, 波动率市场内前 40% | 超短线 |

大师策略门槛为**硬过滤**——不满足门槛的股票直接排除，再按权重排序。快照缺门槛所需列时自动跳过该门槛并告警（不静默清空结果）。加新大师 = 一个 `register_strategy` 调用，加新周期 = 一个 `register_horizon` 调用，不改现有代码。

## 数据源

数据源已抽象为**可扩展注册表**——加新源 = 一个 `register_source` 调用，不改现有代码。

| 数据 | 市场 | 来源 | 说明 |
|---|---|---|---|
| 全市场行情 | A/HK/US | 东方财富 clist 分页 | 最新交易日收盘 |
| 批量财务 | A | 东方财富 datacenter 业绩报表 | 含经营现金流，自动回补上季 |
| 批量财务 | US | SEC EDGAR XBRL frames | 含 NetCashProvidedByUsedInOperatingActivities |
| 深度财务 | HK | 东方财富 F10 主要指标 | 最新 12 个报告期 |
| 日 K 线 | 全部 | 东方财富主源 + 腾讯备源 | 前复权，近 300 交易日 |
| 汇率 | HKD/CNY | 东方财富 | 港股市销率换算 |

全部为公开网页接口，**无需 API Key**。接口限流时自动重试、冷却并切换备用源。

## 项目结构

```
value_genie/
├── fetch/           # 数据采集（行情/财务/K线/管线/数据源注册）
├── strategy/        # 评分引擎（因子/派生因子/复合分/预设/大师/周期/注册表）
├── resolve.py       # 符号解析（名称→市场/代码）
├── analyze.py       # 单股分析引擎（含四周期剖面）
├── overview.py      # 市场概览
├── doctor.py        # 数据体检 + 新鲜度门槛
├── skills.py        # 技能存储与净化
├── report.py        # 快照加载与筛选
├── quotes.py        # 实时行情
├── config.py        # 全局配置
└── __main__.py      # CLI 入口

skills/              # AI 技能剧本（14 个：6 通用 + 6 大师 + 持仓审视 + 时间维度）
tests/               # 290 个单元测试（全离线）
app.py               # Streamlit 网页
run_recommendations.py  # 一键测试 + 六大师今日推荐
AGENTS.md            # AI 助手入口文档
```

## 免责声明

本项目仅为数据研究与量化筛选工具，所有输出由脚本自动生成，**不构成任何投资建议**。数据来自第三方公开接口，可能存在延迟或误差，请以交易所官方数据为准。投资有风险，决策需谨慎。

## License

[MIT](LICENSE)
