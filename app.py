"""Value Genie - interactive screening dashboard (Streamlit).

Run with:
    streamlit run app.py

Everything is computed locally from snapshots produced by
`python -m value_genie fetch`; switching strategies or weights
re-scores instantly without touching the network.
"""

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from value_genie import config, report
from value_genie.fetch.kline import kline_cache_path, load_kline
from value_genie.strategy.composite import apply_composite
from value_genie.strategy.presets import (PRESETS, PRESET_LABELS,
                                          normalize_weights)

st.set_page_config(page_title="Value Genie", page_icon=":genie:",
                   layout="wide")

METRIC_COLUMNS = {
    "pe_ttm": st.column_config.NumberColumn("PE (TTM)", format="%.1f"),
    "pb": st.column_config.NumberColumn("PB", format="%.2f"),
    "dividend_yield": st.column_config.NumberColumn("Div yield %",
                                                    format="%.2f"),
    "rev_yoy": st.column_config.NumberColumn("Rev YoY %", format="%.1f"),
    "profit_yoy": st.column_config.NumberColumn("Profit YoY %",
                                                format="%.1f"),
    "roe": st.column_config.NumberColumn("ROE %", format="%.1f"),
    "composite_score": st.column_config.NumberColumn("Composite",
                                                     format="%.1f"),
    "value_score": st.column_config.NumberColumn("Value", format="%.0f"),
    "growth_score": st.column_config.NumberColumn("Growth", format="%.0f"),
    "quality_score": st.column_config.NumberColumn("Quality", format="%.0f"),
    "safety_score": st.column_config.NumberColumn("Safety", format="%.0f"),
    "data_completeness": st.column_config.ProgressColumn(
        "Data", min_value=0.0, max_value=1.0, format="%.0f%%"),
}

RADAR_METRICS = [
    ("pe_ttm", "PE (TTM)", True),       # True = lower is better
    ("pb", "PB", True),
    ("roe", "ROE %", False),
    ("rev_yoy", "Rev YoY %", False),
    ("profit_yoy", "Profit YoY %", False),
    ("gross_margin", "Gross margin %", False),
    ("net_margin", "Net margin %", False),
    ("drawdown_52w", "Drawdown %", True),
]


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_snapshots(data_dir: str) -> list:
    return report.find_snapshots(data_dir)


@st.cache_data(show_spinner=False)
def load_master(snapshot_dir: str) -> pd.DataFrame:
    return report.load_master(snapshot_dir)


@st.cache_data(show_spinner=False)
def load_manifest(snapshot_dir: str) -> dict:
    path = Path(snapshot_dir) / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@st.cache_data(show_spinner=False)
def load_kline_cached(snapshot_dir: str, market: str, code: str):
    df = load_kline(kline_cache_path(Path(snapshot_dir), market, code))
    if df is None or df.empty:
        return None
    return df


def fmt_cap(value: float) -> str:
    """Human-readable market cap in local currency units."""
    if pd.isna(value):
        return "-"
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(value) >= scale:
            return f"{value / scale:,.1f}{unit}"
    return f"{value:,.0f}"


# ---------------------------------------------------------------------------
# Skills Manager page (human refinement path for skills/)
# ---------------------------------------------------------------------------
def render_skills_manager():
    from value_genie import skills as sk
    st.header("Skills Manager")
    st.caption(
        "Human refinement path: view and edit playbooks, promote or delete "
        "AI field notes. Agents append notes via "
        "`python -m value_genie skill note <id> \"lesson\"`.")
    skills, errors = sk.load_skills(str(config.SKILLS_DIR))
    for e in errors:
        st.error(f"skill load error: {e}")
    if not skills:
        st.info(f"no skills found under {config.SKILLS_DIR}")
        return
    labels = [f"{s.order:02d}  {s.title}" for s in skills]
    s = skills[st.selectbox("skill", labels)]

    notes = sk.field_notes(s)
    st.subheader(f"{s.id}  (v{s.version}, {len(notes)} notes, "
                 f"updated {s.updated_at})")

    with st.form("skill_editor"):
        title = st.text_input("title", s.title)
        triggers = st.text_area("triggers (one per line)",
                                "\n".join(s.triggers))
        body = st.text_area("playbook body (markdown)", s.body, height=360)
        if st.form_submit_button("save (bumps version)"):
            s.title = title.strip()
            s.triggers = [t.strip() for t in triggers.splitlines()
                          if t.strip()]
            s.body = body
            try:
                path = sk.save_skill(str(config.SKILLS_DIR), s)
                st.success(f"saved {path.name} (v{s.version})")
                st.cache_data.clear()
                st.rerun()
            except sk.SkillFormatError as exc:
                st.error(str(exc))

    st.markdown("#### Field notes")
    if not notes:
        st.caption("none yet — agents learn, notes appear here")
    for i, (stamp, author, text) in enumerate(notes):
        c1, c2, c3 = st.columns([6, 1, 1])
        c1.markdown(f"`[{stamp}]` **({author})** {text}")
        if c2.button("promote", key=f"promo_{s.id}_{i}",
                     help="move this lesson into the playbook body"):
            sk.promote_note(str(config.SKILLS_DIR), s.id, i)
            st.cache_data.clear()
            st.rerun()
        if c3.button("delete", key=f"del_{s.id}_{i}",
                     help="remove this note as noise"):
            sk.delete_note(str(config.SKILLS_DIR), s.id, i)
            st.cache_data.clear()
            st.rerun()


page = st.sidebar.radio("page", ["Dashboard", "Skills Manager"])
if page == "Skills Manager":
    render_skills_manager()
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.title("Value Genie :genie:")
st.caption("Multi-market value screener - undervalued, growing, "
           "high-quality stocks across A-share / HK / US.")

data_dir = str(config.DATA_DIR)
snapshots = load_snapshots(data_dir)

with st.sidebar:
    st.header("Data")
    if not snapshots:
        st.error("No snapshots found. Run `python -m value_genie fetch` "
                 "first.")
        st.stop()
    snapshot = st.selectbox("Snapshot date", snapshots,
                            index=len(snapshots) - 1,
                            format_func=lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}")
    snap_dir = str(Path(data_dir) / "snapshots" / snapshot)
    master = load_master(snap_dir)
    manifest = load_manifest(snap_dir)
    if master.empty or "market" not in master.columns:
        st.error("This snapshot has an empty master.csv. Re-run "
                 "`python -m value_genie fetch --refresh`.")
        st.stop()

    st.divider()
    st.header("Markets")
    market_cols = st.columns(len(config.MARKETS))
    chosen = {}
    for col, market in zip(market_cols, config.MARKETS):
        available = (master["market"] == market).sum()
        chosen[market] = col.checkbox(
            config.MARKET_LABELS[market], value=True,
            help=f"{available} stocks in snapshot")
    markets = [m for m in config.MARKETS if chosen[m]]
    if not markets:
        st.warning("Select at least one market.")
        st.stop()

    st.divider()
    st.header("Strategy")
    strategy = st.selectbox(
        "Preset", list(PRESETS) + ["custom"],
        index=0,
        format_func=lambda s: "Custom sliders" if s == "custom"
        else PRESET_LABELS[s])
    if strategy == "custom":
        wv, wg = st.columns(2)
        wq, ws = st.columns(2)
        weights = {
            "value": wv.slider("Value", 0.0, 1.0, 0.35, 0.05),
            "growth": wg.slider("Growth", 0.0, 1.0, 0.25, 0.05),
            "quality": wq.slider("Quality", 0.0, 1.0, 0.30, 0.05),
            "safety": ws.slider("Safety", 0.0, 1.0, 0.10, 0.05),
        }
        weights = normalize_weights(weights)
    else:
        weights = dict(PRESETS[strategy])

    top_n = st.slider("Result count", 5, 100, config.DEFAULT_TOP_N, 5)

# ---------------------------------------------------------------------------
# Freshness banner
# ---------------------------------------------------------------------------
created_at = manifest.get("created_at", "")
failures = manifest.get("failures", [])
if failures:
    st.warning(f"Snapshot has incomplete data: {'; '.join(failures)}")
with st.container(border=True):
    left, mid, right = st.columns(3)
    left.metric("As of", f"{snapshot[:4]}-{snapshot[4:6]}-{snapshot[6:]}")
    mid.metric("Stocks scored", f"{len(master):,}")
    right.metric("Pipeline run", created_at.replace("T", " ") or "-")

# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
scored = apply_composite(master, weights, min_pillars=config.MIN_PILLARS)
pool = scored[scored["market"].isin(markets)]
top = (pool.dropna(subset=["composite_score"])
       .sort_values("composite_score", ascending=False)
       .head(top_n).reset_index(drop=True))
top.insert(0, "rank", top.index + 1)

if top.empty:
    st.error("No stocks passed this strategy. Try different weights or "
             "more markets.")
    st.stop()

st.subheader(f"Top {len(top)} picks")
table = top.reindex(columns=["rank", "market", "code", "name", "industry",
                             "price", "pe_ttm", "pb", "dividend_yield",
                             "rev_yoy", "profit_yoy", "roe",
                             "composite_score", "value_score",
                             "growth_score", "quality_score",
                             "safety_score", "data_completeness"])
event = st.dataframe(
    table,
    width="stretch", hide_index=True,
    column_config=METRIC_COLUMNS,
    on_select="rerun",
    selection_mode="single-row",
)

st.download_button(
    "Download CSV", data=top.to_csv(index=False).encode("utf-8"),
    file_name=f"value_genie_{snapshot}.csv", mime="text/csv",
    type="primary")

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
st.subheader("Composite score distribution")
hist = go.Figure()
for market in markets:
    scores = pool[pool["market"] == market]["composite_score"].dropna()
    if len(scores):
        hist.add_trace(go.Histogram(x=scores, name=market, opacity=0.65,
                                    nbinsx=30))
hist.update_layout(barmode="overlay", xaxis_title="Composite score",
                   yaxis_title="Stocks", height=320)
st.plotly_chart(hist, width="stretch")

chart_l, chart_r = st.columns(2)
with chart_l:
    st.subheader("Value vs quality")
    fig = go.Figure()
    for market in markets:
        d = top[top["market"] == market]
        fig.add_trace(go.Scatter(
            x=d["value_score"], y=d["quality_score"],
            mode="markers", name=market,
            text=d["name"], textposition="top center",
            marker=dict(size=d["market_cap"].fillna(0).apply(
                            lambda v: 12 + 28 * min(1.0, v / 3e12)),
                        sizemode="diameter",
                        color=d["composite_score"],
                        coloraxis="coloraxis", showscale=False)))
    fig.update_layout(coloraxis=dict(colorscale="Viridis"),
                      xaxis_title="Value score",
                      yaxis_title="Quality score", height=420,
                      showlegend=len(markets) > 1)
    st.plotly_chart(fig, width="stretch")

with chart_r:
    st.subheader("Top picks by composite")
    bar = go.Figure()
    for market in markets:
        d = top[top["market"] == market][::-1]
        bar.add_trace(go.Bar(y=d["name"] + " (" + d["market"] + ")",
                             x=d["composite_score"], orientation="h",
                             name=market))
    bar.update_layout(xaxis_title="Composite score",
                      yaxis_title="", height=420,
                      showlegend=len(markets) > 1)
    st.plotly_chart(bar, width="stretch")

# ---------------------------------------------------------------------------
# Per-stock detail
# ---------------------------------------------------------------------------
st.subheader("Stock detail")
sel_state = getattr(event, "selection", None)
sel_rows = list(getattr(sel_state, "rows", None) or [])
if sel_rows:
    row = top.iloc[sel_rows[0]].copy()
    st.info(f"Showing table selection: {row['name']} "
            f"({row['market']}:{row['code']})")
else:
    labels = (top["rank"].astype(str) + ". " + top["name"] + " ("
              + top["market"] + ":" + top["code"] + ")").tolist()
    choice = st.selectbox("Pick a stock", labels)
    row = top.iloc[labels.index(choice)].copy()

metric_l, metric_m, metric_r = st.columns(3)
metric_l.metric("Price", f"{row['price']:,.2f} "
                 f"({row.get('currency', '')})")
metric_m.metric("Market cap",
                fmt_cap(float(row["market_cap"])))
metric_r.metric("Composite", f"{row['composite_score']:.1f}/100")

tab_price, tab_radar, tab_vs = st.tabs(["Price history", "Pillar profile",
                                        "vs market median"])

with tab_price:
    kl = load_kline_cached(snap_dir, row["market"], str(row["code"]))
    if kl is None:
        st.info("No cached kline for this stock.")
    else:
        price = go.Figure()
        price.add_trace(go.Scatter(x=kl["date"], y=kl["close"],
                                   mode="lines", name="close",
                                   line=dict(color="#1f77b4")))
        window = kl["close"].tail(config.KLINE_DAYS)
        hi, lo = float(window.max()), float(window.min())
        price.add_hline(y=hi, line_dash="dot", line_color="gray",
                        annotation_text=f"52w high {hi:,.1f}")
        price.add_hline(y=lo, line_dash="dot", line_color="gray",
                        annotation_text=f"52w low {lo:,.1f}")
        price.update_layout(xaxis_title="", yaxis_title="Close",
                            height=380)
        st.plotly_chart(price, width="stretch")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("52w position", f"{row.get('pos_52w', float('nan')):.0f}%")
        c2.metric("Drawdown", f"{row.get('drawdown_52w', float('nan')):.1f}%")
        c3.metric("250d return", f"{row.get('ret_250d', float('nan')):.1f}%")
        c4.metric("Volatility", f"{row.get('volatility', float('nan')):.1f}%")

with tab_radar:
    pillars = ["value_score", "growth_score", "quality_score",
               "safety_score"]
    stock_vals = [row.get(p) for p in pillars]
    market_avg = [pool[pool["market"] == row["market"]][p].mean()
                  for p in pillars]
    radar = go.Figure()
    radar.add_trace(go.Scatterpolar(
        r=stock_vals + stock_vals[:1],
        theta=[p.replace("_score", "").title() for p in pillars]
        + ["Value"],
        fill="toself", name=row["name"]))
    radar.add_trace(go.Scatterpolar(
        r=market_avg + market_avg[:1],
        theta=[p.replace("_score", "").title() for p in pillars]
        + ["Value"],
        fill="toself", name="Market average", opacity=0.4))
    radar.update_layout(polar=dict(radialaxis=dict(range=[0, 100])),
                        height=420)
    st.plotly_chart(radar, width="stretch")

with tab_vs:
    peers = pool[pool["market"] == row["market"]]
    fig = go.Figure()
    names, stock_vals, med_vals = [], [], []
    for col, label, _lower_better in RADAR_METRICS:
        if col not in master.columns:
            continue
        names.append(label)
        stock_vals.append(float(row.get(col, float("nan"))))
        med_vals.append(float(peers[col].median()))
    fig.add_trace(go.Bar(name=row["name"], x=names, y=stock_vals))
    fig.add_trace(go.Bar(name="Market median", x=names, y=med_vals,
                         opacity=0.5))
    fig.update_layout(barmode="group", yaxis_title="Value", height=400)
    st.plotly_chart(fig, width="stretch")

st.divider()
st.caption("Data: Eastmoney / SEC EDGAR / Tencent. Scores are per-market "
           "percentiles; nothing here is investment advice.")
