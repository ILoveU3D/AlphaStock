# Master & Registry System Design

> 设计文档：投资大师系统 + 策略/数据源统一注册表

**目标：** 让 AI 能用投资大师的视角分析股票，每位大师有独立的技能剧本、权重预设和硬门槛，同时将策略和数据源抽象为可扩展注册表。

## 1. 三大注册表

### 策略注册表（统一 presets + masters）

```python
@dataclass
class Strategy:
    id: str            # "balanced" / "buffett" / ...
    name: str          # 显示名
    weights: dict      # 6 支柱权重
    gates: list = None # [(column, op, value)] 硬门槛，可空
    kind: str = "preset"  # "preset" | "master"
    skill_file: str = ""  # 大师才有
    triggers: list = None # 大师才有，AI 路由用
```

- `STRATEGIES = {}` 注册表，`register_strategy(s)` 注册
- `--preset` 保留为 `--strategy` 别名（向后兼容）
- 加新策略 = 一个 register 调用

### 数据源注册表（轻量）

```python
@dataclass
class DataSource:
    id: str           # "eastmoney" / "sec_edgar" / "tencent"
    name: str
    capabilities: list  # ["quotes:A", "financials:A", ...]
    fetchers: dict       # {"quotes": fn, "financials": fn}

def register_source(ds): ...
def get_sources(data_type, market) -> list:  # 主源 + 备源
```

## 2. 新增支柱因子

| 支柱 | 因子 | 数据来源 |
|---|---|---|
| momentum | ret_60d, ret_250d | 已有 master.csv |
| cashflow | ocf_yield, cash_conversion | 需扩展 fetch |

PILLARS 从 4 扩为 6，旧预设权重自动归一化。

## 3. 四位大师

| 大师 | id | 权重 | 门槛 |
|---|---|---|---|
| 巴菲特 | buffett | val.30 gro.05 qua.40 saf.10 mom.0 cash.15 | ROE≥15%, 毛利率≥40%, 负债率≤60%, ocf_yield≥5% |
| 段永平 | duan | val.20 gro.10 qua.45 saf.15 mom.0 cash.10 | ROE≥20%, 波动率 pctl≤50 |
| 孙宇晨 | sheng | val.05 gro.35 qua.10 saf.05 mom.45 cash.0 | ret_60d≥0 |
| 利弗莫尔 | livermore | val.0 gro.15 qua.10 saf.0 mom.60 cash.15 | ret_60d≥0, 波动率 pctl≥50 |

## 4. 门槛 DSL

`(column, op, value)`：
- `>=`, `<=` 绝对值比较
- `pctl>=`, `pctl<=` 市场内百分位比较

## 5. 文件清单

| 文件 | 动作 |
|---|---|
| strategy/registry.py | 新建：Strategy + DataSource + 注册表 |
| strategy/masters.py | 新建：4 位大师定义 |
| strategy/factors.py | 修改：PILLARS + PILLAR_FACTORS |
| strategy/presets.py | 修改：预设迁移到注册表 |
| fetch/sources.py | 新建：三源注册 |
| fetch/fundamentals.py | 修改：现金流字段 |
| fetch/pipeline.py | 修改：MASTER_COLUMNS + 源注册表 |
| report.py | 修改：screen() 接受 strategy |
| __main__.py | 修改：CLI 命令 |
| skills/07-10 | 新建：4 个大师剧本 |
| AGENTS.md | 修改：路由表 |
