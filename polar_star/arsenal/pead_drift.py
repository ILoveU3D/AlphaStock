"""pead-drift — Bernard & Thomas (1989) post-earnings-announcement
drift: abnormal returns drift in the direction of the earnings
surprise for weeks after the announcement.

DORMANT — depends on SUE (sue-peek): no expected-EPS consensus
time-series in the snapshot (A ratings carry per-report eps fields,
not a quarterly consensus timeline; US/HK none), and no
announcement-event calendar to anchor the drift window.  Wake
condition: a consensus-EPS series source (the SUE input) plus an
earnings-announcement event feed.  No output is fabricated while
dormant.
"""


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "pead-drift",
        "status": "dormant",
        "reason": "depends on SUE: no expected-EPS consensus time-series "
                  "(A ratings carry per-report eps fields, not a "
                  "quarterly consensus timeline; US/HK none) and no "
                  "announcement-event calendar",
        "wake_condition": "consensus EPS series source + "
                          "earnings-announcement event feed",
    }
