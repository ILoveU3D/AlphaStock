# 认知巴别塔（Cognitive Tower）设计文档

日期：2026-09-18
状态：已与用户对齐（v3：DCF 单核 · 平面结构 · 无接口内生化）

## 1. 愿景与定位

**走出乌合之众，寻求宇宙、资本与人性的真理。**

认知巴别塔是把对话中产生的思想从"聊天记录"变成"资产"的规范存放地
（canonical home）：可查询、可累积、可证伪、不怕遗忘。投资哲学只是
它的一个子集——塔是处世哲学、生存哲学的完整载体。

五大功能（用户 2026-09-18 确立）：

1. **展示认知高度**——`tower stats` 输出诚实数字：已验证核心的深度、
   吸收经典的广度、生长速度、伤疤数。
2. **不断通过对话进化**——双向强制循环家规（查塔义务 + 入塔义务）。
3. **DCF 核心不变 + 百家表皮 + 向外扩张**——全塔唯一 axiom 是 DCF
   普适法则；105 本书砖 + 大师砖 + 对话砖自由连接；tags 开放，新领域
   = 新 tag，零结构改动。
4. **精神永久化存续**——git-tracked `tower/` 顶层目录（同 users/、
   trading/ 模式），不惧 data/ 日清、对话压缩、模型更换；refuted 砖
   永不删除。
5. **回答人生问题不模棱两可**——裁决纪律（§9）。

### 命名与结构哲学

- **名字**：认知巴别塔（cognitive tower）。巴别塔只是名字，不承载
  建筑隐喻——**无楼层、无层级、无承重链**。
- **核心是 DCF**：查塔作答时以 DCF 为透镜；入塔时标注与核心的关系；
  与 DCF 冲突的洞见不删除、标 `tension`（矛盾是思考的素材）。
- **内生性原则（用户 2026-09-18 确立："没必要加接口，这是内生性的"）**：
  塔不是工具箱的一个"能力"——不进路由表（除 philosophy 行改指塔）、
  不新增 skill 文件、06 号技能不留指向。书是外采的石料，对话是代谢
  过程，塔是长出来的结构。`tower` 子命令是 AI 的手（确定性解析、
  原子写入、备份、版本），不是面向人的功能入口。
- **塔 vs skills 的分工**：塔 = 知识库（知道什么）；skills = 行为手册
  （怎么回答）。两者分离，互相引用。

## 2. 砖（Brick）数据模型

每块砖一个 `.md` 文件，存于 `tower/<id>.md`（扁平目录，强化"无层级"）。
格式 = YAML 子集 frontmatter（纯量 + 字符串列表，复用 skills.py 的
迷你解析器契约，零新依赖）+ markdown 正文。

```yaml
---
id: dcf-universal-law
title: DCF 普适法则
statement: 一切价值皆是未来现金流的折现——股票如此，职业如此，时间亦如此。
source: conversation:2026-09-08
status: axiom
tags:
  - epistemology
  - value
version: 1
created_at: 2026-09-08T00:00:00
updated_at: 2026-09-18T12:00:00
---
## 论证
（从哪来、凭什么成立、适用边界；书砖 = 核心论点 2-4 句）

## 适用与反例
（可选；诚实标注）

## Field Notes
- [2026-09-18 14:00] (ai) 首次成砖，自 06 号技能普世法则迁入
```

### 字段规范

| 字段 | 必填 | 规则 |
|---|---|---|
| `id` | ✓ | 小写 slug（`^[a-z0-9][a-z0-9-]*$`），与文件名 stem 一致 |
| `title` | ✓ | 人读标题（中文可） |
| `statement` | ✓ | 一句话蒸馏（frontmatter 纯量；长论证放正文） |
| `source` | ✓ | `book:书名` \| `master:名` \| `conversation:YYYY-MM-DD` \| `ai` |
| `status` | ✓ | `axiom` \| `mission` \| `law` \| `principle` \| `hypothesis` \| `observation` \| `refuted` |
| `tags` | ✗ | 自由多值，仅检索无结构含义；推荐种子集见 §7 |
| `links` | ✗ | 列表项 `type:target-id`，target 必须存在 |
| `version` | 自动 | 每次持久化 +1 |
| `created_at` | 自动 | 首次成砖时间，此后不变（stats 的塔龄由此计算） |
| `updated_at` | 自动 | ISO 时间戳 |

### 认知状态（思想复利的质量维度）

| status | 含义 | 约束 |
|---|---|---|
| `axiom` | 地基公理 | **全塔唯一**，id 固定为 `dcf-universal-law`；代码强制唯一性 |
| `mission` | 使命（被选择的终点，非被发现的真理） | 少量；北极星使命在此 |
| `law` | 定律——被我们的对话/生活验证过，跨域成立 | 升迁须附理由 |
| `principle` | 原则——已采纳的运行规则（书砖/大师砖默认入口状态） | |
| `hypothesis` | 假说——有希望，未验证 | |
| `observation` | 观察——对话产出的原始洞见，升迁候选 | |
| `refuted` | 已证伪——**永不删除**（被证伪的思想也是资产） | 降级须附证据 |

状态迁移规则（代码强制，`tower set` 执行）：

- 升迁（observation→hypothesis→principle→law，可跳级）：必须附
  `--reason`，自动写入 Field Notes 一条迁移记录。
- 降级为 `refuted`：必须附 `--reason`（证据），同样入档。
- `axiom` 不可经 `set` 赋予（唯一性由 seed 建立，`add --status axiom`
  直接拒绝并提示已有公理）。
- 状态只进档案不销毁：每次迁移都是一条带时间戳的 Field Note。

### links 类型（5 种，封闭集）

| type | 语义 |
|---|---|
| `derives-from` | 从某砖严格推出（终值交换 derives-from DCF） |
| `refines` | 细化/发展某砖 |
| `contradicts` | 与某砖矛盾 |
| `applies-to` | 某砖在本域的应用（跨域迁移轨道） |
| `tension` | 张力——共存但未解决的紧张关系 |

链接目标不存在 → 报错并列出可用 id。`contradicts`/`tension` 不影响
砖的存在，只标记关系。

### Body 约定

- `## 论证`：必填（书砖 = 核心论点 2-4 句 + 三条砖坯提示）
- `## 适用与反例`：可选
- `## Field Notes`：append-only，格式与 skills 完全一致
  （`- [YYYY-MM-DD HH:MM] (ai|human) text`），复用 NOTE_RE 解析

## 3. 存储与持久化

- 位置：顶层 `tower/` 目录（git-tracked，**绝不**放 data/）。
- 扁平 `tower/<id>.md`；备份 `tower/.backup/<id>/`（保留最近 10 版，
  同 skills 契约）。
- 写入：tmp 文件 + rename 原子写；每次写入前 roundtrip 校验
  （render→parse 必须无损），失败则拒绝落盘。
- 版本：每次持久化 version+1、刷新 updated_at。
- 塔文件只能经 CLI 修改（同 users/ 铁律，AI 是唯一操作者；git 历史
  是审计轨迹）。Body 允许经 `tower set --stdin-body` 修订（版本化 +
  备份），Field Notes 只增不减。

## 4. 模块设计

### `value_genie/tower.py`（核心模块）

复用 `skills.py` 的通用件：`parse_frontmatter` / `_fmt_scalar` /
`_write_atomic` / `_backup` / `NOTE_RE`（import，不复制）。

公开 API（对齐 skills.py 风格）：

```python
@dataclass
class Brick:
    id: str
    title: str
    statement: str
    source: str
    status: str
    tags: list
    links: list          # ["type:target", ...]
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    path: Path | None = None

STATUSES = ("axiom", "mission", "law", "principle",
            "hypothesis", "observation", "refuted")
LINK_TYPES = ("derives-from", "refines", "contradicts",
              "applies-to", "tension")

def parse_brick(text, path=None) -> Brick          # 校验 + 构建
def render_brick(b) -> str                         # roundtrip-safe 序列化
def load_bricks(tower_dir) -> tuple                # (bricks, errors)
def find_brick(tower_dir, key) -> Brick
def field_notes(b) -> list                         # 复用 skills 的解析
def save_brick(tower_dir, b, author="ai") -> Path  # 备份+版本+原子写
def add_brick(tower_dir, b) -> Brick               # 重复 id / 链接目标 / axiom 唯一性校验
def append_note(tower_dir, brick_id, text) -> Brick
def add_link(tower_dir, brick_id, link) -> Brick   # type 与 target 校验
def set_brick(tower_dir, brick_id, status=None, reason=None,
              add_tags=None, drop_tags=None, body=None) -> Brick
def search_bricks(tower_dir, query) -> list        # 子串匹配 id/title/statement/tags/body
def tower_stats(tower_dir) -> dict                 # §6
```

与 skills.py 的差异（为何独立模块而非扩展 skills）：
- 语义不同（知识砖 vs 行为手册），校验规则不同（statement 必填、
  status 枚举、links 校验、axiom 唯一性）；
- 写权限模型不同：skills 是 "agents append-only, body human-only"；
  塔是 "AI 全权操作（本仓库无人类 UI），git 审计"。

### `value_genie/tower_seed.py`（种子数据）

`SEED_BRICKS: list[dict]`——全部 154 块种子砖的完整内容（id/title/
statement/status/source/tags/links/正文）。以数据模块形式进 git，
一次 code review 可全览。`tower seed` 幂等执行：已存在的 id 跳过
（不覆盖、不 bump 版本），`--dry-run` 预览。

### `value_genie/config.py`

新增 `TOWER_DIR = "tower"`（顶层，同 USERS_DIR 模式）。

## 5. CLI

`python -m value_genie tower <sub>`，全部支持 `--json`（纯 JSON、全
精度、无 banner，与既有契约一致）。

```
tower list [--status S] [--tag T] [--kind book|master|conversation|ai] [--json]
tower show <id> [--json]
tower add <id> --title T --statement S --status ST --source SRC
            [--tag X]... [--link type:id]... [--stdin-body] [--json]
tower note <id> "text"
tower link <id> type:target-id
tower set <id> [--status S --reason "..."] [--add-tag T] [--drop-tag T]
              [--stdin-body] [--json]
tower search <query> [--json]
tower stats [--json]
tower seed [--dry-run] [--json]
```

- `--kind`：按 source 前缀过滤（book/master/conversation/ai）。
- `tower set --status` 强制要求 `--reason`（升迁理由 / 证伪证据），
  自动追加迁移记录到 Field Notes。
- **不经过 freshness 门**：塔不依赖行情快照（区别于 ask/recommend
  等）；AGENTS.md 明确此点。
- `--stdin-body`：正文从 stdin 读（PowerShell 长中文参数转义地狱的
  规避）；未提供时 body 生成最小模板（论证节占位文字 "（待论证）"）。

## 6. `tower stats` = 认知高度报告

控制台形态：

```
== 认知巴别塔 ==
核心     axiom ×1：DCF 普适法则（唯一公理）
使命     mission ×n：<标题列表>
定律     law ×n（经对话/生活验证）：<标题列表>
吸收     principle ×n（藏书 105 + 大师 18，借来未验证）
待验     hypothesis ×n / observation ×n
伤疤     refuted ×n（永久保留，错误的资产化）
张力     tension 链接 ×n
生长     近30天 +n 砖、+n notes；塔龄 n 天（首砖日期）
总计     n 砖 / n notes
```

`--json` 输出同构字典。无虚荣指标，全部诚实数字。

## 7. 种子清单（154 块）

### 7.1 核心 6 块

| id | title | status | source | links |
|---|---|---|---|---|
| `dcf-universal-law` | DCF 普适法则 | axiom | conversation:2026-09-08 | —（全塔唯一公理） |
| `north-star-mission` | 北极星使命 | mission | conversation:2026-09-08 | applies-to:dcf-universal-law |
| `terminal-value-swap` | 终值交换 | law | conversation:2026-09-08 | derives-from:dcf-universal-law |
| `compounding` | 复利 | law | conversation:2026-09-08 | derives-from:dcf-universal-law |
| `falsificationism` | 证伪主义 | law | book:猜想与反驳 | refines:dcf-universal-law |
| `bayesian-updating` | 贝叶斯更新 | law | book:超预测 | refines:dcf-universal-law |

DCF 普适法则、终值交换、北极星使命三块：**正文论证自 06 号技能
Universal laws 原文迁入（一字不改），statement 为一句话蒸馏**。
falsificationism 与 bayesian-updating 直接以 law 入塔的依据：二者
已在我们的对话中被反复验证（摩尔三证伪集、v40→v54 审计链、贝叶斯
更新 vs 迎合的区分），非借来未验。

### 7.2 大师砖 18 块（status=principle，source=master:名）

| 大师 | 砖 |
|---|---|
| Buffett | franchise-moat 护城河与特许经营权；circle-of-competence 能力圈；time-is-friend 时间是优秀企业的朋友 |
| Munger | invert-always 反过来想；latticework 多元思维格栅；wonderful-at-fair 以合理价格买伟大公司 |
| Graham | mr-market 市场先生；margin-of-safety 安全边际；price-vs-value 价格与价值的分离 |
| Livermore | pivotal-points 关键点；risk-discipline 纪律先于观点 |
| Duan | business-model-first 商业模式第一（买股票就是买公司）；data-cannot-buy 数据只能构成不买的理由；three-nevers 三个不做（不做空/不借钱/不做不懂的） |
| Sheng | attention-economy 注意力经济与叙事动量 |
| 散户乙 | free-shares 赚免费股票（成本收回）；never-sell-for-price 从不为价格卖出 |
| 鳄鱼 | ten-thousand-year-demand 一万年需求测试 |

哲学内核蒸馏，非量化门槛（门槛留在 strategy registry）。

### 7.3 对话砖 25 块（自 06 号技能 54 条 Field Notes 提炼；原始出处
日期附在各砖 Field Notes，不复制原文全文）

| id | title | status | 来源日期 |
|---|---|---|---|
| career-dcf-three-axes | 职业 DCF 三轴画像（终值依赖度/前置加载度/形状匹配） | law | 2026-09-11 |
| consumption-pricing | 消费的 DCF 定价学（按时机×资本定价） | law | 2026-09-12 |
| terminal-value-two-forms | 终值双层论（年金 vs 资本） | law | 2026-09-11 |
| terminal-value-vehicle-rotation | 终值载体轮动定律 | hypothesis | 2026-09-11 |
| personal-tv-three-laws | 个人终值轨迹三定律 | hypothesis | 2026-09-11 |
| tv-machine-six-layers | 终值机器六层架构 | principle | 2026-09-12 |
| keyhole-philosophy | 钥匙孔哲学（一生 20 孔） | law | 2026-09-09 |
| keyhole-two-species | 钥匙孔双物种与三出口 | principle | 2026-09-12 |
| attention-isomorphism | 注意力同构原理 | law | 2026-09-12 |
| reference-frame-drift | 参照系漂移检测 | principle | 2026-09-12 |
| counterfactual-three-gates | 反事实三闸 | principle | 2026-09-12 |
| complementary-error-theorem | 互补误差定理（择偶） | hypothesis | 2026-09-12 |
| multiples-caliber-rule | 口径规则（倍数必标口径且实算） | law | 2026-09-15 |
| market-cap-arithmetic-gate | 市值算术闸门（"下一个X"解毒剂） | law | 2026-09-12 |
| scarcity-multiple-rule | 稀缺-倍数规则 | law | 2026-09-12 |
| verify-before-narrative | 信息核查原则（先搜再定性） | law | 2026-09-14 |
| three-layer-attribution | 归因三层拆解（单因子解释大回撤=红旗） | law | 2026-09-13 |
| ipo-anchor-rule | IPO 锚规则 + 制度-生意相关性 | principle | 2026-09-12 |
| comp-governance | comp 治理规则（分支倍数锚定 comp 表） | principle | 2026-09-12 |
| pendulum-detection | 摆锤检测（恐慌/悔恨/贪婪三态） | principle | 2026-09-12 |
| evidence-vs-appeasement | 新证据改概率 ≠ 对方不满改结论 | law | 2026-09-12 |
| nokia-warning | 诺基亚警告（信息与偏见同居） | law | 2026-09-12 |
| platform-vs-asic | 平台 vs ASIC（负载变形定律） | hypothesis | 2026-09-12 |
| counterfactual-inflation | 反事实通胀（平行宇宙里住着更强的你） | law | 2026-09-12 |
| consensus-priority | 大师共识优先原则 | principle | 2026-09-04 |

### 7.4 藏书砖 105 块（status=principle，source=book:书名）

诚实口径：借来的智慧未经我们的生活验证；对话中真正调用/验证后升
law、并从书砖分形出独立砖。正文 = 核心论点 2-4 句 + 三条砖坯。

**epistemology（4）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 1 | 猜想与反驳 | 卡尔·波普尔 | epistemology, science |
| 2 | 科学革命的结构 | 托马斯·库恩 | epistemology, science |
| 3 | 超预测 | 菲利普·泰特洛克 | epistemology, forecasting |
| 4 | 谈谈方法 | 勒内·笛卡尔 | epistemology, method |

**world（27）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 5 | 国富论 | 亚当·斯密 | world, economics |
| 6 | 资本论 | 卡尔·马克思 | world, economics |
| 7 | 通往奴役之路 | 弗里德里希·哈耶克 | world, economics, politics |
| 8 | 就业、利息和货币通论 | 约翰·梅纳德·凯恩斯 | world, economics |
| 9 | 大转型 | 卡尔·波兰尼 | world, economics |
| 10 | 利维坦 | 托马斯·霍布斯 | world, politics |
| 11 | 论自由 | 约翰·斯图亚特·穆勒 | world, politics |
| 12 | 论美国的民主 | 托克维尔 | world, politics |
| 13 | 旧制度与大革命 | 托克维尔 | world, politics, history |
| 14 | 罗马帝国衰亡史 | 爱德华·吉本 | world, history |
| 15 | 1984 | 乔治·奥威尔 | world, politics, fiction |
| 16 | 美丽新世界 | 阿道司·赫胥黎 | world, politics, fiction |
| 17 | 娱乐至死 | 尼尔·波兹曼 | world, media |
| 18 | 万历十五年 | 黄仁宇 | world, history, china |
| 19 | 乡土中国 | 费孝通 | world, china, sociology |
| 20 | 置身事内 | 兰小欢 | world, china, economics |
| 21 | 实践论 | 毛泽东 | world, china, epistemology |
| 22 | 矛盾论 | 毛泽东 | world, china, method |
| 23 | 变化的世界秩序 | 瑞·达利欧 | world, history, macro |
| 24 | 枪炮、病菌与钢铁 | 贾雷德·戴蒙德 | world, history |
| 25 | 人类简史 | 尤瓦尔·赫拉利 | world, history |
| 26 | 未来简史 | 尤瓦尔·赫拉利 | world, future |
| 27 | 今日简史 | 尤瓦尔·赫拉利 | world, future |
| 28 | 规模 | 杰弗里·韦斯特 | world, systems |
| 29 | 集体行动的逻辑 | 曼瑟尔·奥尔森 | world, politics, economics |
| 30 | 权力与繁荣 | 曼瑟尔·奥尔森 | world, politics, economics |
| 31 | 国家为什么会失败 | 德隆·阿西莫格鲁 | world, politics, economics |

**human-nature（11）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 32 | 乌合之众 | 古斯塔夫·勒庞 | human-nature, crowd |
| 33 | 思考，快与慢 | 丹尼尔·卡尼曼 | human-nature, bias |
| 34 | 影响力 | 罗伯特·西奥迪尼 | human-nature, persuasion |
| 35 | 自私的基因 | 理查德·道金斯 | human-nature, evolution |
| 36 | 稀缺 | 塞德希尔·穆来纳森 | human-nature, scarcity |
| 37 | 社会性动物 | 埃利奥特·阿伦森 | human-nature, social |
| 38 | 正义之心 | 乔纳森·海特 | human-nature, moral |
| 39 | 象与骑象人 | 乔纳森·海特 | human-nature, mind |
| 40 | 怪诞行为学 | 丹·艾瑞里 | human-nature, bias |
| 41 | 群体的智慧 | 詹姆斯·苏罗维基 | human-nature, crowd |
| 42 | 美德的起源 | 马特·里德利 | human-nature, evolution |

**capital（20）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 43 | 聪明的投资者 | 本杰明·格雷厄姆 | capital, value-investing |
| 44 | 证券分析 | 格雷厄姆/多德 | capital, value-investing |
| 45 | 穷查理宝典 | 查理·芒格 | capital, wisdom |
| 46 | 巴菲特致股东的信 | 巴菲特/坎宁安 | capital, value-investing |
| 47 | 投资最重要的事 | 霍华德·马克斯 | capital, cycles |
| 48 | 金融炼金术 | 乔治·索罗斯 | capital, reflexivity |
| 49 | 这次不一样 | 莱因哈特/罗格夫 | capital, crisis |
| 50 | 疯狂、惊恐和崩溃 | 金德尔伯格 | capital, crisis |
| 51 | 债务危机 | 瑞·达利欧 | capital, debt |
| 52 | 黑天鹅 | 纳西姆·塔勒布 | capital, risk |
| 53 | 反脆弱 | 纳西姆·塔勒布 | capital, risk |
| 54 | 随机漫步的傻瓜 | 纳西姆·塔勒布 | capital, risk |
| 55 | 非对称风险 | 纳西姆·塔勒布 | capital, risk |
| 56 | 非理性繁荣 | 罗伯特·席勒 | capital, bubble |
| 57 | 叙事经济学 | 罗伯特·席勒 | capital, narrative |
| 58 | 滚雪球 | 艾丽斯·施罗德 | capital, buffett |
| 59 | 伟大的博弈 | 约翰·斯蒂尔·戈登 | capital, history |
| 60 | 股市长线法宝 | 杰里米·西格尔 | capital, long-term |
| 61 | 创新者的窘境 | 克莱顿·克里斯坦森 | capital, innovation |
| 62 | 竞争战略 | 迈克尔·波特 | capital, strategy |

**survival（18）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 63 | 原则 | 瑞·达利欧 | survival, principles |
| 64 | 纳瓦尔宝典 | 埃里克·乔根森 | survival, wealth |
| 65 | 刻意练习 | 安德斯·埃里克森 | survival, learning |
| 66 | 深度工作 | 卡尔·纽波特 | survival, attention |
| 67 | 精要主义 | 格雷戈·麦吉沃恩 | survival, focus |
| 68 | 最重要的事只有一件 | 加里·凯勒 | survival, focus |
| 69 | 如何阅读一本书 | 莫提默·艾德勒 | survival, learning |
| 70 | 掌控习惯 | 詹姆斯·克利尔 | survival, habits |
| 71 | 高效能人士的七个习惯 | 史蒂芬·柯维 | survival, habits |
| 72 | 坚毅 | 安杰拉·达克沃思 | survival, character |
| 73 | 心流 | 米哈里·契克森米哈赖 | survival, attention |
| 74 | 终身成长 | 卡罗尔·德韦克 | survival, mindset |
| 75 | 活法 | 稻盛和夫 | survival, work |
| 76 | 干法 | 稻盛和夫 | survival, work |
| 77 | 富兰克林自传 | 本杰明·富兰克林 | survival, character |
| 78 | 乔布斯传 | 沃尔特·艾萨克森 | survival, biography |
| 79 | 埃隆·马斯克传 | 沃尔特·艾萨克森 | survival, biography |
| 80 | 穷爸爸富爸爸 | 罗伯特·清崎 | survival, wealth |

**relationships（14）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 81 | 道德经 | 老子 | relationships, taoism |
| 82 | 论语 | 孔子及弟子 | relationships, confucianism |
| 83 | 庄子 | 庄周 | relationships, taoism |
| 84 | 孙子兵法 | 孙武 | relationships, strategy |
| 85 | 传习录 | 王阳明 | relationships, confucianism |
| 86 | 曾国藩家书 | 曾国藩 | relationships, family |
| 87 | 沉思录 | 马可·奥勒留 | relationships, stoicism |
| 88 | 人生的智慧 | 阿图尔·叔本华 | relationships, wisdom |
| 89 | 人性的弱点 | 戴尔·卡耐基 | relationships, social |
| 90 | 被讨厌的勇气 | 岸见一郎/古贺史健 | relationships, adlerian |
| 91 | 爱的艺术 | 埃里希·弗洛姆 | relationships, love |
| 92 | 亲密关系 | 罗兰·米勒 | relationships, love |
| 93 | 非暴力沟通 | 马歇尔·卢森堡 | relationships, communication |
| 94 | 瓦尔登湖 | 亨利·梭罗 | relationships, simplicity |

**meaning（11）**

| # | 书 | 作者 | tags |
|---|---|---|---|
| 95 | 活出生命的意义 | 维克多·弗兰克尔 | meaning, logotherapy |
| 96 | 西西弗神话 | 阿尔贝·加缪 | meaning, absurdism |
| 97 | 查拉图斯特拉如是说 | 弗里德里希·尼采 | meaning, nihilism |
| 98 | 尼各马可伦理学 | 亚里士多德 | meaning, virtue |
| 99 | 理想国 | 柏拉图 | meaning, philosophy |
| 100 | 月亮与六便士 | 毛姆 | meaning, fiction |
| 101 | 老人与海 | 海明威 | meaning, fiction |
| 102 | 红楼梦 | 曹雪芹 | meaning, fiction, china |
| 103 | 我与地坛 | 史铁生 | meaning, essay, china |
| 104 | 禅与摩托车维修艺术 | 罗伯特·波西格 | meaning, quality |
| 105 | 平凡的世界 | 路遥 | meaning, fiction, china |

书单开放：以后任何对话中出现值得吸收的书/思想，AI 判断后随手蒸馏
入塔——无专属命令，内生代谢。

### 7.5 种子合计

1 axiom + 1 mission + 4 law + 18 master + 25 conversation + 105 book
= **154 块**。

## 8. skill 06 的完全改造（用户 2026-09-18 确立）

`skills/06-investment-philosophy.md` **删除**——哲学体系整体迁出
skills 框架，成为独立模块（git 历史永久保留原文）。

迁移映射：

| 06 号内容 | 去向 |
|---|---|
| Universal law 1：DCF 普适法则 | 塔砖 `dcf-universal-law`（statement 一字不改） |
| Universal law 2：终值交换 | 塔砖 `terminal-value-swap` |
| Universal law 3：北极星使命 | 塔砖 `north-star-mission` |
| Core tenets（六条）| 蒸馏入 AGENTS.md Answer shape 节（部分已在） |
| Folk-master 层（散户乙/鳄鱼） | 大师砖（§7.2）+ 对话砖（§7.3） |
| 54 条 Field Notes | 蒸馏为 25 块对话砖（§7.3），原始出处日期附砖 |
| Phrasing rules（措辞规则，行为性） | 并入 AGENTS.md Answer shape 节 |

配套改动：

- **编号留空缺**：07-12 等既有编号不重排（AGENTS.md 与记忆中大量
  "skills/07-12" 引用保持稳定）；`load_skills` 按 order 排序，空缺
  无害。
- 测试更新：`test_skills.py` / `test_cli.py` 中对技能数量或 06 号
  存在的断言（若有）同步修改。
- AGENTS.md：路由表 philosophy 行改为指向塔（`tower search` /
  `tower show`），"Investment masters" 节不受影响。

## 9. AGENTS.md 家规（写入 Self-refinement protocol 节）

### 双向强制循环（用户 2026-09-18 确立）

1. **查塔义务**：决策级问题（人生/职业/大额消费/关系/投资哲学/重大
   判断）回答前必须 `tower search/list` 相关砖；答案须与 DCF 公理自洽，
   或显式标注 `tension`。
2. **入塔义务**：对话产出智慧级洞见（跨域普适、可复用）→ 必须
   `tower add/note` 入塔，与 Field Notes 自我精进协议同构——同一次
   对话内完成，不欠账。
3. **书籍吸收**：对话中吸收《X》→ AI 蒸馏成砖（`source=book:X`，
   `status=principle`）；被生活验证后升 law。

### 裁决纪律（"不模棱两可"的机制）

4. **结论先行**：一句话裁决，然后才是论证。
5. **裁决必须引砖**：说得出哪条 law/principle 驱动了结论；说不出
   说明塔里还没有——先入塔再裁决。
6. **冲突有仲裁序**：axiom > law > principle > hypothesis >
   observation；DCF 公理是最终仲裁者。
7. **条件裁决 ≠ 模棱两可**：信息不足时禁止"看情况/都行"，必须输出
   "缺 X；若 X 成立则 A，若 Y 成立则 B，触发条件是……"。无结构的
   骑墙才是模棱两可；带触发条件的分支裁决是决断。
8. **具体问题具体分析 = 砖 × 实况**：砖提供一般性，users/me.json、
   memory、trading 记录提供特殊性；只乘一般性是教条，只乘特殊性是
   聊天。

另注明：tower 命令不经过 freshness 门（不依赖行情快照）。

## 10. README 更新

北极星区（"找到你人生的北极星"）新增一段：认知巴别塔 = 思想复利的
直观实现——DCF 单核，154 块种子砖起步（藏书 105 + 大师 18 + 对话
沉淀 25 + 核心 6），git 永续，append-only 生长。不写操作说明（README
讲架构与哲学，不讲人怎么跑脚本）。

## 11. 测试计划（tests/test_tower.py）

对齐 test_skills.py 风格（每文件独立、tmp_path fixture）：

1. **roundtrip**：seed 砖 → parse → render → parse 无损。
2. **add**：正常添加；重复 id 拒绝；`--status axiom` 拒绝（唯一公理）；
   链接目标不存在拒绝并列出可用 id。
3. **note**：追加 Field Note + version bump + 备份产生。
4. **link**：合法类型/目标通过；非法类型拒绝。
5. **set**：升迁强制 --reason 并写入迁移记录；refuted 强制证据；
   tag 增删。
6. **search/list**：子串、--status、--tag、--kind 过滤。
7. **stats**：各状态计数、来源分组、生长统计。
8. **seed 幂等**：连跑两次，第二次零新增、零版本变更。
9. **CLI 冒烟**：`tower list/show/stats --json` 输出可 json.loads。
10. **skills 联动**：`skill list` 不再含 investment-philosophy（数量
    17）；AGENTS.md 相关断言若有则更新。

## 12. 错误处理

- 所有校验失败（格式/重复 id/未知链接目标/非法状态/axiom 唯一性
  违反/refuted 无证据）→ stderr 一行明确信息 + exit 1，与既有 CLI
  风格一致；`--json` 模式下错误仍走 stderr、stdout 保持纯净。
- `load_bricks` 对损坏文件：收集错误字符串不中断（同 load_skills），
  `tower list` 照常列出健康砖并在 stderr 报告坏文件。

## 13. 非目标（明确不做）

- 无楼层、无层级、无承重链、无证伪传播（v2 已砍，用户确认"巴别塔
  只是个名字，核心是 DCF"）。
- 无向量化/嵌入检索——子串匹配够用（pandas + requests 世界观）。
- 无塔内 LLM——蒸馏与裁决由对话中的 AI 完成，塔只负责确定性存取。
- 不进 freshness 门、不进路由表（除 philosophy 行改指塔）、不新增
  skill 文件。
- 不迁移不改线 06 号之外的任何技能。

## 14. 交付物清单

- `value_genie/tower.py`、`value_genie/tower_seed.py`、config 一行
- `tower/` 种子目录（`tower seed` 生成后 git 提交）
- `skills/06-investment-philosophy.md` 删除
- AGENTS.md：路由 philosophy 行 + 自我精进节家规（§9）
- `tests/test_tower.py` + test_skills/test_cli 更新
- README 北极星区一段
- `__main__.py` usage 文档字符串补 tower 命令
