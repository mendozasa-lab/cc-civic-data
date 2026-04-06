"""
Persons — council member profiles with voting records and transcript statements.
"""

import streamlit as st
import plotly.express as px
import pandas as pd

from utils.db import load_council_members, load_votes_for_person, load_segments_for_person, load_member_summary

st.markdown("""
<style>
.cc-tooltip {
    position: relative;
    display: inline-block;
    border-bottom: 1px dotted #888;
    cursor: help;
    color: #888;
    font-size: 0.85em;
}
.cc-tooltip .cc-tooltiptext {
    visibility: hidden;
    width: 300px;
    background-color: #333;
    color: #fff;
    text-align: left;
    padding: 8px 10px;
    border-radius: 6px;
    position: absolute;
    z-index: 9999;
    bottom: 130%;
    left: 50%;
    margin-left: -150px;
    opacity: 0;
    transition: opacity 0.2s;
    font-size: 12px;
    line-height: 1.6;
    pointer-events: none;
    white-space: normal;
}
.cc-tooltip:hover .cc-tooltiptext {
    visibility: visible;
    opacity: 1;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar — council member picker
# ---------------------------------------------------------------------------

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
# Rolling AI summary
# ---------------------------------------------------------------------------

member_summary = load_member_summary(selected["person_id"])
if member_summary:
    with st.expander("About " + selected["person_full_name"], expanded=True):
        st.write(member_summary["summary_text"])
        quotes = member_summary.get("quotes") or []
        if quotes:
            st.markdown("**Representative quotes:**")
            for q in quotes:
                date = q.get("event_date", "")
                st.markdown(f"> {q['text']}")
                if date:
                    st.caption(date)

    model = member_summary.get("model") or "claude-opus-4-6"
    generated = (member_summary.get("generated_at") or "")[:10]
    tooltip_lines = (
        f"<b>Model:</b> {model}<br>"
        + (f"<b>Generated:</b> {generated}<br>" if generated else "")
        + "<b>Inputs:</b> All speaker-attributed segments for this member · max 80k chars<br>"
        + "<b>Speaker labels:</b> Assigned manually per recording"
    )
    st.markdown(
        f'<span class="cc-tooltip">Learn how this was generated.'
        f'<span class="cc-tooltiptext">{tooltip_lines}</span></span>',
        unsafe_allow_html=True,
    )

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
    show_df["Matter"] = show_df["Matter"].str[:80]

    styled = show_df.style.map(color_vote, subset=["Vote"])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=400)

    if keyword and display_df.empty:
        st.caption("No votes match that keyword.")
    elif keyword:
        st.caption(f"{len(display_df):,} of {total:,} votes shown.")

# ---------------------------------------------------------------------------
# Statements (transcript segments)
# ---------------------------------------------------------------------------

st.divider()
with st.expander("Statements"):
    segments_df = load_segments_for_person(selected["person_id"])
    if segments_df.empty:
        st.info("No transcript data available for this council member yet.")
    else:
        keyword = st.text_input("Filter statements by keyword", placeholder="e.g. budget, zoning...", key="seg_keyword")
        display_segs = segments_df.copy()
        if keyword:
            mask = display_segs["Text"].str.contains(keyword, case=False, na=False)
            display_segs = display_segs[mask]

        if display_segs.empty:
            st.caption("No statements match that keyword.")
        else:
            show_segs = display_segs[["Date", "Text", "event_id"]].copy()
            show_segs["Date"] = show_segs["Date"].dt.strftime("%Y-%m-%d")
            show_segs["Text"] = show_segs["Text"].str[:200]
            show_segs = show_segs.rename(columns={"event_id": "Meeting ID"})
            st.dataframe(show_segs, use_container_width=True, hide_index=True, height=350)
            if keyword:
                st.caption(f"{len(display_segs):,} of {len(segments_df):,} statements shown.")

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
