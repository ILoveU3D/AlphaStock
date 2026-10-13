"""mae-mfe-audit (DORMANT) — MAE/MFE excursion audit of our own stops.

Maximum Adverse/Favorable Excursion analysis calibrates the house
stop-loss discipline against what closed trades actually did.  It needs
the trading journal feed — trading/seasons/ lives OUTSIDE the
snapshot-pure weapon context by design — plus at least one closed
trade.  Until a journal->context channel is built and closed trades
accumulate, the weapon is registered but disarmed.  run() always
returns the dormant envelope.

Lineage: house stop-loss self-calibration (excursion analysis,
standard trade-review practice).
"""

ANCHOR = ("MAE/MFE 止损自校准——journal 通道未建, 休眠; 红灯可否决,"
          "绿灯不构成买入理由")


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "mae-mfe-audit",
        "anchor": ANCHOR,
        "status": "dormant",
        "reason": ("trading journal feed outside snapshot-pure context "
                   "+ no closed trades accumulated"),
        "wake_condition": ("journal->context channel built + >= 1 closed "
                           "trade in trading/seasons"),
    }
