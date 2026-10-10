# Trading — AI 虚拟盘（Virtual Portfolio）设计文档

日期：2026-09-05
状态：已获用户批准（方案 A + 四处修订）

## 1. 目标

给 AI 一笔虚拟资产自主管理（美股/港股/A股/ETF），通过真实费率、真实交收规则的
模拟交易获得实盘认知；每日盯市 + 复盘 journal 沉淀经验，教训经 Field Notes 进化
成 skills。管理目标为双目标：资产增值 + 可持续的"分红式提款"（withdrawal rate）。

## 2. 架构

- 模块：`value_genie/trade.py`（引擎 + 渲染 + JSON），CLI 子命令组
  `python -m value_genie trade ...`（在 `__main__.py` 注册）。
- 存储：顶层 git-tracked `trading/seasons/<id>.json`（原子写 tmp+rename，复用
  users.py 模式）。虚拟盘历史是不可再生资产，绝不放 `data/`。
- 复用：`resolve()` 符号解析、`recommend.live_price()` 计价（EM 实时 → 快照
  兜底）、manifest FX（`_fx_rates`）、`_check_freshness` 新鲜度门控、
  `--json` 纯 JSON 契约、`report.df_records()`。
- 新增 skill：`skills/15-trading.md`（AI 运作手册：交易决策流程、复盘模板、
  双目标、自我进化纪律经 `skill note trading "..."` append-only 沉淀）。
- AGENTS.md 增补路由行与模块说明。

## 3. 数据模型（season JSON）

```json
{
  "id": "s001", "name": "第一期：港美练手",
  "status": "active",
  "created_at": "...",
  "base_currency": "USD",
  "initial_capital": 2000.0,
  "rules": {"markets": ["US", "HK"], "fx_spread": 0.003},
  "cash": {"USD": 1500.0, "HKD": 0.0, "CNY": 0.0},
  "settling": [
    {"currency": "HKD", "amount": 5000.0, "origin_market": "HK",
     "available_date": "2026-09-08", "fx_date": "2026-09-09"}
  ],
  "positions": [
    {"market": "US", "code": "AAPL", "name": "Apple", "qty": 5.0,
     "avg_cost": 230.0, "currency": "USD",
     "last_buy_date": "2026-09-05", "lot": 1}
  ],
  "fills": [
    {"seq": 1, "ts": "...", "date": "2026-09-05", "action": "buy",
     "market": "US", "code": "AAPL", "qty": 5, "price": 230.0,
     "gross": 1150.0, "fees": {"platform": 1.99},
     "net_cash_delta": -1151.99, "currency": "USD",
     "session": "in", "note": "AI 买入理由"}
  ],
  "nav_history": [
    {"date": "2026-09-05", "nav": 1998.5, "cash_total": 848.5,
     "positions": [{"market": "US", "code": "AAPL", "qty": 5, "price": 230.0}],
     "fx": {"HKD": 0.92, "USD": 7.2}}
  ],
  "journal": [
    {"date": "2026-09-05", "ts": "...", "nav": 1998.5,
     "day_pnl": -1.5, "text": "复盘：为什么赚/亏、继续做什么、避免什么"}
  ],
  "totals": {"deposited": 0.0, "withdrawn": 0.0}
}
```

- `base_currency` / `initial_capital` 期创建后不可改。
- 多期并行：多个 active 期共存，交易命令显式指定 season id；`status` 汇总。
- `rules.markets` 可中途修改，向后生效（已有仓位可卖不可加）。
- `totals` 以基础货币记账（提款按当时汇率折算）。

## 4. 交易引擎规则

### 4.1 费率表（config 常量，券商级模拟）

| 市场 | 券商模型 | 费用 |
|---|---|---|
| A 股 | 中信 | 佣金 max(0.025%, ¥5) 双向；印花税卖出 0.05%（股票，ETF 免）；过户费 0.001% 双向 |
| 港股 | 众安 | 平台费 max(0.05%, HKD 18) 双向；印花税 0.1% 双向 |
| 美股 | 众安 | 平台费 max($0.0099/股, $1.99)，封顶成交额 1.5% |

依据：ZA Bank 2026-02 起 0 佣金 + 平台费结构；中信 A 股默认万 2.5 最低 5 元。

### 4.2 手数规则（买入强制校验，卖出仅校验 ≤ 持有量）

| 市场 | 最低买入 | 递增 | 来源 |
|---|---|---|---|
| A 主板/创业板 (60/00/30) | 100 | 100 | 规则内置 |
| 科创板 (688) | 200 | 1 | 规则内置 |
| 北交所 (8xx/43x/92x) | 100 | 1 | 规则内置 |
| A 股 ETF (5xx/1xx) | 100 | 100 | 规则内置 |
| 港股 | 每手 TRADE_UNIT | 每手 | 东财 F10 ORGPROFILE `TRADE_UNIT` 实时查询（已验证：汇丰 400、腾讯 100、中移动 500），查到后缓存进 fill/position；接口失败可用 `--lot N` 手工指定，否则拒单 |
| 美股 | 1 | 1 | 规则内置（整股，无碎股） |

### 4.3 交易时段

不拒单。任何时刻按 `live_price()` 成交（盘中=实时价，盘外=最近收盘价）。
fill 记 `session: in/out`，复盘透明。节假日按工作日近似（文档注明）。

### 4.4 回转与交收（严格模拟）

- A 股：当日买入不可当日卖（按 `last_buy_date` 拒单）；卖出回款 T+1 可用。
- 港股：当日买卖自由；卖出回款 T+1 可再买港股，T+2 后才可换汇。
- 美股：当日买卖自由；卖出回款 T+1 可用。
- 引擎在 nav/buy/sell/fx 执行前先跑 `settle_due()`：把到期的 settling 并入
  cash，再处理当前命令。

### 4.5 换汇与多币种

- 现金池 {CNY, HKD, USD}；换汇按快照中间价 + 点差（默认 0.3%，每期可调）。
- NAV 估值用中间价；点差只在真实换汇时扣。
- FX 来源：manifest `fx_hkdcny`/`fx_usdcny`，缺失时实时回退（复用现有链路）。

### 4.6 中途注资/提款

`trade cash deposit|withdraw` 一级操作；提款即"分红式生活费"，note 标记用途。

## 5. CLI 命令面

```
python -m value_genie trade
  season new <id> --name ... --base USD --capital 2000 --markets US,HK [--fx-spread 0.003]
  season list / show <id>
  season rule <id> --markets A
  season close|pause|resume <id>
  season delete <id> --confirm
  buy  <id> <stock> --qty 5 [--note "..."] [--lot N]
  sell <id> <stock> --qty 5 [--note "..."]
  fx   <id> USD->HKD --amount 1000
  cash <id> deposit|withdraw --amount 100 --currency USD [--note]
  nav  <id>
  journal <id> --text "..."
  journal <id> --show [--last 5]
  status
```

- 全部支持 `--json`（纯 JSON、全精度、NaN→null）。
- 新鲜度门控：buy/sell/fx/nav/journal/status（价格敏感）；season CRUD 不门控；
  均支持 `--no-check`。
- 拒单时 stderr 给出明确原因（现金不足/交收未到期/手数不合法/市场不在
  规则内/T+1 限制），退出码非 0。

## 6. 双目标指标（nav/status 输出）

- `NAV`（基础货币）
- `净收益率 = (NAV + 累计提款 − 累计注资) / 初始资金`
- `提款率 = 累计提款 / 初始资金`（"幸福感"指标）
- `day_pnl`（对上一 nav_history 条目的日盈亏，基础货币）

## 7. 每日节奏（skill 层，非引擎强制）

- 盯市 ≠ 交易：每次对话开始，AI 检查活跃期 nav_history 最后日期，跨天自动
  跑 `trade nav` 补记——不占用用户授予的"每天 1~2 次操作机会"。
- 交易只由用户指令触发；AI 执行前自查：新鲜度 → 期规则 → 仓位决策 → 成交
  并把买入理由写入 fill note。
- 复盘由用户触发；AI 读 nav 归因 + fills 写 journal；认可的教训经
  `skill note trading "..."` 沉淀（append-only，AI 不改正文）。

## 8. 已知近似（skill 与本文档明示）

分红不模拟；滑点不模拟；节假日按工作日近似；港股手数依赖 F10 接口可用性。

## 9. 测试（tests/test_trade.py，沿用 test_recommend.py 模式）

- monkeypatch `TRADE_DIR` → tmp；手写假快照（manifest 带汇率）；mock
  `live_quote` / FX 网络边界（模块级注入点）。
- 重点用例：三家费率（最低佣金触发/封顶）、手数校验（科创 200、HK TRADE_UNIT、
  --lot 覆盖）、A 股 T+1 当日卖拒单、港股 T+1 再买 / T+2 换汇交收队列、
  点差换汇、NAV 数学（多币种中间价折算）、日盈亏、season CRUD、多期并行、
  拒单错误信息、JSON 纯度、CLI 端到端。

## 10. 不做的事（YAGNI）

- 不做定时任务（对话驱动补记）。
- 不做滑点/分红模拟。
- 不做杠杆/融资融券/期权。
- 不把虚拟盘混入 users/holding/watchlist 体系（完全隔离）。
