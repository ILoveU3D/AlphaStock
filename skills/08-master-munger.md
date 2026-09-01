---
id: master-munger
title: Master - Charlie Munger (Invert + Latticework + Sit-on-Your-Ass)
order: 8
triggers:
  - 芒格会怎么看
  - munger
  - 反过来想
  - 格栅思维
  - 坐等投资法
  - 芒格视角
commands:
  - screen --strategy munger
  - ask --evidence
version: 1
updated_at: 2026-09-02T00:30:00
---

# Playbook

Answer "芒格会怎么看X" with the Munger lens: inversion, a latticework
of mental models, and the patience to do almost nothing.

## Munger's Framework (the essence, not the one-liners)

1. **Invert, always invert** (via Jacobi). Don't ask "how do I make
   money on X" — ask "how would I *guarantee* losing money here", then
   avoid that list. His kill list: gambling-quality businesses,
   promoted stories, EBITDA worship, anything requiring a forecast he
   can't make, and the "too hard" pile (most things go in the pile).
   The `munger` strategy's hard gates ARE the inversion: ROE ≥20,
   gross margin ≥40%, debt ≤50% eliminate failure modes *first*;
   scoring only ranks the survivors.

2. **A latticework of models**: no single discipline suffices. Base
   rates (is this the exception or the rule?), compound interest
   (the only math that matters, applied obsessively), psychology of
   misjudgment (his 25 biases — incentive bias above all: "show me
   the incentive and I will show you the outcome"), and evolution
   (moats are species; they adapt or die).

3. **Sit-on-your-ass investing**: "The big money is not in the buying
   and the selling, but in the waiting." The 20-slot punch card — if
   you could only make 20 investments in your life, you'd think very
   hard before each. Late in life his Daily Journal portfolio was
   4-5 positions. Concentration is the *consequence* of high standards,
   not risk appetite.

4. **The cheap-mediocre trap** (his historical contribution): he moved
   Buffett past Graham with "a great business at a fair price is
   superior to a fair business at a great price." Time is the friend
   of the wonderful business, the enemy of the mediocre.

5. **Trust the wonderful business's earnings**: unlike Buffett's
   strategy, munger carries *no* cash-flow gate — a deliberate
   calibration. Munger trusted visible franchise economics over
   forensic accounting; verify cash when the AI is unconvinced.

## Workflow

1. Run the screen yourself (user mandate):
   ```
   python -m value_genie screen --strategy munger --top 20
   ```
2. Apply inversion on the survivors: for each name, articulate the
   failure mode first. If you cannot state how this business dies,
   you don't understand it — that cuts both ways.
3. For survivors: `python -m value_genie ask <name> --evidence`.

## Answer Template

> [Verdict]. Inverted: the way to lose here is [failure mode], and
> that is [avoided / present]. Franchise: ROE X%, gross margin Y%,
> debt Z% — [wonderful / merely fine]. Against the punch card: this is
> [one of 20 / not]. [Risk flags verbatim, as incentive analysis].
> Data as of [snapshot date].

## Field Notes

- [2026-09-02 00:30] (ai) User mandate 2026-09-01: run screen --strategy munger yourself, then overlay policy/geopolitics/market/sentiment checks on top names; state which names were cut or downgraded and why.
