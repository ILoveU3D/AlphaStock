---
id: master-sanhuyi
title: Master - 散户乙 (Free Shares via Dividend Compounding + Cost Recovery)
order: 17
triggers:
  - 散户乙会怎么看
  - 免费股票
  - 成本收回
  - 赚股票不赚利润
  - 股息复利
commands:
  - screen --strategy sanhuyi
  - ask --evidence
  - intel X
version: 3
updated_at: 2026-09-10T23:40:31
---

# Playbook

Answer "散户乙会怎么看X" with the free-shares lens: the goal of owning
stocks is not CNY profit but a growing pile of **fully-paid-for
claims on future cash flows** — "股票的目的不是赚利润，而是赚取
免费的股票，通过增值卖出收回成本，或者通过分红，达到获得免费
股票，然后长期持有"（user-introduced 2026-09-10）.

## Sanhuyi's Framework

1. **计价单位从"元"换成"股"**. Your wealth is shares × per-share
   cash flow, not the ticker's last print. The market quotes your
   property daily; only the business's cash generation is fact.
   This is the retail-executable form of the DCF universal law:
   the value you own = the future dividend stream, discounted.

2. **Two paths to free shares** (either makes the remaining
   position psychologically permanent):
   - **增值卖出收回成本** — after appreciation, sell the fraction
     equal to cost; what remains cannot lose you money. For
     good-but-not-keyhole positions only.
   - **分红收回成本** — let dividends return the cost; shares stay
     intact and keep compounding. The ONLY path compatible with
     keyhole positions — selling to recover cost shrinks the
     terminal-value exposure the whole system exists to build.

3. **The engine is REAL cash return**. Gates: ROE ≥15 (dividends
   can grow), OCF yield ≥4 (funded by operations), 股息率 ≥2.5
   (the payout exists and is meaningful — pipeline computes it for
   A/HK/US from annual div_paid ÷ market cap since 2026-09-10),
   负债率 ≤60, and the borrowed-dividend veto — 借钱分红 = fake
   free shares, the "dividend" is principal being returned, not
   cash flow.

4. **Holding psychology is the product**. Once cost is recovered,
   drawdowns stop being threats — the shares are free — and a
   great compounder can be held through -50% noise. This is the
   behavioral bridge to Buffett's "our favorite holding period is
   forever", which retail investors otherwise cannot execute.

5. **The recovery arithmetic** (say it with numbers):
   - flat yield y: ~1/y years to recover cost;
   - yield growing at g: ~ln(1+g/y)/ln(1+g) years
     (e.g. y=3%, g=8% → ~17 years);
   - dividend reinvestment (buying more shares on dips) shortens
     it further — 散户乙's actual practice.

## Hard limits — state these in EVERY answer

1. **Cost recovery is a position-psychology tool, NEVER a sell
   trigger.** The exit trigger stays business-level falsification
   (Duan layer). Waiting to "recover cost before selling" rides a
   falsified business to zero (康美-style).
2. **"Free" shares still carry opportunity cost** — the remaining
   capital still gets DCF'd. Free means emotionally free, not
   economically free.
3. **The method selects nothing** — it presupposes a durable
   compounder was chosen first, via business model + culture
   analysis. It stacks on top, it never replaces.
4. **No-dividend compounders cannot walk the dividend path.** For
   them, sell-to-recover kills the compounding machine (Buffett's
   own regret); the playbook reduces to hold / add on business
   strength / never trim for cost recovery.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy sanhuyi --top 20
   ```
2. For survivors ask the dividend question: will this business pay
   OUT (not borrow) a growing dividend in year 10? Run
   `python -m value_genie ask X --evidence` plus `intel X`.
   dividend_yield comes from the pipeline for all markets (A: 东财
   分红事件表 aggregated per declaration year; HK: F10 DIVIDEND_RATE
   with div_paid fallback; US: SEC frames) — annual-basis, so a
   company that recently initiated/cut its payout shows the OLD
   yield; cross-check intel 公告层分红方案 for fresh changes.
3. State which path fits this position (sell-recovery /
   dividend-recovery / neither — no real payout) and the years-to-
   recovery arithmetic under path 5.

## Answer Template

> [Verdict]. Free-share engine: ROE X%, OCF yield Y%, dividend
> yield Z%, dividend [growing/stale/none — annual basis, check intel
> for fresh payout changes], borrowed-dividend [clean/veto]. Path:
> [sell-recovery / dividend-recovery / neither].
> Years to free shares: [N at current yield; M if dividends grow at
> g]. The business this rests on: [one sentence on 10-year dividend
> durability]. [Risk flags verbatim]. Data as of [snapshot date].

## Field Notes
- [2026-09-10 22:45] (ai) sanhuyi registered as master #7 (user-introduced folk master). dividend_yield deliberately NOT a gate: master.csv populates it for HK only (106/123; A 0/200, US 0/181) — a hard gate would silently kill A/US. Future: merge A dividend_yield from a_dividends.csv (div_paid ÷ market cap per code) into the pipeline, then add ("dividend_yield", ">=", 2.5).
- [2026-09-10 22:45] (ai) Keyhole compatibility (user 钥匙孔原则): the dividend-recovery path is the only free-share path allowed on keyhole positions; sell-to-recover-cost is for non-keyhole positions only and NEVER overrides the business-falsification exit trigger.
- [2026-09-10 23:40] (ai) A-share dividend gap closed 2026-09-10: add_cashflow_factors now derives dividend_yield = annual div_paid / market_cap for ALL markets (A: 东财分红事件表 aggregated per declaration year; HK: F10 DIVIDEND_RATE wins, div_paid fallback; US: SEC frames). sanhuyi gate dividend_yield>=2.5 is live. Snapshots built before this fix show A dividend_yield null — refetch before screening sanhuyi; the yield is annual-basis, so fresh payout changes need the intel 公告层 cross-check.
