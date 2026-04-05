"""
Corpus Christi Civic Data — Streamlit App
==========================================
Public-facing app for exploring Corpus Christi city council data.
Currently shows council member profiles with voting records.
"""

import streamlit as st
import plotly.express as px
import pandas as pd

from utils.db import load_council_members, load_votes_for_person

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Corpus Christi Civic Data",
    page_icon="🏛️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — council member picker
# ---------------------------------------------------------------------------

st.sidebar.title("🏛️ CC Civic Data")
st.sidebar.markdown("Corpus Christi city council voting records.")
st.sidebar.divider()

with st.sidebar:
    with st.spinner("Loading council members..."):
        council_members = load_council_members()

if not council_members:
    st.error("Could not load council members. Check your Supabase credentials.")
    st.stop()

names = [m["person_full_name"] for m in council_members]
selected_name = st.sidebar.selectbox("Select a council member", names)
selected = next(m for m in council_members if m["person_full_name"] == selected_name)

# ---------------------------------------------------------------------------
# Profile header
# ---------------------------------------------------------------------------

st.title(selected["person_full_name"])

end_label = selected["current_end"] or "Present"
st.caption(
    f"{selected['current_title']}  ·  "
    f"{selected['current_start'] or '—'} – {end_label}"
)

if selected["person_email"]:
    st.write(f"✉ {selected['person_email']}")

st.divider()

# ---------------------------------------------------------------------------
# Load votes
# ---------------------------------------------------------------------------

with st.spinner("Loading voting record..."):
    votes_df = load_votes_for_person(selected["person_id"])

if votes_df.empty:
    st.info("No voting records found for this council member.")
    st.stop()

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

total        = len(votes_df)
absent_count = (votes_df["Vote"] == "Absent").sum()
nay_count    = (votes_df["Vote"] == "Nay").sum()
aye_count    = (votes_df["Vote"] == "Aye").sum()
participating = total - absent_count
aye_pct = round(aye_count / participating * 100, 1) if participating > 0 else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Votes", f"{total:,}")
col2.metric("Aye %", f"{aye_pct}%")
col3.metric("Nay", f"{nay_count:,}")
col4.metric("Absent", f"{absent_count:,}")

st.divider()

# ---------------------------------------------------------------------------
# Voting breakdown chart + vote history side by side
# ---------------------------------------------------------------------------

left, right = st.columns([1, 2])

with left:
    st.subheader("Breakdown")
    vote_counts = votes_df["Vote"].value_counts().reset_index()
    vote_counts.columns = ["Vote", "Count"]

    color_map = {
        "Aye":     "#2ecc71",
        "Nay":     "#e74c3c",
        "Absent":  "#95a5a6",
        "Abstain": "#f39c12",
        "Recused": "#9b59b6",
        "Present": "#3498db",
    }
    fig = px.pie(
        vote_counts,
        names="Vote",
        values="Count",
        color="Vote",
        color_discrete_map=color_map,
        hole=0.4,
    )
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Vote History")

    keyword = st.text_input("Filter by keyword", placeholder="e.g. zoning, budget...")
    display_df = votes_df.copy()
    if keyword:
        mask = display_df["Matter"].str.contains(keyword, case=False, na=False)
        display_df = display_df[mask]

    # Color-code the Vote column
    def color_vote(val):
        colors = {
            "Aye":     "color: #2ecc71; font-weight: bold",
            "Nay":     "color: #e74c3c; font-weight: bold",
            "Absent":  "color: #95a5a6",
            "Abstain": "color: #f39c12",
            "Recused": "color: #9b59b6",
        }
        return colors.get(val, "")

    show_df = display_df[["Date", "Matter", "Vote", "Result"]].copy()
    show_df["Date"] = show_df["Date"].dt.strftime("%Y-%m-%d")
    show_df["Matter"] = show_df["Matter"].str[:80]  # truncate long titles

    styled = show_df.style.map(color_vote, subset=["Vote"])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=400)

    if keyword and display_df.empty:
        st.caption("No votes match that keyword.")
    elif keyword:
        st.caption(f"{len(display_df):,} of {total:,} votes shown.")

# ---------------------------------------------------------------------------
# Term history
# ---------------------------------------------------------------------------

st.divider()
with st.expander("Term history"):
    terms = selected.get("terms", [])
    if terms:
        term_df = pd.DataFrame(terms).rename(columns={
            "title":      "Title",
            "start_date": "Start",
            "end_date":   "End",
        })
        term_df["End"] = term_df["End"].fillna("Present")
        st.dataframe(term_df, use_container_width=True, hide_index=True)
    else:
        st.write("No term history available.")
