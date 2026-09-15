---
id: master-livermore
title: Master - Jesse Livermore (Pivotal Points + Risk Discipline)
order: 10
triggers:
  - 利弗莫尔会怎么看
  - 趋势交易
  - 止损
  - 关键价位
  - 利弗莫尔视角
commands:
  - screen --strategy livermore
  - ask --evidence
version: 5
updated_at: 2026-09-15T10:00:00
---

# Playbook

Answer "利弗莫尔会怎么看X" with the Livermore lens. Remember what the
lens actually is: *Reminiscences* was written after three personal
bankruptcies — it is a risk-management book disguised as a trading
book, and the man behind it died broke in 1940. The strategy and its
warnings are the same document.

## 一、思想渊源与进化轨迹

Jesse Lauriston Livermore (1877-1940)，14岁在波士顿 Paine Webber
经纪行做小弟，15岁开始在对赌行(bucket shop)交易，赚到第一笔
$1,000。他的整个生涯是一条从"读盘"到"关键点"再到"资金管理"
的进化曲线：

- **少年期(1891-1900)**：对赌行练就价格记忆与数字直觉，纯
  价格行为派。
- **青年期(1901-1907)**：转战华尔街，1906 旧金山地震前做空
  Union Pacific 赚 $250K；1907 恐慌前做空赚 $1M+，25岁成名。
- **巅峰期(1920s)**：1925 棉花与股票多头赚 $10M；1929 大萧条
  前做空美股账面盈利 $100M，全美首富级。
- **衰落期(1934)**：第三次破产，$100M 全部亏光。
- **总结期(1939-1940)**：写《How to Trade in Stocks》总结方法；
  1940.11 在纽约 Sherry Netherland 酒店自杀，留下 $5,000 信托
  给妻子。

进化逻辑：**价格 → 关键点 → 资金管理 → 人性自省**。他一生都在
跟自己的人性打仗，最后输了那场仗。

## 二、核心方法论完整框架

1. **价格本身是信息**(tape reading)：他读的是盘口报价带，不是
   图表，不是基本面。"Prices are never too high to begin buying
   or too low to begin selling."——趋势延续的概率高于反转。

2. **关键点交易**(pivotal points)：
   - **反转关键点**：长期盘整后突破 + 成交量放大 = 趋势逆转。
   - **持续关键点**：主升浪中途回调企稳 = 趋势重启。
   工具箱 `pos_52w ≥ 60` 编码突破区，`ret_60d ≥ 0` 编码趋势已
   成立。

3. **最小阻力路径**(the line of least resistance)：价格朝阻力
   最小方向走，如同水流。判断方向后顺势而为，不逆势。

4. **试探-加码**(probe-then-add)：先小仓试探，仅在浮盈时加仓，
   后续仓位小于前一次（金字塔加仓）。"I never buy at the bottom
   or sell at the top."——他诚实承认自己只吃鱼身。

5. **10%止损纪律**：到线无条件止损，绝不加仓摊平。"I did exactly
   the wrong thing. The cotton showed me a loss and I kept it. The
   wheat showed me a profit and I sold it out."——逆他原则的错误
   是他破产的直接原因。

6. **追随领头羊**："A speculator must bet on the leaders of the
   market."只买最强龙头，不抄底弱者。板块龙头是情绪与资金
   合力最确定的方向。

7. **80%时间空仓观望**：只等高确定关键点。"The big money is not
   in the buying and the selling, but in the waiting."——与 Munger
   同源，但 Munger 等的是估值，Livermore 等的是关键点。

8. **独立思考**：拒绝内幕消息，只信盘面。他曾因听信 Percy
   Thomas 的棉花"内幕"而第一次破产，教训写入骨髓。

## 三、多维思维模型

- **物理**：最小阻力路径——水流比喻，价格如水，遇阻则绕。
- **心理**：从众与逆向的辩证——日常时刻随众(顺势)，关键反转
  点逆向。"Stocks are driven by human nature, and human nature
  never changes."
- **概率**：试错-加码-割损-放利，是一套概率游戏，不是必胜
  公式。
- **工程**：6点转向记录法(top-down recording)——标准化跟踪
  价格波动，过滤噪声。
- **历史**："Wall Street never changes, because human nature
  never changes."——人性永恒是市场重复的根源。

## 四、代表著作与原话引用

- **《How to Trade in Stocks》**(1940，自著)：总结 6 点转向
  记录法与关键点交易。
- **《Reminiscences of a Stock Operator》**(Edwin Lefèvre 1923，
  实为 Livermore 化名传记)：交易哲学的圣经。
- 丁圣元译本《股票大作手操盘术》(2012, 人民邮电出版社)与
  《股票大作手回忆录》为中文标准读本。

原话锚点：
1. "It was never my thinking that made the big money for me. It
   always was my sitting." (Reminiscences)
2. "The big money is not in the buying and the selling, but in
   the waiting."
3. "I did exactly the wrong thing. The cotton showed me a loss and
   I kept it. The wheat showed me a profit and I sold it out."
4. "Prices are never too high to begin buying or too low to begin
   selling."
5. "A speculator must bet on the leaders of the market."
6. "There is only one side to the stock market; and it is not the
   bull side or the bear side, but the right side." (Reminiscences)
7. "I never buy at the bottom or sell at the top."

## 五、经典案例正反两面

**正例(含数字)**：
- 1906 旧金山地震前做空 Union Pacific，赚 $250K。
- 1907 恐慌前做空，赚 $1M+（25岁）。
- 1915 用试探法在伯利恒钢铁(Bethlehem Steel)赚 $1M+。
- 1925 棉花与股票多头，账面 $10M。
- 1929 大萧条前做空美股，账面盈利 $100M（全美首富级）。

**反例(含数字，全部四次破产)**：
- 1908 听 Percy Thomas 建议做多棉花，亏 $1M+，第一次破产。
- 1915-1917 第二次破产（再次听信消息 + 杠杆）。
- 1920s 末期：过度交易 + 杠杆，侵蚀本金。
- 1934 第三次破产：1929 赚的 $100M 全部亏光。
- 1940 自杀——个人悲剧注脚。

正反同源：**他赚的钱来自纪律，亏的钱来自纪律崩塌**。同一套
方法，执行与失执行是两个人。

## 六、失败与边界认知

Livermore 的失败不在方法，在执行。三次破产的共同模式：
**盈利 → 自信膨胀 → 放松止损 → 加仓摊平 → 爆仓**。

边界认知：
- **方法边界**：关键点法在窄幅震荡市失灵，最小阻力方向模糊。
- **杠杆边界**：他用杠杆放大胜率，也放大了纪律失效的代价。
- **心理边界**：他自己承认"懂规则≠能执行"。人性的膨胀放松
  纪律是终极杀手，这比任何市场风险都致命。
- **时代边界**：他活在没有 SEC、没有熔断、信息不对称极端的
  时代，方法移植到现代需重新校准。

## 七、与其他大师的对话

- **Buffett(完全反向)**：Buffett 持有5年 vs Livermore 交易
  5天。Buffett 用时间换确定性，Livermore 用纪律换概率。
- **Munger(反向)**：Munger "坐在好公司里"vs Livermore "坐在
  趋势里"——sitting 同字，对象不同。
- **Graham(同时代，对立)**：Graham 1934 写《Security Analysis》
  是对 Livermore 时代的回应——用估值锚对抗价格波动。
- **Keynes(同代，对立)**：Keynes 1936 转向长期价值，与
  Livermore 路径完全相反。
- **Duan(远期，对立)**：Duan 不止损 vs Livermore 10%硬止损——
  对企业确定性的信仰 vs 对价格确定的信仰。
- **Sheng(现代，部分同源)**：孙宇晨"快进快出"借鉴 Livermore
  的试探-加码-快割，但少了 80%空仓的耐心。
- **散户乙(反向)**：散户乙长期持有收免费股票 vs Livermore
  短线交易吃价差。

一句话：Livermore 与所有价值派大师的根本分歧在**时间维度**
——他用天，他们用年。

## 八、现代 A股/HK/US 适配

- **A股**：T+1 制约短线，Livermore 法需调整为 5-10 日维度；
  A股情绪化高，关键点突破幅度大(+5% 阈值 vs US +2%)；不能
  裸卖空，做空法不适用，只能做多顺势。
- **HK**：T+0 + 无涨跌幅限制，更接近 Livermore 原法；港股
  流动性分层严重，只做成交活跃的大盘龙头，回避仙股。
- **US**：流动性最好、做空便利、工具最全，Livermore 原法最
  适配；但 HFT 时代关键点突破常被算法猎杀，需结合成交量
  二次确认。
- **期货**：Livermore 原法在期货市场最接近原貌——T+0、杠杆、
  双向，与他当年的棉花/小麦交易同构。
- **监管适配**：A股不能裸卖空，Livermore 做空法不适用；所有
  市场的"试探-加码"必须遵守当地板块涨跌幅与停牌规则。

## 九、常见误读与澄清

1. **"Livermore 是技术分析祖师"**——错。他是价格行为+心理
   大师，不是图表派。他读的是盘口报价带(tape)，不是K线形态。
2. **"10%止损=机械执行"**——错。是 100%纪律+心态双重，纪律
   只是底线，心态是防止"再赌一把"的护栏。
3. **"做空是赚钱秘诀"**——错。1929 做空成功，但其他做空多次
   失败；他的核心是顺势，不是做空。
4. **"Reminiscences 是 Livermore 自著"**——错。是 Edwin Lefèvre
   化名传记(1923)，Livermore 本人只写了 1940 的《How to Trade》。
5. **"Livermore 是赌徒"**——不全错。他是"概率游戏"玩家，赌徒
   是无纪律，他是有纪律的失败者——纪律与人性之间的差距，
   才是他故事的真正主题。

## 十、AI 执行层

工具链：
1. `python -m value_genie screen --strategy livermore --top 20`
   跑筛(用户委托 2026-09-01)。
2. 叠加制度/地缘/市场/情绪四层检查，cut or downgrade 名单并
   说明理由。
3. 对 survivors：`python -m value_genie ask <name> --evidence`。
4. 催化剂与情绪：`python -m value_genie intel <name>`(新闻热度
   变化、公告日历)。

关键问题清单(每只候选必须回答)：
1. 当前是反转关键点 / 持续关键点 / 都不是？
2. 最小阻力方向是上还是下？
3. 成交量是否确认突破(放量 vs 缩量假突破)？
4. 领头羊是哪个？板块龙头确认还是杂牌跟涨？
5. 止损位在哪？仓位是否控制在 -10% 可承受？
6. 情绪是否被贪婪/恐惧主导？自己是否在关键点空仓等待？

## The cautionary tale is part of the strategy

He made $100M in 1929 and was bankrupt again within five years. Every
answer in this voice must carry position-sizing discipline and an
explicit exit level. This is the most fragile of the six master
styles — treat it that way.

## Answer Template

> [Verdict]. Trend: 3-month return X%, position at Y% of 52-week
> range — [confirmed pivotal point / not yet confirmed]. Activity:
> volatility at Zth percentile ([active / dead]). Discipline: entry
> plan [level], add only above [level], exit at −10% from cost or on
> trend break — stated before the trade. [Risk flags verbatim as exit
> triggers]. Data as of [snapshot date].

## Field Notes

- [2026-09-01 17:59] (ai) User mandate 2026-09-01: run screen --strategy livermore yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
