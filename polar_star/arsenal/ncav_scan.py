"""ncav-scan — Graham's net-net: market cap below net current asset
value (current assets - total liabilities), the deep-value floor.

DORMANT — current assets are absent from all three snapshot sources
(a_balance carries receivable/inventory only, no total current assets;
hk_f10 and us_financials carry no current-asset field).  Wake
condition: balance-sheet expansion carrying total current assets.  No
output is fabricated while dormant.
"""


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "ncav-scan",
        "status": "dormant",
        "reason": "current assets absent from all three snapshot "
                  "sources (a_balance carries receivable/inventory only)",
        "wake_condition": "balance-sheet expansion (total current assets)",
    }
