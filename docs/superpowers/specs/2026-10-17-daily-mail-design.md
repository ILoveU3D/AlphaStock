# 每日邮件订阅功能设计（Daily Mail）

日期：2026-10-17
状态：待评审

## 背景与目标

北极星服务新增每日一封的邮件：巴菲特股东信质感的中文信，3-5 分钟读完，
发送并抄送给所有订阅用户（目前为用户本人和几位朋友）。发送由用户在
TRAE solo 设置的定时任务触发（每天 10:00），定时任务里 AI 在场。

架构原则（用户已确认）：**AI 撰写 + CLI 送信**——机器聚合素材，AI 写
prose（符合工具包"工具内无 LLM，AI 写 prose"的教义），机器负责送信。

## 邮件内容（三个内容支柱 + 固定页脚）

1. **今日股票推荐**——QMF 融合管道：digest 提供 masters-vote L1 宽池
   素材，AI 在写信时完成 L2-L4 判断并给出唯一推荐（量化只否决、AI 做
   选择）。
2. **AI 讲故事**——AI 用自己的知识储备讲一个投资相关的故事（大师掌故、
   历史案例、书籍教训等），纯 AI 知识，无需 CLI 数据。
3. **订阅者关注股分析**——全部订阅者 watchlist 去重后的逐股速览
   （live 价、估值、旗标 verbatim、一句话判断）。
4. **固定页脚**——data-as-of 一行（数据截至时间，新鲜度契约强制）+
   一行免责声明。任何一天的信都必须声明数据时点。

## 存储层（全部 local-only，gitignored，永不推送）

顶层 `mail/` 目录（与 `users/` 同级，加入 .gitignore）：

- `mail/config.json`——SMTP 配置，手工配置一次：
  ```json
  {
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "username": "发件邮箱@qq.com",
    "auth_code": "QQ邮箱SMTP授权码",
    "from_name": "北极星"
  }
  ```
- `mail/subscribers.json`——订阅名单，CLI 原子写（沿用 users.py 的
  tmp+rename 契约）：
  ```json
  [
    {"name": "...", "email": "...", "watchlist": ["HK:00700", "A:600519"]}
  ]
  ```
  用户本人只是普通订阅者之一，无特殊字段；关注股集合 = 全部订阅者
  watchlist 去重（**不**自动并入任何人的持仓）。
- `mail/sent.log`——发送记录，每成功发送一行 `YYYY-MM-DD`；`mail send`
  发现当天已有记录时拒绝发送，需 `--force` 覆盖（防定时任务重跑刷屏）。

## 命令面

### `python -m polar_star mail digest [--json]`

新鲜度门（与其他数据命令一致：FAIL 直接 BLOCKED 退出 1）。聚合今日素材，
默认打印人类可读摘要，`--json` 输出纯 JSON 素材包：

```json
{
  "date": "2026-10-17",
  "data_as_of": "...(快照时点 + kline 滞后)",
  "l1_pool": [
    {"market": "...", "code": "...", "name": "...", "core_score": 0.0,
     "core_business": 0.0, "core_culture": 0.0, "core_dcf": 0.0,
     "vetoes": ["..."], "graham_g": 0.0, "expectation_gap": 0.0}
  ],
  "watchlist": [
    {"market": "...", "code": "...", "name": "...", "missing": false,
     "price": 0.0, "pct_chg": 0.0, "pe_ttm": 0.0, "pb": 0.0,
     "percentiles": {}, "flags": ["..."]}
  ]
}
```

- `l1_pool`：masters-vote L1 宽池（vote_count≥1 且非硬否决），按
  core_score 排序，含三核分数、否决旗标、Graham 审计显示列。
- `watchlist`：订阅者关注股去重后逐股 ask 摘要（live 报价 + 快照分位 +
  风险旗标 verbatim）。单股解析失败 → 该股 `missing: true` 并记原因，
  AI 在信中如实说明，不编造数字。

### `python -m polar_star mail send --file X.html --subject "..." --data-as-of "..." [--force] [--dry-run]`

不过新鲜度门（送信本身不读行情）。

1. 读取 AI 写好的 HTML 正文片段；
2. 套上固定的股东信排版壳（见下），页脚注入 `--data-as-of` 传入的
   数据时点；
3. 构建 MIME 邮件（text/html + 自动剥离标签生成的 text/plain 备选），
   To: 发件邮箱本人，CC: `subscribers.json` 全部邮箱（与发件邮箱重复
   的地址跳过，避免同址收发件人重复投递）；
4. 经 `smtplib.SMTP_SSL`（标准库，无新依赖）发送；
5. 成功后在 `mail/sent.log` 记当天日期。

- `--dry-run`：打印组装后的邮件（含收件人列表）但不发送，供调试。
- `--subject`：必填，AI 拟的中文主题（如"北极星日报 2026-10-17：..."）。
- 配置缺失/授权码失效 → 退出码 1，打印修复指引（含 QQ 授权码获取路径）。

### `python -m polar_star subscriber add|remove|list`

- `add --name X --email Y [--watch HK:00700,A:600519]`：关注股经正常
  resolve 链解析为 master.csv 形态后存储；
- `remove --email Y`；
- `list [--json]`。

均不过新鲜度门。

## 排版壳（固定 CSS，AI 不可见）

- 衬线字体栈（Georgia, "Songti SC", SimSun, serif），单列 max-width
  640px，行距 1.8，信件式排版，无图片；
- AI 只写正文 HTML 片段（小节标题、段落、少量表格），壳保证任何一天
  发出的信都有统一的股东信质感；
- 页脚由壳固定注入 data-as-of 与免责行（data-as-of 由 send 的
  `--data-as-of` 参数显式传入，取自 digest 输出的 `data_as_of` 字段）。

## 错误处理

| 场景 | 行为 |
|---|---|
| digest 新鲜度 FAIL | `[FRESHNESS BLOCKED]` + 退出 1（与其他命令一致） |
| digest 新鲜度 WARN | 打印 `[FRESHNESS WARN]` 到 stderr，继续并在素材包标注 |
| 单只关注股解析失败 | 素材包中 `missing: true` + 原因，不中断 |
| SMTP 未配置/认证失败 | 退出 1 + 修复指引（不发送、不记 sent.log） |
| 当天已发送 | 退出 1 + 提示 `--force` |
| subscribers.json 为空 | send 拒绝（无收件人），提示先 add |

## 测试（tests/test_mail.py）

- subscriber 增删查：tmp 目录往返，原子写不损坏；
- digest 聚合：合成快照 + 合成订阅名单，验证素材包 schema 与 missing
  股路径；runner 不触网（mock 报价/快照层）；
- send：mock `smtplib.SMTP_SSL`，验证 MIME 结构（To/CC、html+plain
  双格式、subject）、排版壳注入、sent.log 记录与 `--force` 逻辑、
  `--dry-run` 不发送。

## 每日定时任务工作流（TRAE solo 任务定义，非工具包代码）

1. `doctor --json` → 必要时 `fetch`（家规）；
2. `mail digest --json` → AI 读素材；
3. AI 写信（三支柱 + 故事），存 `tmp/letter-YYYYMMDD.html`；
4. `mail send --file ... --subject "..." --data-as-of "..."`；
5. 发送结果记入当日 journal 一行。

## 明确不做（YAGNI）

- 不做个性化分人邮件（一封群发，内容合并）；
- 不做持仓体检、武器库收敛名单、舆情速递板块（第一版三支柱以外不扩）；
- 不做网页退订链接（朋友间服务，退订 = 用户手动 `subscriber remove`）；
- 不引入任何新第三方依赖（smtplib/email 均为标准库）。
