# 多用户系统 + 赛季去 dashboard 化 + 渐进式导航 — 设计文档

日期：2026-10-03
状态：设计已获用户批准（brainstorming 三节确认），待实施
分支：feature/multiuser-navigation

## 背景与动机

项目从单用户 demo 演进为复合工程。用户提出三个演进方向（原话要点）：

1. **多用户**：从单用户 OS 迈向多用户 OS。AI 必须清楚当前在与哪位用户对话；
   用户个人信息（风格、持仓）做隐私保护、**永不推送远端**；远端已有的
   `users/me.json` 需清理。
2. **赛季**：赛季不需要 dashboard——AI 是最好的前端，每次让 AI 总结即可；
   赛季为全体用户共享。
3. **Navigation**：为不熟悉北极星的新用户提供渐进式导航，README 改造为
   世界地图，AI 作为唯一前端需要一个触发机制，做成文字页游式的探索导览。

## 已确认的关键决策（用户逐项选定）

| 决策点 | 选定 |
|---|---|
| users/ 远端清理深度 | **只清当前树**（git rm --cached + gitignore + 正常 PR；不重写历史、不 force push main） |
| 登录语义 | **本地指针·无口令**（users/.session 记当前用户 id；真正隐私边界是 git/远端而非本地访问） |
| 导航形态 | **纯无状态导览**（README 世界地图 + navigation skill；不记探索进度，每次对话自成一局） |

## 隐私边界（三类资产，写进 AGENTS.md + README）

| 类别 | 内容 | 远端策略 |
|---|---|---|
| 北极星共同价值 | 代码、skills/、tower/（含 theses）、trading/（赛季）、docs、README、AGENTS.md | 推送 |
| 用户个人疆域 | `users/` 整个目录（风格、持仓、.session 指针） | **永不推送**（gitignore） |
| AI 私有判断 | profiles/、models/ | 永不推送（现有规则不变） |

## F1 多用户

### 现状

- `users/<id>.json` 已支持多用户文件，但目录整体被 git 跟踪且
  `users/me.json` 已在远端 main。
- 无"当前用户"概念：`recommend --user`、`holding *`、`user show`、
  `user set-style` 全部显式传 id。
- 用户风格经 `register_user_strategies()` 注册为 kind="user" 策略。

### 设计

1. **隐私落地**
   - `.gitignore` 增加 `users/`（整目录）。
   - `git rm -r --cached users` 清当前树；本地 `users/me.json` 原样保留。
   - 走特性分支 + PR（不碰「直推 main 禁止」铁律；用户自行开/merge PR）。
2. **session 指针**
   - `users/.session`：纯文本，内容为当前用户 id；随 users/ 一起被 ignore。
   - `users.py` 新增：`current_user()` / `login(user_id)` / `logout()`。
     - login 先 `load_user` 校验存在，再写指针（原子写同 save_user 约定）。
     - logout 删除指针文件。
     - current_user 读指针；文件不存在/内容非法返回 None。
3. **CLI**
   - 新增 `user login <id>`、`user logout`、`user whoami`（当前用户 +
     全部用户列表，--json 兼容）。
   - `user create` 成功后自动 login（新用户即当前用户）。
   - `recommend --user`、`holding add|update|remove|list --user`、
     `user show --user`、`user set-style --user` 的参数改为**可选**：
     缺省取 session 当前用户；无 session 时报错并提示
     `user login <id>` / `user create <id>`。
4. **策略注册**：不变（仍注册全部用户风格；users/ 本地化后无泄漏面）。
5. **AI 侧约定**（AGENTS.md）：涉及个人操作（持仓/推荐/风格）前，
   先 `user whoami` 确认身份；对话中用户报出身份时 AI 主动 login。

### 错误处理

- 指针指向的 user 文件被删：`current_user()` 返回 None（不抛异常），
  命令层报「session 失效，请重新 login」。
- 无 session 且未传 --user：exit 1 + 明确提示，不静默猜用户。

## F2 赛季去 dashboard 化

### 现状

- `trade dashboard <sid>` 写 `trading/dashboards/<sid>.md`；trade.py 中
  `dashboard_path` / `render_dashboard` / `write_dashboard`（约 L820-961）。
- `trading/dashboards/` 已在远端（s001.md、s002.md）。

### 设计

1. **删除**：`trade dashboard` 子命令、上述三个函数、config 中
   dashboards 相关条目；`trading/dashboards/` 从远端树移除并删除本地
   （走同一特性分支 PR）。
2. **不新增命令**：`trade status` / `trade nav` / `trade journal`
   （均 --json 兼容）已提供全部原料，AI 成文总结即前端。
3. **skill 15 改写**：dashboard 段替换为「AI 赛季总结指引」——取
   status（持仓+现金）+ nav（曲线/回撤）+ journal（蒸馏教训）组织成文。
4. **AGENTS.md 路由表**：「看看你的战绩 / 更新看板」行改为
   `trade status/nav/journal → AI 成文总结`；trade 模块说明中
   dashboard 描述同步移除。
5. **赛季共享**：赛季 JSON 结构不变、无 owner 字段——赛季是 AI 的
   虚拟盘，天然全员共享，继续 git 跟踪推送。

## F3 渐进式导航（无状态文字导览）

### 设计

1. **README 重写为世界地图**（保留既有硬性要求）：
   - 顶部保留 DCF 计算公式（```math 块）+ 一行点题 blockquote
     （2026-09-09 用户要求，不可动）。
   - 哲学段保留（DCF 普适法则 / 终值交换 / 北极星使命，精炼）。
   - 新增「世界地图」段：大厅（这是什么、AI 是唯一前端）→ 各区条目，
     每区 2-3 行（是什么 + 入口提示）：交易塔（trading 赛季）、
     认知巴别塔（tower）、论点池（thesis）、大师议事厅（7 大师策略）、
     情报站（intel）、公司画像与财务模型（本地-only）、用户疆域
     （users/，隐私说明）。
   - 架构与方法论压缩至后部（保留核心，删操作手册式内容——AGENTS.md
     才是操作手册）。
2. **新增 `skills/20-navigation.md`**（order 20，YAML frontmatter +
   markdown 标准结构）：
   - triggers：导航 / 新手 / 怎么开始 / 这是什么 / 带我去 / 参观 /
     navigation / tour。
   - 正文规定渐进规则：
     a. 一次只讲一层——先大厅全景（一句话/区），不展开；
     b. 用户点名去哪（"去巴别塔"）才展开该区：是什么、能做什么、
        一个示例命令、出口列表（"还可以去…"）；
     c. 绝不一次倒完整个地图；
     d. 导览词风格：文字页游的探索感，但不虚构游戏状态（无经验值/
        成就/进度——用户明确选了无状态）。
3. **AGENTS.md 路由表**新增一行：「新手/导航/这是什么/带我去…」→
   navigation skill（无对应 CLI 命令，纯讲解）。
4. 无状态：不写任何进度文件；每次对话自成一局。

## 影响面与测试

- `value_genie/users.py`：+session 函数；`value_genie/__main__.py`：
  +login/logout/whoami 子命令、--user 可选化；`value_genie/trade.py`：
  -dashboard 相关；`value_genie/config.py`：-dashboards 条目；
  `.gitignore`：+users/；AGENTS.md / README.md / skills/15 /
  +skills/20。
- 测试：`tests/` 新增 session 指针与 login/whoami 用例；清理引用
  dashboard 的既有用例；`python -B -m pytest tests -q` 全绿为收工标准。
- users.py 模块 docstring 中「git-tracked」表述需同步更正为
  「local-only, never pushed」。

## 不做的事（YAGNI 明示）

- 不做口令/哈希鉴权；不做账户层大重构（session 不渗透 trade/tower 等
  共享命令）；users/ 不改名；导航不记探索进度、不做成就系统；
  不重写 git 历史。
