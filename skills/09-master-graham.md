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
version: 1
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "格雷厄姆会怎么看X" with the Graham lens: margin of safety as
*arithmetic*, Mr. Market as a servant, and the humility to know that
deep analysis of everything is impossible.

## Graham's Framework (the essence, not the religion)

1. **Margin of safety is a load factor, not a vibe**. A bridge
   engineered for 10 tons is crossed safely by 3-ton trucks. Price so
   low that even if your assumptions are wrong you don't get hurt.
   The famous defensive rule: **PE x PB ≤ 22.5** (15 x 1.5, with
   slack to trade one off against the other). The screen computes
   `pe_pb = pe_ttm x pb` from existing columns and gates on ≤22.5;
   loss-makers and negative-book rows get NaN and fail — by design,
   they are outside his universe.

2. **Mr. Market is your servant, not your master** (chapter 8, the
   book's heart): a bipolar neighbor quoting prices daily. You are
   free to ignore him, trade with him when he's foolish — never take
   his mood as information about the business.

3. **Diversification as epistemic honesty** — the anti-Munger, and
   both men are coherent. Graham *knew* he could not deeply analyze
   hundreds of names, so he spread across 30+ and let the law of
   large numbers do the work. His screens EXCLUDE; they do not
   anoint. Which is why graham gates are simple, numeric, and strict:
   `pe_pb ≤22.5`, `debt_ratio ≤50`, `roe ≥10` (a floor against
   statistical junk, not a quality target).

4. **The net-net principle lives on in spirit**: buying below 2/3 of
   net current asset value was his 1930s bread and butter; such
   names are nearly extinct in screened markets today. The 22.5 rule
   is its modern heir — price demonstrably detached from euphoria.

5. **Late-life honesty (1976 interview)**: he said the framework had
   reduced to owning an index fund for most people — the elaborate
   apparatus was for professionals. When the graham screen finds
   nothing worth conviction, say "Graham would buy the index" rather
   than forcing a pick. An empty screen is a valid answer.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy graham --top 20
   ```
2. Graham's edge never depended on news flow — but *you* must still
   overlay policy/geopolitics/sentiment to avoid value traps
   (chapter-8 price is only opportunity if chapter-20 safety holds).
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict]. Arithmetic: PE x PB = N (rule: ≤22.5), debt ratio D%,
> ROE R% — [inside / outside the defensive universe]. Margin of
> safety: price implies [X%] of book/earnings power — [adequate /
> thin]. Mr. Market context: name trades at [Nth] value percentile of
> [market] gated universe. [Risk flags verbatim]. Data as of
> [snapshot date].

## Field Notes

- [2026-09-02 00:30] (ai) User mandate 2026-09-01: run screen --strategy graham yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
