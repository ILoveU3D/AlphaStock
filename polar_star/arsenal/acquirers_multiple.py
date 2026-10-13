"""acquirers-multiple — Gray & Carlisle, Deep Value: EV/EBITDA, the
acquirer's takeover multiple, ranked cheapest-first.

DORMANT — EV components (cash, debt split) and EBITDA are absent from
all three snapshot sources (a_balance carries receivable/inventory
only; hk_f10 carries no cash/debt split; us_financials carries no
cash/EBITDA decomposition).  Wake condition: balance-sheet /
income-statement expansion carrying cash, debt and EBITDA.  No output
is fabricated while dormant.
"""


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "acquirers-multiple",
        "status": "dormant",
        "reason": "EV components (cash, debt split) and EBITDA absent "
                  "from all three snapshot sources",
        "wake_condition": "balance-sheet/income-statement expansion "
                          "(cash, debt, EBITDA)",
    }
