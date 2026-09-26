---
id: fused-quant-master
title: Quant-Master Fusion Recommendation (量化×大师融合推荐)
order: 18
triggers:
  - 推荐
  - 最推荐
  - 最被低估
  - 低估的标的
  - 有什么机会
  - 量化加大师
  - 融合推荐
  - 值得买
commands:
  - masters-vote [--top N] [--json]
  - ask X --evidence
  - intel X
  - recommend --user me
version: 14
updated_at: 2026-09-26T00:18:40
---

# Playbook

Answer every recommendation request through the fused QMF pipeline —
ONE quant+master-optimal pick, never a split "quant says X, masters say
Y" answer. User mandate 2026-09-15: 融合，不分情况讨论。The GSL case
(2026-09-15) is the origin: quant screens ranked GSL #1 (graham +
sanhuyi), the 7-master layer vetoed 6:1 (cycle trap + CEO/CFO
synchronized selling + forward PE 8.41 vs TTM 4.30). The fusion must
catch that BEFORE recommending, not after.

## The four layers (L1/L2 code-enforced, L3/L4 AI-run)

### L1 — 量化共识层（代码，`masters-vote`）

`python -m value_genie masters-vote --top 15 [--json]`

- Each stock is voted against all 7 masters' hard gates:
  `vote_count` (0-7) + `masters_passed` + `mean_composite` (mean of
  composites under each master's own weights).
- Ranking: vote_count desc → mean_composite desc. A 2-vote Graham #1
  (GSL) correctly ranks below 4-vote consensus names.
- **Never recommend from a single strategy's top rank** — the pool
  starts at the cross-master consensus.

### L2 — 否决层（代码 flags + 规则）

`masters-vote` prints the veto flags; treat them as hard inputs:

- `CYCLE_TRAP`: pe_divergence (eps_ttm / consensus EPS) ≥ 1.5 — the
  market prices earnings falling ≥ 1/3. The GSL signature. Veto unless
  the qualitative layer can prove the consensus wrong.
- `cycle_warn`: divergence ≥ 1.25 — earnings-decline risk, requires
  explicit justification to pass.
- `profit_spike`: profit_yoy ≥ +200% — low-base/one-off rebound;
  growth pillar is unreliable, check the base year before believing
  the number.
- `gap:` lines: no consensus-EPS source (HK/US) or no coverage —
  declare the gap in the answer, never improvise the number.
- Then run `intel X` on finalists: 内部人卖出、解禁/减持计划、粉饰
  信号、借钱分红 are vetoes per the 舆情铁律 (2026-09-09). Insider
  synchronized selling + high profit growth = classic sell signal.

### L3 — 大师定性层（AI，per the deepened playbooks 07-12, 17）

For each L2 survivor, run the 7-master qualitative vote — business
model, culture, moat, earn/lose paths (data via `ask X --evidence` +
`intel X`). Each master votes from their own playbook lens:

- Buffett: 三时代定位 + owner earnings + right people
- Munger: 双轨分析 + 三筐 (In/Out/Too Hard) + Lollapalooza
- Graham: 方法边界自检（周期股低 PE 是反向指标）+ 市场先生位置
- Livermore: 关键点 + 最小阻力方向 + 仓位纪律
- Duan: 四连问（生意/文化/价格）+ right people + -50% 测试
- Sheng: 注意力周期 + climax 退出（仅短线视角，仓位 ≤5%）
- 散户乙: 股权思维 + 分红回本算术 + 借钱分红 veto

数据只能成为不买的理由（用户原话 2026-09-06）—— qualitative
vetoes are absolute; qualitative approvals are necessary but never
sufficient alone.

### L4 — 融合裁决（AI 决策权）

Fuse: L1 vote count + L2 survivors + L3 master table + user style
(`recommend --user me` for style gates + holdings exclusion) + market
conditions. NOT a mechanical gate intersection (user principle):
统筹兼顾，最终判断由 AI 掌控并给出明确结论。

Output shape (hard rules):

1. **One verdict, one pick** — the quant+master optimal. Runners-up
   listed with one-line reasons, no case-by-case branching.
2. Master vote table (7 rows: vote + one-line reason).
3. Position discipline per Duan: -50% drawdown tolerance sizing;
   keyhole compatibility check (分红收回路径 for 分红舱 candidates).
4. Data-as-of line + declared gaps verbatim.
5. 短炒警示 if the horizon is ultrashort/short.

## Worked example (2026-09-15, the calibration case)

- L1: 海德股份 4 votes (buffett,munger,graham,duan) but L2 flags
  `profit_spike` (+815.8% profit_yoy, 低基数) → veto.
- L1: GSL 2 votes only — consensus already demoted the graham #1.
  L2 (manual check then; now automated): pe_div ≈ 1.96 → CYCLE_TRAP.
  L3: CEO+CFO 8月26-27日同步卖出 → Duan right-people veto.
- 荣昌生物: L2 caught `pe_div=51.58` → CYCLE_TRAP + profit_spike —
  exactly the signature the code now catches automatically.
- Final pick that day (via manual fusion): 周生生 00116 — 5:1 master
  vote, PE×PB 1.53, 股息率 7.02%, 0 risk flags, gaps declared (HK
  无研报源 / 20% 红利税 / ROE 14% 边界).

## Hard limits

- L2 flags are vetoes unless the AI can *prove* them wrong with
  sourced evidence (先搜公开渠道再定性, 2026-09-14).
- 倍数口径规则 (2026-09-15): every multiple marked TTM/LF/forward,
  computed from the toolkit, never from memory.
- If L1 pool is empty or all finalists are flagged, say so — an
  honest "no qualifying pick today" beats a forced recommendation.

## Field Notes
- [2026-09-15 17:11] (ai) masters-vote L2 live pass only covers A-share (Eastmoney consensus EPS); HK/US rows show gap:no consensus-EPS source instead of a divergence value - state the gap, do not improvise. Calibration 2026-09-15: 海德股份 ranked L1 #1 (4 fundamental-master votes) but carried profit_spike + missing consensus EPS - same shape as the GSL trap; L3/L4 must veto flagged L1 leaders before recommending. HK/US profit_spike rows (Dorian LPG, Gulfport, NUTX, Aurinia) are LLM-cycle/shipping-cycle peaks - treat profit_spike as a hard veto, not a caveat.
- [2026-09-15 20:55] (ai) TCOM 校准（2026-09-15）：L1 四基本面大师全票+表观 PE 5.47 第一，仍被 L2 叙事核查推翻——2025 净利 332.94亿CNY 含 199亿投资利得（占60%），OCF/净利 0.43，真实经营 PE ~13-14x；反垄断罚没 51.79亿+整改拆除'特牌独家+全网最低价'take rate 壁垒，Q2 收入指引放缓至 3-8%。教训：US/HK 无 A 股扣非/粉饰信号时，L2 必须用 web 叙事核查 + OCF/净利<0.6 双指标替代利润质量闸门；表观 PE 第一 ≠ 最被低估。GSL 案之后第二例融合否决。
- [2026-09-16 11:06] (ai) 板手数前置检查（2026-09-16 AH案例）：L4 裁决输出前必须先查 HK 标的 board lot（trade buy 会被引擎拒绝并返回手数），计算最小手数仓位%——江南布衣最优（四票+ROE38.3+派息率110%）但500股/手=18.8%NAV突破单名15%上限，纪律否决执行后改次优波司登（2000股/手=14.9%恰在限内）。教训：基本面最优 ≠ 可执行最优；手数不可分割时'首笔5%分批建仓'失效，须在裁决层就选择手数合规的次优标的，而非成交后才发现超限。A 股 100 股/US 1 股无此问题。
- [2026-09-16 23:43] (ai) 错杀闸门规格修正(2026-09-16 CATL案例, 用户指正): 错杀判定中的'基本面没坏'曾被错误操作化为'无负面数据点'——这会把周期股的毛利率-1pp/存货上升/税费传导等周期噪音当作结构恶化, 结构性错过所有周期性深值机会。正确规格: 基本面没坏 = 生意级证伪集未触发(份额/护城河/文化/模式), 错杀 = 价格跌幅远大于生意受损幅度。平台型生意的'客户去X化'叙事(二供分流/自研替代)≠生意死亡, 类比: 去英伟达化多年但利润池份额未失——判据是技术代际节奏是否领先, 非客户是否尝试多元化。周期噪音 vs 结构恶化的分层必须在 L4 裁决中显式声明。
- [2026-09-22 14:44] (ai) 股东回报硬闸门(20260922 用户强调段永平'股票的最终买家只能是公司自己', tower brick ultimate-buyer): L2 否决层新增三问检验——①现金真实性: 回购/分红的钱是经营现金流还是投资利得/借款? (TCOM 4票但 OCF/净利0.43=投资利得型, 否决; 大师gates的'借钱分红否决'同源) ②回报持续性: 多年记录还是一次性作秀? (ACAD 十年亏损期回购=伪回报, 否决; ZM 三年10亿+/年=真记录) ③时机纪律: 便宜时执行还是追高护盘? (波司登首笔回购在-25%回撤处=合格; DUOL 2026-02首个-23%崩盘当日=管理层接盘信号; 德翔/LPG式周期顶盈利回购=GSL校准的变体, 否决). 裁决时该闸门与profit_spike/解禁红旗同列L2, 但对'最被低估'类问题权重前置: 无股东回报能力=价值兑现依赖下一个买家=与DCF公理冲突. 注意区分两种合格类型: ZM=回购注销型(成长舱原型), 波司登=分红复利型(分红舱原型, free-shares砖), 类型不分高下, 检验标准同三问
- [2026-09-22 14:54] (ai) 时机分层判据(20260922 用户质询'为什么全是急跌票'): L4 融合层升级为两层结构——①错杀池(急跌+基本面没坏=低估来源, 维持) ②企稳扳机(时机入场层: r5>0 且 r20 翻正 / 站上20日线 / 前低不破后放量, 任一触发)。分舱适用: 论点买入(钥匙孔/分红舱, 段永平不择时)免扳机; 时机买入(错杀gate/短线/季赛加仓)必须过扳机。教训案例: 0922 波司登第二手以'急跌错杀'作入场理由但 r5=-9.5% 仍在下跌=左側接刀, 属逻辑混用(论点逻辑不该用急跌作理由, 时机逻辑就该等企稳), 按扳机层应继续观察。实算校准: 该形态(dd52<=-15%急跌过 + r5>0,r20>0企稳上涨 + 质量floor + 股东回报gate)今日全市场仅 HK 1只(康臣药业,graham 1票)/US 0只/A 3只(2只被叙事gate)——'急跌后企稳上涨+低估'是转瞬即逝的窄窗口, 为确认多付5-10%入场溢价=利弗莫尔关键点权利金, 是成本不是缺陷
- [2026-09-23 14:32] (ai) 0923校准双录: ①周期顶否决的市场确认——LPG(4票)周二收盘-5.47%、德翔海运(L1榜首)次日-2.25%, 均在否决后第一二个交易日内开始兑现, 印证scarcity-multiple-rule(周期稀缺模板不给倍数): 周期顶低PE票的'便宜'会在脉冲退潮时消失, 否决链不是保守是提前离场; ②入口互补声明——用户风格gate(ret_20d<=-3%错杀池)与企稳扳机层是两套入口不互斥: 康臣r20+6.57%不进错杀池但扳机全亮(r5+7.69%+今日+0.70%三日确认), 推荐管道按'扳机层入口'输出并标注'非错杀池来源', 不得因gate不匹配而丢弃扳机票(用户0922质询的正是这个盲区)
- [2026-09-25 13:10] (ai) 2026-09-25 海德股份案例: L1 双榜第一(4票: buffett/munger/graham/duan, PE 7.3/ROE 21.4/PB 1.7)被 L2 硬否决 — OCF/净利 -0.01(13.5亿利润零现金含量) + profit_spike +816% + 零研报覆盖(无一致预期)。重演 GSL 校准: 低PE高ROE的金融控股量化幻觉, owner-earnings 视角一票否决。AMC/不良资产处置利润=公允价值变动, 非现金。
- [2026-09-25 23:47] (ai) 20260925 用户校准(L3压缩): 宣称'买入理由从商业模式与文化出发'但实践L3被压成3-5行原型模板匹配,文化层仅存L2行为代理(回购/分红/内部人交易)穿错闸门的衣服。根因: ①肯定论证未代码化(否决层全是机器规则,买理由靠临场发挥) ②错杀池入口=价格事件,管道天然数据密集,与段永平原则结构性张力 ③每日横扫20分钟/票接触不到创始人史与组织行为。修正: L4输出'这门生意'段前置(模式一句话/文化行为证据/赚亏路径,先于估值数字);文化证据只收行为级不收形容词;推荐标注候选级(通过排除)vs论证级(理解生意),候选级不得穿论证级的衣服。案例: 吉比特三行/波司登两行 vs 摩尔线程级分析(张建中NV文化DNA)的差距=两级决策重量,但未标注即失真。
- [2026-09-25 23:59] (ai) 20260925 用户校准(L3规格重写,升v10修正): ①L3论证义务升级——护城河须论证到说服用户(三层定位+变宽变窄证据+谁能攻破),创始人履历+本分审计(说过vs做到/资本配置/拒绝过什么/压力期选择)必须token深研,创新姿态二选一明确(创新者窘境:开创S曲线的破局者(NVIDIA范本:R&D投向下一范式+自我蚕食意愿) vs 稳健现金牛(海力士/美光模板:巨额FCF+便宜)); ②赚钱/死路径降级为结果层仅作验证; ③新堵漏:周期位置前置判断(结构稀缺vs周期稀缺,profit_spike区分周期顶与周期底回升)——存储2025 miss根因=trailing gates顺周期性; ④执行授权:代码无法实现的模块消耗算力深研,不再降级; ⑤候选级/论证级标注取消——未论证到说服力级别的只进观察名单不作为推荐。相关塔砖: trailing-gates-are-procyclical / causes-not-outcomes。
- [2026-09-26 00:03] (ai) 20260926 用户授权+校准: ①六原型批判性使用权正式授予AI(用户自认消费/泡泡玛特领域不擅长,只敢买港股通红利)——原型降级为提问模板(每原型生成自己的死法审计问题表,见塔砖four-layer-business-pricing),禁止作结论标签; ②六原型稳定偏性被确认为存储miss的框架级根因(本体论缺失非数据缺失); ③泡泡玛特处理规格: 论证不到确信级+用户产业判断缺席的标的=不可推荐,大师持仓不转移论证责任(authority-is-evidence-of-model),分歧入档留证伪集; ④用户重申创新者窘境+存储反思为不可妥协优先级=L3的S曲线层与周期位置层,已在four-layer-business-pricing中固化为第3/4层。
- [2026-09-26 00:07] (ai) 20260926 用户校准(时间护照): 每笔L4推荐强制携带时间护照四字段——①维度声明(ultrashort/short/mid/long+舱位类型: 钥匙孔3-10年/分红舱永不卖/成长舱论点破坏/赛季仓位赛季周期) ②论点-时间匹配(同一股票四维度=四门生意,声明买哪个论点) ③退出触发(维度专属,论点级vs价格级分列) ④维度漂移规则(什么信号允许换维度,如mid买入后long论点亮→转舱)。根因: 不声明维度的仓位会漂移,中线套牢默默改长线=经典自欺,推荐有义务消除此漂移条件。衍生品禁令重申: 期货/杠杆=无DCF+摧毁仓位纪律+零信息优势,永远不碰(油轮期货玩笑的认真回答)。超短线能力赤字承认: gates在册但赛季零实弹,训练计划=下窗口5%NAV动量延续仓(pivotal扳机入场/-7%硬止损/短炒警示全开)。
- [2026-09-26 00:18] (ai) 20260926 用户口径重定义(代码已改): 四维度=超短<1天/短1天-1月/中1月-1年/长1年+(horizons.py注册表已固化,626测试全绿)。授权: 赛季中积极尝试各维度锻炼——超短线训练仓规格: <=5% NAV,pivotal扳机入场,-7%硬止损,持有<=1天(新口径ultrashort定义),短炒警示全开;短线1天-1月窗口的扳机票(如TCOM二手)即为此维度的实弹;维度尝试须在journal留完整决策链,赛季复盘按维度分列战绩。
