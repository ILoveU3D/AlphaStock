# 价值投资精灵 Value Genie

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Markets](https://img.shields.io/badge/Markets-A%E8%82%A1%20%7C%20%E6%B8%AF%E8%82%A1%20%7C%20%E7%BE%8E%E8%82%A1-orange)
![Tests](https://img.shields.io/badge/Tests-220%2B%20passed-brightgreen)

全市场价值投资研究工具库，覆盖 A 股 / 港股 / 美股。既是**人类可用的交互式选股器**，也是 **AI 助手可自主调用的金融研究工具库**——任何 AI 进入仓库后读取 [`AGENTS.md`](AGENTS.md) 即可专业地回答投资问题。

## 两条使用路径

```
人类路径                        AI 路径
┌─────────────────┐            ┌──────────────────────────┐
│ streamlit run    │            │ 读 AGENTS.md → 路由表      │
│   app.py         │            │ ask / compare / overview  │
│ 仪表盘 + 技能管理  │            │ skill note (自我净化)      │
└─────────────────┘            └──────────────────────────┘
```

## 快速开始

```bash
git clone <your-repo-url>
cd value-genie
pip install -r requirements.txt

python -m value_genie fetch          # 拉取全市场数据快照
python -m value_genie screen         # 命令行选股 Top 20
python -m value_genie ask 茶百道      # 单股速览（AI 入口）
streamlit run app.py                 # 交互式网页
```

运行测试：`python -B -m pytest tests -q`

## 核心能力

| 能力 | 说明 | 命令 |
|---|---|---|
| **全市场选股** | A 股 ~5,400 + 港股 ~2,700 + 美股 ~9,000 只进入初筛，四维评分排序 | `screen` |
| **单股分析** | 实时报价 + 快照基本面 + K 线指标 → 结论 + 百分位 + 风险旗标 | `ask 茶百道 [--evidence] [--json]` |
| **多股对比** | 2 只以上并排比较：谁更便宜、谁增长更快 | `compare 茶百道 古茗` |
| **市场概览** | 估值中位数、板块分布、宽度指标、Top 名单 | `overview --markets HK --top 10` |
| **数据体检** | 快照年龄、K 线新鲜度、覆盖量、失败记录 | `doctor` |
| **策略切换** | 4 预设 + 4 投资大师 + 自定义权重，换策略不重新拉数据 | `screen --strategy buffett` |
| **投资大师** | 巴菲特/段永平/孙宇晨/利弗莫尔视角选股（可扩展注册表） | `strategy list` |
| **技能系统** | 10 个 AI 剧本 + 自我净化 + 人工微调 | `skill list / note / edit` |
| **交互式网页** | 快照切换、市场勾选、排名表、气泡图、K 线、雷达图 | `streamlit run app.py` |
| **增量更新** | 按日快照落盘，新鲜数据自动复用，二次运行大幅提速 | `fetch`（加 `--refresh` 强制全量） |

## CLI 参考

```bash
# 数据采集
python -m value_genie fetch [--markets A,HK,US] [--refresh]

# 选股筛选（预设 + 大师策略）
python -m value_genie screen [--strategy balanced|buffett|garp|duan|sheng|livermore|...]
                             [--set value=0.5 quality=0.5]
                             [--top 20] [--markets A,HK] [--snapshot 20260831]

# 策略与数据源注册表
python -m value_genie strategy list     # 列出所有策略（预设 + 大师）
python -m value_genie source list       # 列出所有数据源

# AI 研究工具
python -m value_genie ask 茶百道 [--evidence] [--json] [--no-check]
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

## 面向 AI 的研究工具库

任何 AI 助手（Claude Code / Trae / Cursor）进入仓库后自动读取 [`AGENTS.md`](AGENTS.md)，按路由表把投资问题转化为工具调用：

| 用户问 | AI 执行 |
|---|---|
| "你怎么看待茶百道？" | `ask 茶百道` |
| "给我看证据" | `ask 茶百道 --evidence` |
| "茶百道和古茗哪个好？" | `compare 茶百道 古茗` |
| "现在港股有什么机会？" | `overview --markets HK` |
| "数据新鲜吗？" | `doctor` |
| "巴菲特会怎么看X？" | `screen --strategy buffett` + `ask X --evidence` |
| "段永平会怎么选X？" | `screen --strategy duan` + `ask X --evidence` |
| "孙宇晨会怎么看X？" | `screen --strategy sheng` + `ask X --evidence` |
| "利弗莫尔会怎么看X？" | `screen --strategy livermore` + `ask X --evidence` |

### 技能（skills）与自我净化

`skills/` 目录收录 10 个剧本（6 个通用 + 4 个投资大师），每个带触发词与操作步骤。技能是**活文档**，有两条净化路径：

- **AI 自净化**：回答问题后学到经验，执行 `skill note <id> "经验内容"` 追加一行笔记，后续所有 AI 自动继承
- **人工微调**：Streamlit 应用的 **Skills Manager** 页面可视化编辑技能、晋升/删除笔记

每次修改自动版本化，`skills/.backup/` 保留最近 10 版可回滚。Agents 只追加笔记、不改写剧本正文——保持系统可信。

## 架构

```
Stage 1   全市场行情（clist 分页，100% 覆盖）
          + A 股批量财务（东财 datacenter，含现金流）
          + 美股批量财务（SEC EDGAR XBRL，含经营现金流）
              ↓  硬性门槛 + 初筛评分 → 每市场 Top ~200
Stage 2   候选股日 K 线（东财主源 + 腾讯备源，前复权 300 日）
          + 港股 F10 逐股财务
              ↓  终评六维得分 → master.csv
策略引擎   预设 / 大师策略 / 自定义权重 → 门槛过滤 → 综合分排名
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
└── master.csv             # 终评主表（四维得分）
```

## 评分方法

六支柱因子（各因子先转为**市场内百分位**再取均值，避免跨市场货币与会计口径错配）：

| 支柱 | 因子 | 方向 |
|---|---|---|
| 估值 Value | PE(TTM) / PB / PS / 股息率 | 越便宜越高分 |
| 成长 Growth | 营收同比 / 净利润同比 / 最新季营收同比 | 越高越好 |
| 质量 Quality | ROE / 毛利率 / 净利率 / 资产负债率 | 后者越低越好 |
| 安全 Safety | 52 周位置 / 波动率 / 距 52 周高点回撤 | 越低位越稳越高分 |
| 动量 Momentum | 近 3 月涨幅 / 近 12 月涨幅 | 越高越好（趋势跟随） |
| 现金流 Cashflow | 经营现金流/市值 / 现金流/净利润 | 越高越好（盈利含金量） |

综合分 = 六支柱加权平均；某支柱缺数据时按剩余权重归一化，少于 3 个支柱不计综合分。

### 预设策略

| 预设 | 估值 / 成长 / 质量 / 安全 / 动量 / 现金流 | 灵感 |
|---|---|---|
| **Balanced**（默认） | 35 / 25 / 30 / 10 / 0 / 0 | 多因子均衡 |
| Magic Formula | 50 / 0 / 50 / 0 / 0 / 0 | Greenblatt 神奇公式 |
| GARP | 25 / 45 / 30 / 0 / 0 / 0 | 合理价格的成长 |
| Deep Value | 55 / 0 / 25 / 20 / 0 / 0 | 深度价值 |
| Custom | 网页滑块自定义 | — |

### 投资大师策略（带硬门槛）

| 大师 | 核心关注 | 权重 | 门槛 |
|---|---|---|---|
| **巴菲特** | 现金流 + 质量 + 安全边际 | 30/5/40/10/0/15 | ROE≥15%, 毛利率≥40%, 负债率≤60%, OCF yield≥5% |
| **段永平** | 平常心 + 质量优先 | 20/10/45/15/0/10 | ROE≥20%, 波动率市场内后 50% |
| **孙宇晨** | 热点敏感 + 动量跟随 | 5/35/10/5/45/0 | ret_60d≥0（趋势必须向上） |
| **利弗莫尔** | 趋势 + 纪律 + 动量 | 0/15/10/0/60/15 | ret_60d≥0, 波动率市场内前 50% |

大师策略门槛为**硬过滤**——不满足门槛的股票直接排除，再按权重排序。加新大师 = 一个 `register_strategy` 调用，不改现有代码。

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
├── strategy/        # 评分引擎（因子/复合分/预设/大师/注册表）
├── resolve.py       # 符号解析（名称→市场/代码）
├── analyze.py       # 单股分析引擎
├── overview.py      # 市场概览
├── doctor.py        # 数据体检
├── skills.py        # 技能存储与净化
├── report.py        # 快照加载与筛选
├── quotes.py        # 实时行情
├── config.py        # 全局配置
└── __main__.py      # CLI 入口

skills/              # AI 技能剧本（10 个：6 通用 + 4 投资大师）
tests/               # 220+ 单元测试（全离线）
app.py               # Streamlit 网页
AGENTS.md            # AI 助手入口文档
```

## 免责声明

本项目仅为数据研究与量化筛选工具，所有输出由脚本自动生成，**不构成任何投资建议**。数据来自第三方公开接口，可能存在延迟或误差，请以交易所官方数据为准。投资有风险，决策需谨慎。

## License

[MIT](LICENSE)
