# 公司档案库（company profiles）实施计划

## Context

三核架构（commit 4c796ff）已把商业模式/企业文化/DCF 立为唯一排序键，但 business/culture
两核目前的输入只有**量化代理**（roe/gm/借钱分红/回购等）。用户 mandate（2026-09-29）：
把 A/HK/US 公司的商业模式、企业文化、未来愿景等**原文信息**全部抓到本地保存，支持
增量更新——这是选股的核心参考素材，cores.py 的分析逻辑消费它。

已拍板的四项决策（用户授权默认值）：
1. **候选池优先，增量扩张**：首批 = funnel 候选（~200/市场）+ watchlist + 持仓，每次
   fetch 自动补新入池公司，档案库随时间长大
2. **git-tracked `profiles/`**：与 tower/theses/users 同级的知识资产目录，不进 data/
   （重建昂贵，符合"永续资本结构"哲学）
3. **简介级文本**：A=东财 F10 公司概况/主营业务；HK=东财 HK F10 概况；US=SEC
   submissions 元数据 + stockanalysis.com 简介。年报 MD&A / 10-K Item1 留 Phase 2
4. **AI 蒸馏回写**：工具箱只存原文（无 LLM）；AI 在 L3 深评时 `profile show` 读原文，
   把结构化评估经 `profile assess` 回写档案 assessment 区，cores.py 融合蒸馏分

## 关键设计

- **文件格式 JSON**（不选 YAML frontmatter）：双区嵌套结构（raw + assessment + meta），
  skills.py 的迷你解析器不支持嵌套；AI 不手编文件，走 `--json` 读、`assess` 命令写；
  thesis.py/users.py 先例（原子写 + schema-drift tolerant 加载 + tmp_path 测试 fixture）
- **目录**：`profiles/<market>/<code>.json`（a/hk/us 子目录，code 用 master.csv 形式，
  复用 `users.normalize_code` 归一）
- **raw / assessment 两区严格分离**：抓取器只写 raw；assessment 只由 `profile assess`
  写。`assessment.raw_fetched_at` 记录蒸馏基于的 raw 版本——raw 重抓后不一致 = 蒸馏
  过期（stale），cores 融合剔除、L3 提示重评
- **变化检测**：`content_hash`（summary+main_business+vision 的 sha1 前12位）；hash
  不变只 bump `fetched_at`，hash 变才更新内容并使旧 assessment stale

### 档案 JSON 结构

```json
{
  "id": "A:600900", "market": "A", "code": "600900", "name": "...",
  "version": 3, "created_at": "...", "updated_at": "...",
  "raw": {"fetched_at": "...", "source": "...", "source_url": "...",
          "summary": "公司简介原文", "main_business": "主营业务原文",
          "vision": "", "meta": {"chairman": "...", "...": "..."},
          "content_hash": "sha1前12位"},
  "assessment": {"assessed_at": null, "raw_fetched_at": null, "agent": null,
    "business": {"score": null, "moat_type": "", "machine_lifecycle": "", "argument": ""},
    "culture":  {"score": null, "founder_led": null, "benfen_evidence": [], "argument": ""},
    "dcf": {"argument": ""}, "verdict": ""}
}
```

## 实施步骤

### 0. 网络探针（先行，结果落成 config 常量 + 探针日期注释）
- A 股：探两个候选——datacenter `RPT_F10_ORG_BASICINFO`（filter 字符串双引号铁律）与
  `emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code=SH600900`，
  确认哪个带"公司简介/主营业务/经营范围"字段
- HK：`RPT_HKF10_INFO_ORGPROFILE`（`fetch_hk_lot` 已验证可用，columns:"ALL"）探是否含
  简介/主营业务文本列；无则退 HK F10 PageAjax 镜像
- US：SEC submissions API（`SEC_SUBMISSIONS_URL_TMPL`，intel/announcements.py 已在用）
  提供 meta；简介正文探 `https://stockanalysis.com/stocks/{slug}/` 的 description 字段

### 1. config.py 常量
`PROFILES_DIR` / `PROFILE_FRESH_DAYS=90` / `PROFILE_BLEND=0.5` / 三市场 URL 常量
（探针定稿）+ `profiles/.gitkeep`

### 2. 新建 `value_genie/profile.py`（模型 + CRUD + 新鲜度）
对照 thesis.py 结构：`Profile/ProfileRaw/ProfileAssessment` dataclass；
`load_profile`（schema-drift tolerant）/ `save_profile`（atomic.atomic_write_text）/
`list_profiles` / `find_profile`（走 resolve 链）/ `raw_is_fresh` /
`assessment_is_stale` / `set_raw`（hash 判变）/ `set_assessment`（score 0-100 校验，
raw 空拒绝）/ `pool_members(snap_dir)`（master+watchlist dedup）/
`load_assessment_frame()`（唯一对接面：只收 assessed 且非 stale →
DataFrame[market, code, a_business, a_culture]）

### 3. 新建 `value_genie/fetch/profiles.py`（三抓取器 + 增量编排）
- 网络函数全部模块级（monkeypatch 边界）；复用 http.py 的 DC/SEC/SA/EM_WEB Fetcher
  （重试4次+冷却）；源失败返 None（fail-closed，不写空档案）；调用间 sleep 0.4s
- `fetch_profile_a/hk/us(code) -> dict|None`；`FETCHERS` 注册表
- `update_profiles(symbols, force=False) -> {"fetched","skipped_fresh","changed","failed"}`：
  fresh 跳过、None 记 failed（旧文件不动）、set_raw + save_profile
- 把 intel/ratings.py 的 `_sa_flight_array`/`_sa_json` 提升为共享解析器，ratings.py 改
  import（不复制粘贴）

### 4. 新建 `tests/test_profile.py`
pdir fixture（复制 test_thesis.py 的 tdir 模式：tmp_path + monkeypatch PROFILES_DIR）。
用例：CRUD roundtrip / schema-drift / 坏文件 ValueError / code 归一（hk 998→00998）/
raw_is_fresh 边界 / hash 不变只 bump / hash 变 → stale / assess 校验（越界、raw 空）/
load_assessment_frame 剔 stale / 三抓取器罐装 payload / 源 None 记 failed 不动旧文件 /
pool_members dedup

### 5. cores.py 融合（纯函数，零 IO）
`add_core_scores(df, assessments=None)`：有蒸馏分 →
`core = PROFILE_BLEND*quant + (1-PROFILE_BLEND)*a_score`（quant NaN 时蒸馏独任）；
无蒸馏分 → 现状量化代理原样保留（这是设计意图：首年多数公司只有代理）；
`core_gaps` 仅在 assessment stale 时追加声明；不加新列（675 测试列断言不破）。
test_cores.py 扩展：blend 数学 / quant NaN 蒸馏独任 / 不传 assessments 逐列回归锁

### 6. pipeline.py 集成
- `run_fetch` 尾部（radar 合并与 watchlist 二次写盘后、manifest 写盘前）：
  `update_profiles(pool_members(snap_dir))`，try/except 记 manifest failures 不阻断快照；
  `manifest["datasets"]["profiles"]` 计数
- `build_master` 加默认参数 `assessments=None`，两处 `cores.add_core_scores` 传入；
  run_fetch 开头 `profile.load_assessment_frame()` 加载一次
- 限速预算：PROFILE_FRESH_DAYS=90 下日常增量 ~10-40 只/fetch ≈ 4-16 秒；首跑 ~5 分钟
  走 `profile update --force`
- test_pipeline.py 扩展：manifest 计数、抓取器异常记 failures 不阻断

### 7. CLI（__main__.py，profile 子树，不过 freshness gate——同 tower/thesis 先例）
`list [--market] [--stale] [--json]` / `show <stock> [--json]`（L3 读取入口，走 resolve
链）/ `fetch <stock>`（强制重抓，探针+修复用）/ `update [--market] [--force] [--limit N]`
/ `assess <stock> --business-score N --culture-score N [--moat-type] [--lifecycle]
[--founder-led] [--benfen ...] [--business-arg ...] [--culture-arg ...] [--dcf-arg ...]
[--verdict ...]`（AI 回写唯一入口）/ `status [--json]`（覆盖率：池 vs 建档/过期/已蒸馏/
stale）。test_cli.py 扩展：--json 纯 JSON、assess 校验失败 exit≠0、list --stale 过滤

### 8. 文档（单独提交）
AGENTS.md：routing table 加"X的商业模式/企业文化/档案原文" → `profile show X`；L3 深评
工作流（show 读原文 → 三核论证 → assess 回写）；profile 命令不过 freshness gate 说明。
skills/18 Field Note 记一行。README 架构节加一行。

### Phase 2（本次不做）
年报 MD&A / 10-K Item1 深文本区；池外发现（show --discover 式）；vision 字段的专门源

## 验证

1. `python -B -m pytest tests -q` 675+ 全绿（含新增 ~25 用例）
2. 探针命令实跑三市场各一只（600900 / 00998 / MU），确认字段落档
3. `python -m value_genie profile update --limit 5` 端到端：档案落盘 → `profile show` 读
   原文 → `profile assess` 回写 → `profile status` 覆盖率正确
4. 合成快照跑 fetch 管道（monkeypatch 抓取器），manifest datasets.profiles 计数正确
5. assess 后重跑 fetch，`core_business/core_culture` 反映 blend 分；raw 更新后
   assessment stale → core 回落量化代理 + core_gaps 声明

## 关键文件

新建：`value_genie/profile.py`、`value_genie/fetch/profiles.py`、`tests/test_profile.py`、
`profiles/.gitkeep`
修改：`value_genie/config.py`、`value_genie/strategy/cores.py`、
`value_genie/fetch/pipeline.py`、`value_genie/__main__.py`、`value_genie/intel/ratings.py`
（解析器提升共享）、`tests/test_cores.py`、`tests/test_pipeline.py`、`tests/test_cli.py`、
`AGENTS.md`、`README.md`（一行）
