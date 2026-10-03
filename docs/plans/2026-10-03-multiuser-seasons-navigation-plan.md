# 多用户 + 赛季去 dashboard + 渐进导航 实施计划

> **For agentic workers:** 按任务序执行，每任务结束即提交。TDD：先写/改测试，确认失败，再实现，再确认通过。步骤用 checkbox 跟踪。

**Goal:** users/ 本地化（隐私）+ session 指针多用户 + 删除 trade dashboard 全链路 + README 世界地图与导航 skill。

**Architecture:** 三特性独立小改（spec：`docs/plans/2026-10-03-multiuser-seasons-navigation-design.md`）。users.py 加 session 三函数；__main__.py 加 login/logout/whoami 并把 --user 全部可选化；trade.py 删 dashboard 区块；文档层改 README/AGENTS/skills。

**Tech Stack:** Python 3.10+，pytest，argparse，无新依赖。

**分支:** `feature/multiuser-navigation`（已创建，spec 已提交于 1fe680b）

---

## 已确认的现状事实（执行时不必重查）

- `value_genie/users.py`：`USER_ID_RE` L26；`users_dir()` L75；`save_user` L152（原子写范式）；模块 docstring L10-13 称 "git-tracked"（需改）。
- `value_genie/__main__.py`：`_load_user_or_exit` L559；`cmd_user` L569-648；`cmd_holding` L670+；`cmd_recommend` L741+；dashboard 处理块 L956-975；user parser 组 L1887-1918；holding parser 组 L1920-1950（`ph_ls` L1943 `default="me"`）；recommend parser L1953-1969（`--user default="me"` L1954）；trade dashboard parser L2070-2074。
- `value_genie/trade.py`：dashboard 区块 = L817-964（注释头 `# Dashboard` + `dashboard_path`/`_fmt_pct`/`_max_drawdown_pct`/`_fees_paid_base`/`render_dashboard`/`write_dashboard`）。`_summary_from`（L679）被 `status_all`（L710）使用——**保留**。`_fmt_pct`/`_max_drawdown_pct`/`_fees_paid_base` 仅被 render_dashboard 使用——随删。`render_season` 从 L967 开始——保留。
- `value_genie/config.py`：L14 `USERS_DIR` 注释；L265 `TRADING_DIR`。无 dashboards 专用条目（dashboard 路径由 trade.py 拼接）。
- 测试：`tests/test_trade.py` L706 `test_dashboard_write_and_render`、L733 `test_cli_dashboard` 待删；`tests/test_users.py` fixture `users_dir`（L14-17，monkeypatch `usr.config.USERS_DIR`）可复用；CLI 测试范式见 L264+（`main([...])` + capsys）。
- skill 规范：frontmatter 必填 `id/title/triggers/commands`（`value_genie/skills.py` L41）；order/version 为 int；正文改写走 `skills.save_skill`（自动备份 + version bump）——本对话用户已明确授权这两处 skill 改动（human-supervised）。
- README：dashboard 引用在 L31、L129、L232-235、L245、L296；users "git 持久" 在 L29、L174；技能数 "18" 在 L91、L133、L290；测试数 "645" 在 L8、L140、L291。
- AGENTS.md：dashboard 出现在路由表行与 freshness gate 命令清单（`trade buy/sell/fx/cash/nav/journal/status/dashboard`）；users 段与 Environment 段称 users/ "git-tracked"。
- 远端：`users/me.json`、`trading/dashboards/{s001,s002}.md` 在 origin/main 树上。

---

## Task 1: users.py session 指针（login/logout/current_user）

**Files:**
- Modify: `value_genie/users.py`（docstring L1-14 + 文件末尾追加函数）
- Test: `tests/test_users.py`（文件末尾追加）

- [ ] **Step 1: 写失败测试**（追加到 tests/test_users.py 末尾）

```python
# ---------------------------------------------------------------------------
# Session pointer (multi-user login)
# ---------------------------------------------------------------------------
def test_session_login_logout_cycle(users_dir):
    usr.create_user("me")
    assert usr.current_user() is None          # no session yet
    usr.login("me")
    assert usr.current_user() == "me"
    assert (users_dir / ".session").read_text(encoding="utf-8") == "me"
    usr.logout()
    assert usr.current_user() is None


def test_login_requires_existing_user(users_dir):
    with pytest.raises(FileNotFoundError):
        usr.login("ghost")


def test_current_user_stale_pointer(users_dir):
    users_dir.mkdir(parents=True, exist_ok=True)
    (users_dir / ".session").write_text("ghost", encoding="utf-8")
    assert usr.current_user() is None          # pointer w/o user file


def test_current_user_garbage_pointer(users_dir):
    users_dir.mkdir(parents=True, exist_ok=True)
    (users_dir / ".session").write_text("NOT A SLUG!!", encoding="utf-8")
    assert usr.current_user() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_users.py -k session or login or stale or garbage -q`
Expected: 4 FAILED（`AttributeError: module 'value_genie.users' has no attribute 'login'` / `current_user`）

- [ ] **Step 3: 实现**（users.py 两处）

模块 docstring L10-13 改为：

```python
Files live under ``users/<user_id>.json`` (top-level, LOCAL-ONLY —
gitignored and never pushed to any remote, user mandate 2026-10-03;
deliberately NOT under the cleanable ``data/`` tree) and stay
human-readable; all writes are atomic (tmp file + rename), the same
contract as skills persistence. The session pointer ``users/.session``
(plain-text current user id) shares the same local-only boundary.
```

文件末尾追加：

```python
# ---------------------------------------------------------------------------
# Session pointer (who is the AI talking to)
# ---------------------------------------------------------------------------
SESSION_FILE = ".session"


def session_path() -> Path:
    return users_dir() / SESSION_FILE


def current_user():
    """Logged-in user id; None when no session / stale / garbage pointer.

    Never raises: the session file is a hint, not a lock — command
    layers decide how to ask the human to log in again."""
    try:
        uid = session_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not uid or not USER_ID_RE.match(uid):
        return None
    try:
        if not user_path(uid).exists():
            return None
    except ValueError:
        return None
    return uid


def login(user_id: str) -> str:
    """Point the session at an existing user; FileNotFoundError if unknown."""
    load_user(user_id)  # validates existence + readability
    p = session_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".session.tmp")
    tmp.write_text(user_id, encoding="utf-8")
    tmp.replace(p)
    return user_id


def logout() -> None:
    """Drop the session pointer; idempotent."""
    try:
        session_path().unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_users.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```powershell
git add value_genie/users.py tests/test_users.py
git commit -m "users: session pointer (login/logout/current_user) + local-only docstring"
```

---

## Task 2: CLI user login/logout/whoami + create 自动 login

**Files:**
- Modify: `value_genie/__main__.py`（cmd_user L569-648 + user parser 组 L1887-1918）
- Test: `tests/test_users.py`（末尾追加）

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_cli_login_whoami_logout(users_dir, capsys):
    from value_genie.__main__ import main
    assert main(["user", "whoami"]) == 1       # no session yet
    assert main(["user", "create", "me"]) == 0  # create auto-logs-in
    assert usr.current_user() == "me"
    assert main(["user", "whoami"]) == 0
    assert "me" in capsys.readouterr().out
    assert main(["user", "logout"]) == 0
    assert usr.current_user() is None
    assert main(["user", "login", "me"]) == 0
    assert usr.current_user() == "me"
    with pytest.raises(SystemExit):
        main(["user", "login", "ghost"])


def test_cli_whoami_json(users_dir, capsys):
    from value_genie.__main__ import main
    main(["user", "create", "me"])
    capsys.readouterr()
    assert main(["user", "whoami", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"current": "me", "users": ["me"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_users.py -k "cli_login or whoami" -q`
Expected: FAILED（argparse: invalid choice 'whoami' / 'login'）

- [ ] **Step 3: 实现**

cmd_user：在 `if args.user_cmd == "create":` 块的 `print(...)` 前插入 `usr.login(u.id)`，print 改为：

```python
        print(f"created user {u.id} ({u.name}) -> {usr.user_path(u.id)}; "
              f"logged in as {u.id}")
```

在 `if args.user_cmd == "list":` 之前插入三个新分支：

```python
    if args.user_cmd == "login":
        try:
            usr.login(args.user_id)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"logged in as {args.user_id}")
        return 0

    if args.user_cmd == "logout":
        usr.logout()
        print("logged out")
        return 0

    if args.user_cmd == "whoami":
        cur = usr.current_user()
        items = usr.list_users()
        if args.json:
            print(json.dumps({"current": cur,
                              "users": [u.id for u in items]},
                             ensure_ascii=False))
            return 0 if cur else 1
        if cur is None:
            print("no active session; `user login <id>` or "
                  "`user create <id>`")
        else:
            print(f"current user: {cur}")
        if items:
            print("users: " + ", ".join(u.id for u in items))
        return 0 if cur else 1
```

（`json` 在 __main__.py 顶部已 import；若未 import 则顶部补 `import json`。）

parser 组：在 `pu_create` 之后、`pu_sub.add_parser("list", ...)` 之前插入：

```python
    pu_login = pu_sub.add_parser("login", help="point the session at a user")
    pu_login.add_argument("user_id")
    pu_sub.add_parser("logout", help="drop the session pointer")
    pu_whoami = pu_sub.add_parser(
        "whoami", help="current session user + all users")
    pu_whoami.add_argument("--json", action="store_true",
                           help="machine-readable JSON output")
```

同时把 `user show` / `user set-style` 的 positional 改为可选（为 Task 3 铺路，此处一并改）：

```python
    pu_show.add_argument("user_id", nargs="?", default=None)
    ...
    pu_style.add_argument("user_id", nargs="?", default=None)
```

cmd_user 的 show / set-style 分支首行改用 Task 3 的 `_resolve_user_id_or_exit(args)`（先写，Task 3 定义该函数后立即可用——两任务同 commit 窗口内完成，测试在 Task 3 统一跑）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_users.py -k "cli_login or whoami" -q`
Expected: 2 PASS

- [ ] **Step 5: 提交**

```powershell
git add value_genie/__main__.py tests/test_users.py
git commit -m "cli: user login/logout/whoami + create auto-login"
```

---

## Task 3: --user 全面可选化（缺省 = session 当前用户）

**Files:**
- Modify: `value_genie/__main__.py`（`_load_user_or_exit` 附近加解析函数；cmd_holding L670+；cmd_recommend L741+；parser L1920-1969）
- Test: `tests/test_users.py`、`tests/test_recommend.py`

- [ ] **Step 1: 写失败测试**

tests/test_users.py 末尾追加：

```python
def test_cli_user_show_defaults_to_session(users_dir, capsys):
    from value_genie.__main__ import main
    main(["user", "create", "me"])
    capsys.readouterr()
    assert main(["user", "show"]) == 0         # no id arg, uses session
    assert "== user me ==" in capsys.readouterr().out


def test_cli_no_session_no_user_errors(users_dir):
    from value_genie.__main__ import main
    with pytest.raises(SystemExit):
        main(["user", "show"])                 # nothing to fall back on
```

tests/test_recommend.py 末尾追加（复用该文件既有 fixture，照抄 L253-264 的夹具组合）：

```python
def test_cli_recommend_defaults_to_session_user(<同既有 fixture 签名>):
    usr.create_user("me")
    usr.login("me")
    rc = main(["recommend", "--data-dir", str(data_dir),
               "--no-check"])
    assert rc == 0
```

（实现时打开 tests/test_recommend.py L253-290，复制 test_cli_recommend 的 fixture 签名与快照夹具，仅去掉 `--user me`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_users.py -k "session" -q; python -B -m pytest tests/test_recommend.py -k "session" -q`
Expected: FAILED（show 缺 positional / recommend 无 session 解析）

- [ ] **Step 3: 实现**

`_load_user_or_exit`（L559）之后插入：

```python
def _resolve_user_id_or_exit(args, attr="user_id"):
    """Explicit --user/id wins; else the session's current user."""
    from . import users as usr
    uid = getattr(args, attr, None)
    if uid:
        return uid
    cur = usr.current_user()
    if cur is None:
        raise SystemExit(
            "no user specified and no active session; "
            "`user login <id>` / `user create <id>` first, "
            "or pass the user id explicitly")
    return cur
```

cmd_user 的 show 分支 L598：`args.user_id` → `_resolve_user_id_or_exit(args)`；set-style 分支 L632 同改。
cmd_holding：L674 / L696 / L711 / L725 的 `args.user_id` → 各分支首行 `user_id = _resolve_user_id_or_exit(args)` 后替换引用（add 分支的 auto-create 保留：显式 id 不存在时仍自动建并 login——在 auto-create 后追加 `usr.login(user.id)`）。
cmd_recommend L747：`args.user` → `_resolve_user_id_or_exit(args, "user")`。

parser：
- L1943 `ph_ls.add_argument("user_id", nargs="?", default=None)`（去掉 `default="me"`）
- L1923 / L1930 / L1940（add/update/remove 的 positional）加 `nargs="?", default=None`
- L1954 `pr.add_argument("--user", default=None, help="user id (default: session current user)")`

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_users.py tests/test_recommend.py tests/test_cli.py -q`
Expected: 全 PASS（test_cli.py L811 显式传 "me" 的用例不受影响）

- [ ] **Step 5: 提交**

```powershell
git add value_genie/__main__.py tests/test_users.py tests/test_recommend.py
git commit -m "cli: --user optional everywhere, defaults to session current user"
```

---

## Task 4: 隐私落地 — gitignore users/ + 清远端当前树

**Files:**
- Modify: `.gitignore`、`value_genie/config.py` L14 注释

- [ ] **Step 1: 改 .gitignore**

L10-11 注释中的 `users/ dir` 提法已过时，改为：

```
# data/ is regenerable run-time state (snapshots, kline cache) — safe to
# wipe daily
data/
output/

# User territory is LOCAL-ONLY (user mandate 2026-10-03): styles,
# holdings and the session pointer are private — never pushed to any
# remote. Multi-user boundary: shared = code/skills/tower/trading;
# personal = users/.
users/
```

- [ ] **Step 2: config.py 注释**

L14 改为：

```python
USERS_DIR = BASE_DIR / "users"    # local-only user territory, never pushed
```

- [ ] **Step 3: 清当前树并验证**

```powershell
git rm -r --cached users
git check-ignore users/me.json   # 期望输出 users/me.json（已被忽略）
git status --short               # 期望：D users/me.json（cached 删除），本地文件仍在
```

本地 `users/me.json` 文件必须仍在磁盘上（`ls users` 确认）。

- [ ] **Step 4: 提交**

```powershell
git add .gitignore value_genie/config.py
git commit -m "privacy: users/ goes local-only (gitignore + untrack; local files kept)"
```

---

## Task 5: 删除 trade dashboard 全链路

**Files:**
- Modify: `value_genie/trade.py`（删 L817-964）、`value_genie/__main__.py`（删 L956-975 与 L2070-2074）
- Delete: `tests/test_trade.py` L706-745 两个用例、`trading/dashboards/`

- [ ] **Step 1: 先删测试**

tests/test_trade.py：删除 `test_dashboard_write_and_render`（L706 起）与 `test_cli_dashboard`（L733 起）两个完整函数（注意保留夹具与其后用例；若夹具 `prices` 仅被这两个用例使用则一并删——实现时 grep 确认）。

Run: `python -B -m pytest tests/test_trade.py -q`
Expected: PASS（删除后剩余用例全绿；若有 import 残留引用 `write_dashboard` 先报错属预期，下一步清）

- [ ] **Step 2: 删 trade.py 区块**

删除 L817-964：从 `# -----...` 注释头 `# Dashboard (per-season markdown, committed to git for public review)` 起到 `write_dashboard` 函数结束（L964 空行前），保留下方 `render_season`（L967）。共 6 个对象：`dashboard_path`、`_fmt_pct`、`_max_drawdown_pct`、`_fees_paid_base`、`render_dashboard`、`write_dashboard`。

- [ ] **Step 3: 删 __main__.py 两处**

- cmd_trade 中 `if cmd == "dashboard":` 整块（L956 起至其 `return 0` 结束，约 L975）
- parser：`pt_db = pt_sub.add_parser("dashboard", ...)` 三行（L2070-2074）

- [ ] **Step 4: 删 dashboards 目录**

```powershell
git rm -r trading/dashboards
```

- [ ] **Step 5: 全量回归**

Run: `python -B -m pytest tests -q`
Expected: 全 PASS（dashboard 相关引用清零：`Grep "dashboard" value_genie tests` 应无结果）

- [ ] **Step 6: 提交**

```powershell
git add value_genie/trade.py value_genie/__main__.py tests/test_trade.py
git commit -m "trade: remove dashboard pipeline — AI is the scoreboard (status/nav/journal)"
```

---

## Task 6: skill 15 赛季总结指引 + AGENTS.md 交易/多用户段

**Files:**
- Modify: `skills/15-trading.md`（经 skills.py API，自动备份+版本 bump）、`AGENTS.md`

- [ ] **Step 1: skill 15 正文改写 + 新 Field Note**

用 Python 经 skills.py 机制执行（保证备份与版本号）：

```powershell
python -B -c "from value_genie import skills; from pathlib import Path; \
sd = Path('skills'); \
s = skills.find_skill(sd, 'trading'); \
s.body = s.body.replace('''## Answer shape for \"你的盘怎么样\"''', '''## Season summaries (AI is the scoreboard)

trade dashboard 命令已移除（2026-10-03 用户决定）：不再生成任何
Markdown 看板。被问「战绩怎么样 / 总结赛季」时，取
`trade status --json`（持仓+现金+提款率）+ `trade nav <id> --json`
（净值曲线/回撤）+ `trade journal <id> --show --json`（复盘蒸馏），
由 AI 成文总结——结论先行（NAV + 当日盈亏 + 净收益 + 提款率），
再持仓表，再一句话仓位意图，引用 nav-as-of 日期。

## Answer shape for \"你的盘怎么样\"'''); \
skills.save_skill(sd, s, author='ai'); \
skills.append_note(sd, 'trading', 'MANDATE 2026-10-03: trade dashboard command removed; season summaries are AI-composed from status/nav/journal --json — never regenerate Markdown dashboards', author='user')"
```

（实现时先 `Read` skills.py 的 `save_skill`/`append_note` 签名确认参数名，再执行；执行后 `python -m value_genie skill list` 验证 trading 版本 bump 且无格式错误。）

- [ ] **Step 2: AGENTS.md 编辑**（逐一精确替换）

a) 路由表行：
旧：`| "看看你的战绩 / 更新看板" | trading | `python -m value_genie trade dashboard <season>` (writes `trading/dashboards/<id>.md`, commit it) |`
新：`| "看看你的战绩 / 总结赛季" | trading | `python -m value_genie trade status/nav/journal --json` → AI 成文总结（无 dashboard，AI 即看板） |`

b) freshness gate 命令清单：
旧：`trade buy/sell/fx/cash/nav/journal/status/dashboard` run a **freshness gate**`
新：`trade buy/sell/fx/cash/nav/journal/status` run a **freshness gate**`

c) Users 段首句：
旧：`Users live in `users/<id>.json` (top-level git-tracked dir, one file per user; human-readable, CLI-maintained, atomic writes).`
新：`Users live in `users/<id>.json` (top-level LOCAL-ONLY dir, gitignored and never pushed to any remote — user mandate 2026-10-03; one file per user, human-readable, CLI-maintained, atomic writes). The session pointer `users/.session` records who the AI is talking to.`

d) Users 段命令行：
旧：`Commands: `user create|list|show|set-style` ...`
新：`Commands: `user create|list|show|set-style|login|logout|whoami`（create 后自动 login；show/set-style 的 id 可省略，缺省取 session 当前用户）...`（其余保留）

e) Routing table 上方补一条多用户家规（插入在 `## Users, styles and holdings` 段末）：

```markdown
**Multi-user house rule (2026-10-03):** before any personal operation
(holdings / recommend / set-style), run `user whoami` to confirm who
you are talking to; when the human states their identity, `user login
<id>` first. Shared North-Star assets (code / skills / tower / theses /
trading seasons) are pushed; user territory (`users/`) and AI judgment
(`profiles/`, `models/`) never leave the machine.
```

f) Environment 段：
旧：`Per-user profiles live in the top-level git-tracked `users/` dir — modify them only through the `user` / `holding` CLI commands, never by hand.`
新：`Per-user profiles live in the top-level LOCAL-ONLY `users/` dir (gitignored, never pushed) — modify them only through the `user` / `holding` CLI commands, never by hand.`

g) 路由表 navigation 行（追加到路由表末尾）：

```markdown
| "新手 / 导航 / 这是什么 / 带我去X / 参观" | navigation | 无专用命令——按 skills/20-navigation 渐进讲解（AI 即导览，一次只讲一层） |
```

- [ ] **Step 3: 验证**

Run: `python -B -m pytest tests/test_skills.py -q` + `python -m value_genie skill list`
Expected: PASS；trading 版本 +1

- [ ] **Step 4: 提交**

```powershell
git add skills/15-trading.md skills/.backup AGENTS.md
git commit -m "skills+agents: season summaries via AI (no dashboard), multi-user session house rule"
```

（skills/.backup/ 在 gitignore 中——`git status` 确认只有 15-trading.md 与 AGENTS.md 入库；backup 文件不 add。）

---

## Task 7: skills/20-navigation.md（渐进式无状态导览）

**Files:**
- Create: `skills/20-navigation.md`
- Test: `tests/test_skills.py`（若其中断言语料数量/清单需更新，实现时 grep 确认）

- [ ] **Step 1: 创建文件**

```markdown
---
id: navigation
title: Navigation — 北极星世界导览（渐进式文字探索）
order: 20
triggers:
  - 导航
  - 新手
  - 怎么开始
  - 这是什么
  - 这是什么项目
  - 带我去
  - 参观
  - 介绍一下
  - navigation
  - tour
commands:
  - user whoami
  - skill list
  - tower stats
  - trade status
version: 1
updated_at: 2026-10-03T00:00:00
---

# Playbook

北极星对新用户是一张世界地图，AI 是唯一的向导。本技能规定导览的
节奏：**渐进、无状态、文字页游感**——不记任何进度，每次对话自成
一局，但任何时候用户都能从大厅重新出发。

## 渐进规则（硬约束）

1. **一次只讲一层**：用户说"这是什么/新手/导航"时，只给大厅全景——
   每个区域一句话，绝不展开。结尾给出可去的地方列表，把选择权交给
   用户。
2. **点名才展开**：用户说"去巴别塔/看看交易塔"才展开该区：是什么
   （两行）、能做什么（三条以内）、一个示例提问（不是命令语法——
   用户只对 AI 说话）、出口列表（"还可以去…"）。
3. **绝不一次倒完整个地图**：一次回复最多展开一个区域。
4. **无游戏状态**：不虚构经验值/成就/进度；探索感来自节奏与措辞，
   不来自假状态。
5. 用户是谁先于导览：涉及个人疆域（持仓/推荐/风格）的话题，先
   `user whoami`；未登录则把"创建你的疆域"作为导览的第一站。

## 大厅全景（导览词骨架）

- **交易塔（trading 赛季）**：AI 的虚拟盘，真实费率下的赛季实战，
  战绩靠账本不靠自述。
- **认知巴别塔（tower）**：180+ 块思想砖，DCF 是唯一公理，被证伪
  的砖永不删除。
- **论点池（thesis）**：塔砖断言变成选股候选——昨天的错误，明天
  替你选股。
- **大师议事厅（masters）**：七位大师按各自一生方法论给股票投票。
- **情报站（intel）**：解禁/减持/公告/研报/新闻，先搜证再定性。
- **画像与模型室（profiles/models）**：AI 读公司原文蒸馏商业模式
  与文化的地方，本地-only。
- **用户疆域（users）**：每位用户的风格与持仓，永不离开这台机器。

## 展开模板（每个区域套用）

1. 是什么（≤2 行）→ 2. 你能做什么（≤3 条，用提问示例而非命令）→
3. 一个最经典的去处/玩法 → 4. "还可以去：…"（出口列表）。

语气：向导而非说明书；像文字页游的房间描述，短句，有画面感，
不堆砌命令语法（命令是 AI 自己的事）。
```

- [ ] **Step 2: 验证索引**

Run: `python -m value_genie skill list` + `python -B -m pytest tests/test_skills.py -q`
Expected: navigation 出现在列表（order 20）；测试全绿（若 test_skills.py 硬编码了技能数量，同步更新）

- [ ] **Step 3: 提交**

```powershell
git add skills/20-navigation.md tests/test_skills.py
git commit -m "skills: navigation playbook (progressive stateless tour)"
```

---

## Task 8: README 重写为世界地图

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 保留不动区**

L1-15（标题/badges/math 公式/blockquote 点题）原样保留——2026-09-09 用户硬性要求。badge 中 Tests 计数在 Task 9 更新。

- [ ] **Step 2: 逐处修改**

a) L29 用户画像段：`每位用户一份 git 持久化档案` → `每位用户一份本地持久档案（users/ 目录 gitignored，永不推送远端——用户疆域不出本机）`；段末补：`多用户系统：AI 经 session 指针（user login/whoami）确认正在服务的用户。`

b) L31 虚拟盘段：删 `战绩公开可审计：[第一期看板（s001）](trading/dashboards/s001.md) · [第二期看板（s002）](trading/dashboards/s002.md)。`，改为 `战绩由 AI 即时成文总结（trade status/nav/journal）——AI 即看板，不再生成静态文件。`

c) 在「交互模式」段（L37-45）之后新增「世界地图」段：

```markdown
## 世界地图（新用户从这里出发）

对 AI 说"**导航**"或"**这是什么**"，AI 会作为向导带你逐区探索——
一次只讲一层，你点名去哪，它才展开哪。

| 区域 | 一句话 |
|---|---|
| **交易塔** | AI 的虚拟盘赛季：真实费率、交收、整手规则下的实战账本 |
| **认知巴别塔** | 180+ 块思想砖砌成的哲学库，DCF 唯一公理，伤疤永不删除 |
| **论点池** | 塔砖断言注入选股候选池——昨天的错误，明天替你选股 |
| **大师议事厅** | 七位投资大师按各自方法论给全市场投票 |
| **情报站** | 解禁/减持/公告/研报/新闻，先搜证再定性 |
| **画像与模型室** | AI 读公司原文蒸馏商业模式与文化（本地-only） |
| **用户疆域** | 你的风格与持仓——永不离开这台机器 |
```

d) L129 trade 能力行：删 `与**每期 Markdown 看板**（持仓 + 战绩 + 复盘，git 提交即可公开检视）` → `与复盘日志；赛季总结由 AI 成文（AI 即看板）`。

e) L174：`用户档案独立于快照，存放在 git 追踪的 `users/` 目录；` → `用户档案独立于快照，存放在本地-only 的 `users/` 目录（gitignored，永不推送）；`。

f) 「AI 虚拟盘」专节：删 L232-235「看板直达」块，替换为一行 `**赛季总结**：对 AI 说"总结一下第 N 期"，AI 取 status/nav/journal 成文——AI 即看板。`；删 L245「每期看板」bullet；L230 后 `管理目标双轨` 段保留。

g) L296 项目结构：删 `trading/dashboards/  # ...` 行。

h) L91 / L133 / L290：`18 个 AI 剧本` → `19 个 AI 剧本`（+navigation）。

i) 「工程契约」段（L135-140）末尾追加：

```markdown
- **资产三分边界（2026-10-03）**：北极星共同价值（代码 / skills /
  tower / trading 赛季 / docs）推送远端；用户疆域（users/：风格、
  持仓、session）与 AI 私有判断（profiles/、models/）gitignored，
  永不离开本机。
```

- [ ] **Step 3: 渲染检查**

通读改后全文：无 dashboard 残留引用（`Grep "dashboard|看板" README.md` 仅允许出现「AI 即看板」表述）、无 "git 追踪的 users/" 表述。

- [ ] **Step 4: 提交**

```powershell
git add README.md
git commit -m "readme: world-map navigation + privacy boundary + de-dashboard"
```

---

## Task 9: 全量回归 + 推送

- [ ] **Step 1: 全量测试**

Run: `python -B -m pytest tests -q`
Expected: 全 PASS。记录总数，更新 README badge（L8）与 L140/L291 的测试数。

- [ ] **Step 2: 残留扫描**

```powershell
# 以下 grep 均应无命中（除 AI 即看板 / 历史 Field Notes / spec 文档）
```
- `Grep "write_dashboard|render_dashboard|dashboard_path" value_genie tests`
- `Grep "dashboard" value_genie`
- `git ls-files users`（应为空——users/ 已 untrack）
- `git status --short`（users/me.json 不出现于 tracked 变更）

- [ ] **Step 3: 提交计数更新并推送**

```powershell
git add README.md
git commit -m "readme: test count update"
git push -u origin feature/multiuser-navigation
```

- [ ] **Step 4: 交付说明**

告知用户：分支已推送，请在 GitHub 自行开 PR 并 merge（铁律：AI 不开 PR、不直推 main）。merge 后远端 HEAD 不再含 users/me.json 与 trading/dashboards/（历史提交仍可见——用户已选"只清当前树"）。

---

## Self-Review 记录

- **Spec 覆盖**：F1（Task 1-4）、F2（Task 5-6）、F3（Task 7-8）+ AGENTS/README 边界（Task 6/8）全部有对应任务；spec「不做的事」无任务——正确。
- **Placeholder**：无 TBD/TODO；测试代码完整（test_recommend 的 session 用例标注了"复制既有 fixture 签名"——属有意指引，非占位，因 fixture 名以文件内实况为准）。
- **类型一致**：`login()`/`logout()`/`current_user()`/`session_path()` 命名在 Task 1-3 一致；`_resolve_user_id_or_exit(args, attr=)` 签名在 Task 3 定义与使用一致（recommend 用 `attr="user"`）。
- **风险点**：Task 2 Step 3 中 show/set-style 的 `_resolve_user_id_or_exit` 在 Task 3 才定义——两任务在同一连续执行窗口内完成，若单独执行 Task 2 测试（不含 show/set-style 用例）不受影响。
