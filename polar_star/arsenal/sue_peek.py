"""sue-peek — Ball & Brown (1968) / standard SUE (standardized
unexpected earnings): earnings surprise vs the consensus expectation,
standardized by the surprise history.

DORMANT — no expected-EPS consensus time-series in the snapshot: A
ratings carry per-report eps fields, not a quarterly consensus
timeline; US/HK carry none.  Wake condition: a consensus-EPS series
source.  No output is fabricated while dormant.
"""


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "sue-peek",
        "status": "dormant",
        "reason": "no expected-EPS consensus time-series (A ratings "
                  "carry per-report eps fields, not a quarterly "
                  "consensus timeline; US/HK none)",
        "wake_condition": "consensus EPS series source",
    }
