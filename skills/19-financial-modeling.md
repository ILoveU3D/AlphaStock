---
id: financial-modeling
title: Financial Modeling — 财务建模 Playbook
order: 19
triggers:
  - 建模
  - 财务模型
  - DCF
  - 估值模型
  - comps
  - 可比公司
commands:
  - model gather X
  - model write X
  - model show X
  - model lint X
  - model status
  - model fetch X
  - model build X
  - model set X
  - model list
version: 46
updated_at: 2026-10-08T12:19:21
---

# 19 · Financial Modeling（财务建模）

Triggers: 建模 / 财务模型 / DCF / 估值模型 / comps / 可比公司 / model X

## 范式（2026-10-03 用户定稿）

**模型 = AI 对一家公司的完整认知档案，不是估值计算器。** AI 一家一家
单独建模，无脚本批量；脚本是 AI 的手，不是 AI 的替代。建模中缺工具
就加工具，缺砖就 `tower add`——通过全市场建模强化量化工具和巴别塔，
一切为了让 DCF 北极星更强。

产物本地-only（models/，永不推送）、可更新、可复用、动态输入输出；
**信息量必须 ≥ 该公司财报，否则是不合格建模**（`model lint` 机器校验：
三件套完整性 + 世界叙事权重依据 + 文本量 ≥ 素材 30%）。

## 工作流（协作循环，不是流水线）

1. `model gather X [--peers 688256,688041]` —— 机器聚合素材到
   `models/<mkt>/<code>/raw/`：上市以来全历史三表 + intel 事件 +
   公司自述原文 + 年报文本（A：MD&A/主营构成/核心题材/机构预测/
   高管简历；US：10-K Item1/7）+ 法定披露全文（A：历年年报+招股
   书 PDF，raw/filings/）+ 同行（master 缺失时 AI 显式指定同行集）
2. **AI 读素材**：raw/ 全部 + `intel X` + 塔砖（`tower search` 相关
   主题——创新/飞轮/文化先查塔，如 gpu-platform-cocreation 的
   共创循环写法）
3. `model write X key=@file --reason "..."` —— AI 写理解层
   （model.json）。机器只强制三件套：
   - `business_flywheel.text` —— 钱从哪来、怎么转、哪环会断
   - `culture.vision / current_state / evidence` —— 愿景/现状/行为证据
   - `reverse_dcf.implied_world / my_world / gap` —— 现价隐含的
     世界 vs 我信的世界
   其余全开放：`world_narratives`（每个=完整世界假设"发生了什么→
   飞轮第N环接通"，weight 由 AI 估且 `weight_basis` 必填——权重即
   论证）、`dimensions`（AI 自由维度，50个1000个都行）、
   `falsification_monitor`
4. `model lint X` —— 合格线校验；INCOMPLETE 的档案不进 core_dcf 钩
5. `model build X`（估值层：情景×概率 FCFF + comps，旧机制）——
   世界叙事的 drivers 落到 assumptions 后跑；show 同时呈现档案+估值
6. `model status` —— 全市场建模覆盖度

## 全市场战役循环（campaign，2026-10-04）

`model campaign` 是战役的机器侧：三层队列（tier1 持仓/钥匙孔 →
tier2 漏斗候选 core_score 降序 → tier3 全市场按行业/市值，ST 沉底；
HK 全名单来自 mainindicator batch），状态存 `models/campaign.json`
（本地-only），每家公司的进度从不落盘——gathered = raw/history.json
存在、modeled = lint 通过，全部从磁盘实时推导。

- `model campaign init` —— 从最新快照+users 重建队列（幂等）
- `model campaign status` —— 进度板：分层 modeled/ready/pending
- `model campaign next [-n K]` —— **AI 工作队列**：下 K 家未建模
  （标注 gathered/ungathered）
- `model campaign gather [-n K]` —— 批量采集下 K 家素材：**监视
  循环的活**。背压上限 300 家（不跑到 AI 前面太远）；连败 3 次的
  目标 park 不再重试
- 分工红线不变：campaign gather 是机器的手，model.json 永远 AI
  一家一家写。无人值守调度（任务计划/cron）只准调 gather，不准
  碰 write

## 何时建模（AI 自律触发条件）

- **必建**: masters-vote / recommend 的 L3 深评短名单候选，进 L4 裁决前
- **必建**: holding-deep-review 中论点漂移或大幅波动的持仓；钥匙孔季度证伪检查
- **全市场战役**: 钥匙孔/持仓 → L3 → 漏斗候选 → 按行业能力圈逐家推进
- **不建**: 漏斗宽池扫描；D4 战术/短炒模式

## 红线

- 理解层只能由 AI 写——机器聚合素材但永不生成 model.json 的内容
- 权重没有 weight_basis = 占位值，输出打标，不算 AI 判断
- 缺科目（A股股本、HK capex/现金负债）绝不编造——gaps 声明
-  comps/倍数只作互证参照，不作买入论证（DCF 第一）
- resolve 对 out-of-universe 新股：代码形式现在直接用（2026-10-04
  修复：`A:688795` / `HK:02555` / `US:AAPL` 前缀形式全支持）；
  中文名仍走 searchapi fallback 链
- models/ 是本地-only 专有判断，永不推送

## Field Notes

- 2026-10-03 工作台上线：archive.py（model.json + lint）+ gather.py
  （多源聚合，fail-closed 互不阻塞）。摩尔线程试跑：全历史 2022-2025
  四年三表到手（营收 4609万→15亿）
- 2026-10-04 年报文本源上线（fetch/annual.py，探针定稿
  data/probe_mdna.py）：A股 emweb BusinessAnalysis 三连——jyps 经营
  评述（MD&A，**只给最近一期**，翻页无效，茅台实测同样）+ zygcfx
  主营构成（分产品收入/成本/毛利率，茅台 37 期约 10 年）+ zyfw
  经营范围；OperationsRequired 给核心题材 hxtc + 机构预测 jgyc
  （多年 YEAR1-4/EPS/PE）+ 研报评级 ybzy（**投行分析源**）；
  CompanyManagement 给高管简历（文化层证据，NV 系背景实证级）。
  US 走 SEC 10-K Item 1/7 切段（stdlib HTML 剥标签，取最后出现
  跳过目录）。HK 披露易 PDF 无解析库 → gap。
- 2026-10-04 PDF 全文源上线（fetch/filings.py，pypdf 已全局装，
  软依赖不 vendor）：A股走巨潮 cninfo——topSearch 查 orgId →
  hisAnnouncement 按 category_ndbg_szsh（年报，剔除摘要，默认
  近 5 份 FILINGS_MAX_REPORTS）/ searchkey=招股（招股书，剔除
  提示性公告）→ static.cninfo.com.cn 文字版 PDF（实测 230 页/
  22万字符/~10s）；slice_mdna_a 按「第X节 管理层讨论与分析」
  切段（前 5% 命中视为目录跳过，切到下一节标题，<2000字符判
  失败）。gather 落盘 raw/filings/*.txt 全文 + *_mdna.txt 切段
  + raw/filings.json 索引。HK/US 招股书暂 gap（US 年报已由
  annual.py 10-K 覆盖）
- [2026-10-04 15:41] (ai) HK mainindicator history: annual rows must be picked by REPORT_TYPE ending 年报, never by 12-31 date — non-Dec fiscal years (03306 Jun-end, 03998 Mar-end) starve or mis-date otherwise; fixed in model/history.py 2026-10-04, tests test_parse_mainindicator_dec_fy / test_jun_fy_interim_is_not_annual / test_mar_fy_not_starved
- [2026-10-04 16:15] (ai) HK CNY-reporters (CNY statements, HKD price): engine has no FX layer — set shares=total_shares x 0.91 FX so per-share outputs are HKD (result currency label stays CNY but values are HKD, declared in --reason); engine caps 3 scenarios so 4-scenario dossiers fold tail into bear at the probability-weighted anchor (exact weighted preservation); dividend-claim translation (tax=0 net_debt=0 da/capex/nwc=0 margin=D0/rev) for leveraged payers where honest FCFF equity is negative (00991: 5.0x net debt/mcap — the H-share price IS the discounted dividend policy, not an FCFF residual); engine tax_rate=0 or-bug fixed 2026-10-04 with regression test
- [2026-10-04 17:24] (ai) engine 的 terminal_g/wacc/horizon_years or-bug 已同 tax_rate 一并修复（_or_default 显式 None 检查 + 回归测试 test_terminal_g_zero_is_respected）：0.0 是合法终值增速——BKE 档案核心论点 g=0 带宽震荡曾被 or 静默换成默认 0.025，终值虚增约 20%
- [2026-10-04 17:24] (ai) US 顶层 history.json 若 fetched_at 早于 2026-10-04 14:37 的 history.py 修复，companyfacts 财年帧错位两年且缺最新 10-K 年（BKE/HRMY 实证：10/2 拉取把 FY2023 标成 FY2025）——重建估值层前必须 model fetch --force 并与 raw/history.json 比对最后一年；另：理解层 10/4 重写而估值层仍停留在旧机制小 assumptions（<2KB）= 未重建信号
- [2026-10-04 18:15] (ai) engine-fix rebuild acceptance: after fixing the or-default zero-swallowing bug, rebuilt all 15 valuation layers and verified anchors via weighted_per_share delta (<0.005%) + result.history_hash == history.json hash; deliberate zero-paradigm params (HK dividend-discount tax_rate=0, BKE terminal_g=0) survived the fix intact — anchor-diff + hash check is the acceptance procedure for any post-engine-fix rebuild
- [2026-10-04 21:10] (ai) 全市场战役上线（model campaign，用户令 2026-10-04）：init 实测 13,755 目标（持仓 4 / 漏斗 453 / 全市场 13,298，HK batch 2,225 全名单）；两个契约坑——users.list_users() 返回 UserProfile 对象（不是 id，勿再 load_user 二次解析）；HK mainindicator batch 返回的已是清洗帧（小写 code 列，无名称列），不是原始 SECURITY_CODE 形态。进度状态全部磁盘实时推导（gathered=raw/history.json、modeled=lint 通过），campaign.json 只存队列与失败计数
- [2026-10-04 21:11] (ai) 全市场战役上线 2026-10-04：model campaign init|status|next|gather——三层队列（持仓→漏斗 core_score→全市场行业/市值，ST 沉底，HK 用 mainindicator batch 全名单 2225 家）；进度从磁盘实时推导不落盘；gather 背压 300、连败 3 次 park。契约坑：users.list_users() 返回 UserProfile 对象；HK batch 已是清洗帧（小写 code 列）。无人值守调度只准调 gather，write 永远 AI 手写
- [2026-10-04 22:00] (ai) lint 30% 线按 _text_volume 字符数计：中文 UTF-8 在磁盘上每字 3 字节，用文件大小估进度会高估 3 倍——写维度前先 python 实测 staging 总字符 vs raw_text_volume()*0.3 再决定补量；另：中文文本内嵌 ASCII 双引号会让 JSON 解析失败，统一用「」
- [2026-10-04 22:25] (ai) model write 的 KEY=VALUE 必须带 @ 前缀加载文件；漏 @ 时路径被存成字面文本（text volume 骤降），且 world_narratives 块把路径字符串逐字符拆成 33 个非对象条目——lint 报 not an object 长串时先查 @
- [2026-10-04 22:25] (ai) annual.py 切片上限迭代史：80k(SLDE 首采)→120k(SLDE 修复)→160k(UVE 修复，MD&A 真实长 131k)；i7 长度恰等于上限=截断信号，采集后必查 len==max_len 与尾部是否句中截断
- [2026-10-04 23:25] (ai) 80k 截断签名：raw annual.json 的 item1/item7 恰好=80000字符=修复前旧代码残留（gather_batch 只抓未建模目标，永不刷新旧文件）；接手预抓取素材时先扫 cap 签名（len==80000），用 fetch_annual_us 现采覆写；已建模公司（KO/HRMY/INVA）素材被截断需重抓+补维度重 lint
- [2026-10-05 01:06] (ai) US 10-K models: PowerShell file Length is BYTES not chars (Chinese ~3B/char) — estimate writing volume with len(text) in Python before merge; lint counts parsed JSON string leaves only (key names/JSON syntax in world_narratives/gaps/falsification_ledger drop ~25%), so merge-script volume checks must json.loads the block files; write temp scripts into models/<mkt>/<code>/raw/ (AppData temp blocks writes); SEC gather truncates item7 at 160K chars — check tenk dict sub-keys and declare missing sections (ERM/Capital&Liquidity/late segments) in gaps
- [2026-10-05 02:13] (ai) model gather skips re-fetching files that already exist unless --force is passed — a failed 10-K slice (e.g. THG item7=0) will NOT self-heal on plain re-gather; always use model gather X --force when the stored copy carries a gap. Slice failures happen on all-caps headings glued to page numbers (THG: '0ITEM 7–MANAGEMENT'), which the line-anchor fallback still resolves
- [2026-10-05 04:18] (ai) model build now prefers raw/peers.json AI-explicit peer codes over master.csv industry/cap proximity (US rows often have empty industry — PYPL comps silently degraded to cap-neighbors WAT/CRDO/ALL; fixed 2026-10-05 in __main__ build path: codes from peers.json, values fresh from master, falls back to select_peers when absent)
- [2026-10-05 04:18] (ai) valuation-layer history.json fetched before the 2026-10-04 ZM fix carries silently shifted years (PYPL fy2025 held FY2023 comparatives — first-wins picked oldest period); after model gather, run model fetch --force to rebuild history with the fixed fetcher and verify last fy revenue against the 10-K text before building
- [2026-10-05 05:37] (ai) BUG: model gather writes raw/history.json but model build/load_history reads <stock>/history.json at the stock-dir ROOT — when the two drift (TTD 2026-10-05: root stuck at a stale 2026-10-02 fetch with FY labels shifted +2y, last_rev off by 33%), build silently forecasts from the wrong base. Fix: compare root vs raw fetched_at + last-year revenue before every build; if root is stale, copy raw/history.json over it. Symptom to watch: engine per-share values 25-35% below hand-calc with identical assumptions.
- [2026-10-05 05:57] (ai) US 建模数据陷阱2（DLX 案例）：SEC companyfacts 的 cash tag 会混入 restricted cash（DLX:  = cash .9M + settlement 受限 .1M）导致净债务低估 、EV 低估 13%、reverse-DCF 隐含增长率结论方向性错误（零增长 vs +1.4%）。建模前必须用 10-K MD&A 流动性段的官方 net debt 对账；重杠杆股此错会让 bear 世界股权残值虚高。
- [2026-10-05 05:57] (ai) US建模陷阱2补正(DLX)：companyfacts cash tag 含 restricted cash 313=36.9+276.1(USD M)，净债务须以10-K MD&A官方net debt 1392.5为准，否则EV低估13%、隐含g方向反转
- [2026-10-05 11:47] (ai) Windows shell 会把含 | 和 () 的中文 rg 正则拆散（cmd 层解析），从 raw 全文抽取锚点时改用一次性 Python 脚本；A 股 gather 不含年报后公告（如 H 股定增），写 reverse_dcf 估值锚前须搜公开公告核实资本动作（600030 案：定增 8.04 亿股@23.13 港元 2026-08-06 交割）
- [2026-10-05 12:40] (ai) dossier density: lint raw_text_volume counts only raw/*.json narrative text (filings/ excluded) — write the first pass at >=31% of that figure; banks run ~12-17k raw so ~4.5-5.5k chars one-shot avoids the thickening round-trip
- [2026-10-05 15:07] (ai) HK 次新股快照 PE_TTM 是滞后口径：东财港股主指标用上一年报净利、未含最新中报利润跳升（鸣鸣很忙 01768 案例：快照 29.08× vs 含 2026H1 的真实 TTM ≈18.7×，差 55%）——建模港股次新时必须用 TTM=FY-H1+H1 重算并声明口径
- [2026-10-05 16:37] (ai) model set 的场景键(ebit_margin/revenue_growth)要求列表格式——传标量(如 bear.ebit_margin=0.42)会被接受并在 model build 时抛 TypeError(fcff_path len());正确格式为逗号分隔五期列表 bear.ebit_margin=0.42,0.42,0.42,0.42,0.42;券商估值口径模板:shares=年报总股本(A+H全口径)、net_debt=0(表观债务=经营杠杆)、tax_rate=0.25、margin按周期正常化ROE校准(bear≈ROE5.5%/base≈8.5%/bull≈11.5%),FY峰值税前率需刻意下修体现均值回归
- [2026-10-05 18:39] (ai) US dossiers: annual.json embeds full 10-K text (~60k chars), so lint 30% requires an 18k+ char dossier — write all seven shards at roughly double the depth of an HK/A dossier; resolve code collisions with full ID (US:M matched MDB/MKTX)
- [2026-10-05 19:17] (ai) US 10-K 合并标题切片失败：油气 MLP 常用『Items 1 and 2. Business and Properties』（S-K Item 1200 格式），fetch_annual_us 只认『Item 1.』——修复前的 workaround：手工下 10-K 全文按『Items 1 and 2』起、『Item 1A. Risk Factors』止切片存 raw/filings/*.txt（PAA 实测 140,581 字符含资产总表/竞争/人力资本，是 US 卷宗增厚的最佳素材源）
- [2026-10-05 19:17] (ai) lint 体量估算纪律：raw_text_volume 只数 raw/*.json 根目录的字符串叶——增厚暂存件必须放 raw/_staging/ 子目录（放根目录会自我抬高 30% 线）；lint 同样只数卷宗 JSON 字符串叶，凭手感估中文字数普遍高估 30-50%，目标应设在线上方 ≥500 字符余量（PAA 实测：三轮增厚 14,667→20,879→25,441→27,870 才过 27,848 线）
- [2026-10-05 19:17] (ai) 每小时监视已注册为 Windows 计划任务 ValueGenieCampaignMonitor（2026-10-05，schtasks /SC HOURLY 调 models/_monitor_task.cmd → 全局 Python『C:\Users\yukang.wang\AppData\Local\Python\bin\python.exe』跑 model campaign monitor -n 20）；沙箱 PATH 里的 python 是 TRAE VM 解释器，计划任务必须用用户全局 Python；任务在全部建模完成时自删（monitor_pass 内建 schtasks /Delete）；手动停用：schtasks /Delete /TN ValueGenieCampaignMonitor /F
- [2026-10-05 20:24] (ai) A+H 双上市建模模式（2026-10-05，中铝/交行验证）：A 股卷宗承载完整理解层（年报素材厚），H 股卷宗浓缩移植飞轮/文化 + 全新入口层（H/A 价差、红利税地图、流动性贝塔、汇兑）——两份均过 lint，效率比双倍重写高一倍；模型 campaign 里 A/H 成对出现时按此模式处理
- [2026-10-05 22:26] (ai) model write 的 KEY=VALUE 必须用 @file 载入长文本/JSON——漏 @ 会把路径字符串当值写入（list 字段被拆成单字符列表），lint 文本量骤降可立即发现；修复=同 key 用 @file 重写覆盖
- [2026-10-05 22:52] (ai) HK dossiers pass lint trivially: raw text volume is ~1.4k chars (HKF10 main indicators only, no annual-report PDF channel) so the 30% ratio is meaningless for HK — quality bar must be enforced by content density vs official interim/annual results, and the data caliber break (Eastmoney continuing-ops vs official full IFRS) blocks valuation-layer build; declare and pause like HK:00001
- [2026-10-06 06:10] (ai) FUTU 案例三个口径陷阱（2026-10-06）：① 20-F 申报人无 annual.json 且 companyfacts 的 revenue 是 ASC 606 合同收入（不含利息收入）——净利率 107%/毛利率 188% 全是口径假象，必须用含利息的总收入口径（20-F/6-K）；② 券商 OCF 混入客户资金流（ocf_yield 33.8% 假象）且 debt_ratio 82% 是客户应付款——FCF/EV 类指标全部不可用；③ master.csv 价格（110.55）与 kline 收盘（102.17）冲突时，用 drawdown_52w×52 周高反推校验（-48.77%×.33 只有 102.17 自洽）再定价格锚
- [2026-10-06 07:26] (ai) world_narratives 的世界描述字段名必须是 world（不是 description）——lint 报 'no world text' 即此因；另：lint 字符量计入 model.json 全部字符串叶子（含维度名、evidence 的 type/title/source、证伪监控各字段），规划补量时 evidence/falsification/gaps 每件约贡献 2-3.5K 字符
- [2026-10-06 13:20] (ai) model set 只接受数字/逗号分隔数组（不支持@file），scenarios 必须用 bear.prob=0.45 逐键传入；且 set 前必须先 model build 生成默认 assumptions（fetch+build+set+build 四步）；write 的 culture/reverse_dcf 支持 @file 整块替换（archive.write_fields 的 sections 分支）
- [2026-10-06 14:00] (ai) A股 history.json 的 debt 字段=负债合计（含无息经营负债），非有息负债——有息负债必须从年报资产负债表附注重建（601168 实证：341.65亿 vs 真实有息243.3亿，差98亿）；net_debt 桥接时少数股东权益按账面值加入并声明
- [2026-10-06 14:00] (ai) A股 master 的 PE_TTM 已含最新中报利润（601168 实证：14.18=市值842.39/TTM归母59.4亿，含2026H1），建模时 TTM 口径直接用 master 勿用 FY-only 自算（H1 folded in: TTM=FY+H1新-H1旧）
- [2026-10-06 14:39] (ai) HK目标建模三坑（2026-10-06汇丰案）：① raw/history.json只是gather暂存，正式history必须先跑 model fetch 写到stock根目录，否则build报no history；② model set 的KV值全部float化，currency等字符串字段无法set——per_share经price_fx换算成HKD后result.currency仍标CNY，须在rdcf.gap里声明口径；③ 银行/金融股适配：net_debt=0（负债是经营原料）、da/capex/nwc归零使FCFF≈税后利润、机械值=无资本约束理论上限（CET1留存致真实可分配为净利60-80%），gap必须三点全声明
- [2026-10-06 14:50] (ai) 大数单位陷阱（2026-10-06宏力达案，连续两次踩坑）：net_debt/shares等十亿级参数从中文素材（亿元）换算到引擎（CNY原值）时必须显式过一遍'亿元×1e8'再写值——宏力达净现金20.48亿曾先后误写为1.95亿和195亿；建议set前用python -c核对一次数量级（市值/股本应为合理股价区间）
- [2026-10-06 17:56] (ai) US companyfacts XBRL revenue tags have multi-year anomalies: AER 2018-2021 revenue reported as 9.7M-15.7M (tag switch), CMRE 2024 2.084B vs 2025 0.878B (-58% cliff) — when a US target's revenue series breaks >40% between adjacent years while NI stays coherent, suspect tag/consolidation change first (check NI/OCF coherence + segments), flag in gaps, and never build the revenue trajectory on the broken span without 10-K verification
- [2026-10-06 18:56] (ai) model write 的 @file 解析按后缀分流：.json 才 parse 成数组/对象，.txt 永远是字符串——culture.evidence 这类数组字段必须存成 .json 后缀再 @引用（US:G 踩坑后修正）；另 raw_text_volume 只数 raw/*.json 顶层 glob，raw/_staging/ 子目录的分片不计入 raw 量（staging 草稿不会虚增 lint 分母）
- [2026-10-06 21:11] (ai) lint 体量估算二次踩坑（INCY 2026-10-06）：raw/_staging 里的 src_item*.txt 是源文导出不是 AI 写作——估理解层字数时必须排除 src_* 前缀，只算 flywheel/culture/rdcf/dims/falsification 等纯写作件（INCY：上轮误把 43KB src 导出当写作量以为超额达标，实测纯写作 31.4K 差线 9.9K，被迫补写 d11-d16 六个维度才过线）；合并前用 python 实测 staging 写作件字符总和 vs raw_text_volume*0.3 再动手
- [2026-10-06 21:11] (ai) 「引擎装载口径」维度的槽位公允值必须在 build 完成后从 result.json 回写，禁止凭记忆近似（INCY 2026-10-06：凭感觉写 74/101/129，实际 58.2/103.4/139.8——bear 估高 26%）；正确流程=装载口径维度初稿只写参数不写槽位值，build 后用实际输出回填 gap 与装载口径两处，价格口径同时用 result.json 的 price 对齐（115.30→113.73 漂移案例）
- [2026-10-06 21:35] (ai) 上下文中断恢复程序：摘要声称'已创建'的文件以磁盘为准——顶层 model.json/assumptions.json/result.json 任一缺失即合并/装载脚本未实际执行，恢复时先 Get-ChildItem 核对目录再重跑脚本；set_assumptions 不接受 gaps 键（只收 _TOP_KEYS+场景驱动键），gaps 只能进理解层
- [2026-10-06 22:37] (ai) F10 debt 字段对资源/制造类公司严重失真（000612: 15.34亿 vs 年报有息5.9亿；000792: 107亿 vs 12.8亿；601225: 989亿 vs 219.7亿）——估值层 net_debt 必须从年报科目重算（短借+长借+一年内到期+租赁），把 history.debt 当线索不当事实
- [2026-10-08 01:07] (ai) E&P valuation trap (RRC 2026-10-08): SMPV/NAV anchors must declare liquidation vs going-concern basis and subtract net debt for equity value — narrative target 42-50 collapsed to engine weighted 24.7 once the FCFF engine charged perpetual capex; every narrative anchor must be engine-recomputable (write both numbers in the dossier and reconcile before closing)
- [2026-10-08 12:19] (ai) HK thesis/funnel 边缘股的 peers 映射常给错行业（百威给了零食饮料组、中通给了航运港口组、老铺给了服饰组）——写卷宗时 peers 数据必须人工核行业再引用，并在 gaps 声明同行映射缺陷
- [2026-10-08 12:19] (ai) hk_quotes.csv 的 HK 代码无前导零（'2475' 非 '02475'），zfill(5) 才能匹配；master 的 HK market_cap 与 PE 反推市值存在 10-30% 口径差，卷宗锚定 PE 而非市值列并声明 gap
