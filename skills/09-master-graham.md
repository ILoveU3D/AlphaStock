---
id: master-graham
title: Master - Benjamin Graham (Statistical Deep Value + Mr. Market)
order: 9
triggers:
  - 格雷厄姆会怎么看
  - graham
  - 市场先生
  - 烟蒂股
  - 净流动资产
  - 格雷厄姆视角
commands:
  - screen --strategy graham
  - ask --evidence
version: 2
updated_at: 2026-09-15T10:00:00
---

# Playbook

Answer "格雷厄姆会怎么看X" with the Graham lens: margin of safety as
*arithmetic*, Mr. Market as a servant, and the humility to know that
deep analysis of everything is impossible — and that for most people
the elaborate apparatus should reduce to an index fund.

## 1. 思想渊源与进化轨迹

- 1894 生于英国伦敦，1 岁移民美国。1914 Columbia 毕业进 Wall
  Street（Newburger, Henderson & Loeb）当信息员，靠统计套利起家。
- 1929 大崩盘中 Graham-Newman 基金净值跌去约 70%——浮存金 + 杠杆
  双杀，这是他终生的伤痕教材。
- 1934 与 David Dodd 合著 *Security Analysis*，理性投资的圣经；
  1949 出版 *The Intelligent Investor*（普及版，Buffett 称"史上
  最好的投资书"）。
- 1956 退休，Graham-Newman 基金清盘。1976 接受访谈，明确说普通
  人应该买指数基金，"elaborate apparatus" 是为专业人士；同年
  9 月离世。
- 进化弧线：青年统计套利 → 中年烟蒂/Net-Net → 晚年指数基金。
  这条弧线本身就是 Graham 最诚实的一课——方法随市场效率提升而
  收敛，但安全边际原理不变。

## 2. 核心方法论完整框架

### 投资 vs 投机的定义（第1章，一切前提）

> "An investment operation is one which upon thorough analysis
> promises safety of principal and an adequate return. Operations not
> meeting these requirements are speculative."

三要件：thorough analysis（深度分析）、safety of principal（本金
安全）、adequate return（适当回报）。缺一即投机——而投机本身不
丢人，丢人的是把投机当成投资。

### 三种估值方法（按保守度递减）

1. **净流动资产法（Net-Net）**：NCAV = 流动资产 - 全部负债，买入价
   低于 2/3 NCAV。1930s 标志，硬资产保护到牙齿。
2. **盈利能力法（Earnings Power）**：企业正常化盈利 ÷ 折现率。
3. **成长性法**：盈利增长 × 合理乘数——最危险，谨慎使用。

Graham 明确说：第一法最保守，第二法次之，第三法最危险。AI 在
cite 估值时必须标注用的是哪一法。

### 防御型 vs 进取型（第4章）

- **防御型**：被动、分散、低估值、不分析个股；债券+股票 50/50；
  历史年化约 6-8%。这是大多数人的归宿。
- **进取型**：主动、集中、深度分析、套利、特殊机会；需要时间、
  知识、性情。Graham 反复说：进取型不是"更激进"，是"更勤奋"。

### 防御型七准则（1949 原版，graham 策略硬门的祖先）

1. 适当企业规模（避免小盘）
2. 流动比率 ≥ 2
3. 过去 10 年稳定盈利
4. 连续分红 20 年
5. 10 年年均 EPS 增长 ≥ 1/3
6. PE ≤ 15
7. **PE × PB ≤ 22.5**（核心硬准则，15×1.5，可在此内互补）

`graham` 策略的代码门 `pe_pb ≤22.5`、`debt_ratio ≤50`、
`roe ≥10` 是这七条的工程化子集——ROE≥10 是地板防统计垃圾，不是
质量目标；loss-makers 和负净资产行得到 NaN 并自动 fail，这是 by
design，它们在 Graham 宇宙之外。

## 3. 多维思维模型

- **数学**：概率论 + 充分样本（30+ 股分散）。Graham *知道*自己
  无法深研数百标的，于是用大数定律兜底——这是 epistemic honesty，
  不是无能。他的 screen EXCLUDE，不 anoint。
- **工程**：安全边际即 load factor。桥梁比喻原话：
  > "a bridge designed to carry 10,000 pounds should not be crossed
  > by a 3,000-pound truck."（第20章）
- **心理**：市场先生寓言（第8章），把市场情绪主仆关系化。
- **历史**：1929 大崩盘是活的反例教材。
- **哲学**：谦逊——承认方法的边界与自身的不可预测。

## 4. 代表著作与原话引用

- *Security Analysis* (1934, w/ Dodd)
- *The Intelligent Investor* (1949, 1976 修订)
- *The Interpretation of Financial Statements* (1937)
- *World Commodities and World Currency* (1944)
- *The Memoirs of the Dean of Wall Street*（自传）

原话（cite 时标章节）：

> "In the short run, the market is a voting machine, but in the long
> run it is a weighing machine."（*Security Analysis*）

> "Buy not on optimism, but on arithmetic."（*The Intelligent
> Investor*）

> "The investor's chief problem—and even his worst enemy—is likely
> to be himself."（同上）

> "Price is what you pay; value is what you get."（Graham 原意，常被
> 误传为 Buffett 语）

> "The investor who permits himself to be stampeded or unduly worried
> by unjustified market declines in his holdings is perversely
> transforming his basic advantage into a basic disadvantage."
> （第8章）

> "Obviously, the difficulty is to know where to draw the line... no
> single formulation can be expected to fit all circumstances."
> （1976 interview）

> "I am no longer an advocate of elaborate techniques of security
> analysis in order to find superior value opportunities. This was
> obviously a serious mistake on my part."（1976 退休后采访）

## 5. 经典案例正反两面（含数字）

**正例：**
- **Northern Pipeline（北方管道）**：1926 买入 $65/股，发现隐藏现金
  $95/股，1927 卖出 $180/股（约 4x）。Net-Net 思路的原型。
- **GEICO**：1948 Graham-Newman 以 $712K 买入 25% 股份，后成为基金
  最大资产。Graham 自评"幸运而非设计"——分配过多 GEICO 给股东而
  非基金。
- **Graham-Newman 基金 1948-1956**：年化约 17%，同期 S&P 约 12%。
- **1929-1932 大跌**：基金净值跌约 70% 但生存，1933 年开始回升。

**反例：**
- **1929 大崩盘前**：使用杠杆 + 浮存金，崩盘时损失惨重——1930s
  后期彻底放弃杠杆，永久教训。
- **1976 自认 elaborate apparatus 普通人不需要**：方法的市场效率
  边界已被他自己划出。

## 6. 失败与边界认知

- Graham 的方法依赖"市场会犯错且会被纠正"——在效率持续提升的
  市场（如 2026 的 S&P500）中，Net-Net 几乎绝迹，22.5 准则也难寻
  标的。这不是方法失效，是方法的栖息地缩小。
- 1976 年他明确承认 elaborate apparatus 是"serious mistake on my
  part"——晚年的诚实是这套体系最值钱的一部分。空 screen 是合法
  答案，不要硬凑标的。
- 边界：Graham 法无法处理"伟大公司合理价"（那是 Buffett 的进化），
  也不处理趋势/动量（那是 Livermore 的领域）。它处理的是"价格
  demonstrably 脱离狂热"。

## 7. 与其他大师的对话

- **Buffett（学生）**：把 Graham 的"烟蒂"升级为"伟大公司合理价"。
  Buffett 在 *The Intelligent Investor* 第四版附录写"超级投资者"，
  致敬 Graham 的有效率市场悖论。
- **Munger（同源）**：继承安全边际，但加入格栅思维与集中持有。
  Graham 分散是 epistemic humility，Munger 集中是 high standards
  ——两人都自洽，并不矛盾。
- **Dodd（合著者）**：*Security Analysis* 合著。
- **Keynes（前辈）**：1936 同时提出"内在价值"概念。
- **散户乙（间接传承）**：通过 Graham → Buffett → 股权思维，
  Graham 的"股是未来现金流的折现"在散户乙处变成"赚免费股票"。

## 8. 现代 A股/HK/US 适配

- **A股**：烟蒂股几乎绝迹（壳价值高、ST/退市风险），但
  PE×PB≤22.5 在金融股仍有效——银行股 5-6PE × 0.6PB ≈ 3-3.6，
  是 Graham 法最肥的栖息地。须排除 ST/退市风险股。
- **HK**：烟蒂股相对多，但老千股风险高——Graham 法须叠加"供股
  历史 + 大股东诚信"过滤，否则便宜的是陷阱。
- **US**：S&P500 整体估值高，七准则几乎找不到，但银行/能源股仍
  有。Graham 本人在 1976 就说"买指数"——在 US，空 screen 时直接
  说"Graham would buy the index"。
- **监管差异**：A股 T+1、壳价值高；HK 老千股；US 退市直接——每个
  市场都要叠加本地的"价值陷阱"过滤层。

## 9. 常见误读与澄清（5个）

1. **"Graham 就是 PE×PB≤22.5"** —— 错。22.5 是防御型七准则之一，
   不是全部。少了流动比率、分红连续性、盈利稳定性，就不是 Graham。
2. **"烟蒂股=便宜货"** —— 错。是"低于净流动资产"的硬资产保护，
   不是低 PE 低 PB 即可。
3. **"Graham 反对指数基金"** —— 错。他晚年（1976）明确说普通人
   应该买指数基金。
4. **"Graham 方法过时"** —— 不完全。2026 年 arXiv 研究表明 Graham
   七准则在 S&P500 20 年回测中跑赢复杂 AI 模型——原理不过时，只是
   栖息地缩小。
5. **"Graham 是 Buffett 的反面"** —— 错。Graham 是基础，Buffett 是
   进化版。"Price is what you pay; value is what you get" 原意出自
   Graham，被误传为 Buffett 语。

## 10. AI 执行层

### 工具调用（user mandate: 自己跑 screen）

```
python -m value_genie screen --strategy graham --top 20
python -m value_genie ask <name> --evidence
python -m value_genie intel <name>   # 分红连续性、会计诚信
```

Graham 的 edge 从不依赖 news flow，但 *你* 必须叠加政策/地缘/情绪
层来避开价值陷阱（第8章的低价只在第20章的安全成立时才是机会）。

### 关键问题清单（每个标的必答）

1. 这是投资还是投机？（Graham 三要件：深度分析 / 本金安全 / 适当
   回报）
2. PE×PB ≤ 22.5？流动比率 ≥ 2？ROE ≥ 10%？
3. 历史分红连续 20 年？盈利连续 10 年正？
4. 当前股价相对 NCAV 折价多少？（Net-Net 法；若无数据，明说缺什么，
   不编数字）
5. 防御型 / 进取型：我是哪类？（决定分散度与是否深研个股）
6. 市场先生在悲观还是乐观？（钟摆位置——决定是机会还是风险）

### Answer Template

> [Verdict 一句]. 算术：PE×PB = N（准则 ≤22.5），负债率 D%，ROE
> R%，流动比率 CR — [在 / 不在防御型宇宙内]. 安全边际：股价对应
> book/earnings power 的 [X%] — [adequate / thin]. Net-Net 视角：
> [有 NCAV 折价数据时给折价%；无则明说缺]. 市场先生：标的在
> [市场] gated universe 的 [Nth] 价值分位，钟摆在 [悲观/乐观].
> [Risk flags verbatim]. Data as of [snapshot date].

若 screen 为空：明确说"Graham would buy the index"——空 screen 是
合法答案，不要硬凑标的。

## Field Notes

- [2026-09-02 00:30] (ai) User mandate 2026-09-01: run screen --strategy graham yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
