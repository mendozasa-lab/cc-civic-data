"""
Meetings — browse meeting transcripts, filter by speaker and keyword.
"""

import streamlit as st

from utils.db import load_events_with_transcripts, load_segments_for_event, load_meeting_summary, load_transcript_provenance
from utils.render import TOOLTIP_CSS, render_transcript_table, granicus_quote_link

st.title("Meetings & Transcripts")
st.markdown("Browse council meeting transcripts. Select a meeting to see who said what.")

st.markdown(TOOLTIP_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Load meetings that have completed transcripts
# ---------------------------------------------------------------------------

with st.spinner("Loading meetings..."):
    meetings = load_events_with_transcripts()

if not meetings:
    st.info("No transcripts available yet. Run the transcription pipeline to get started.")
    st.stop()

# ---------------------------------------------------------------------------
# Meeting selector (sidebar)
# ---------------------------------------------------------------------------

def meeting_label(m: dict) -> str:
    date = m["event_date"] or "Unknown date"
    body = m["body_name"] or "Meeting"
    return f"{date} — {body}"

labels = [meeting_label(m) for m in meetings]
selected_label = st.sidebar.selectbox("Select a meeting", labels)
selected_meeting = meetings[labels.index(selected_label)]

st.divider()

# ---------------------------------------------------------------------------
# Meeting summary
# ---------------------------------------------------------------------------

summary = load_meeting_summary(selected_meeting["event_id"])
provenance = load_transcript_provenance(selected_meeting["event_id"])
clip_id = selected_meeting.get("clip_id") or (provenance or {}).get("clip_id")
if summary:
    st.subheader("Meeting Summary")
    st.write(summary["summary_text"])

    member_briefs = summary.get("member_briefs") or {}
    if member_briefs:
        with st.expander("Council Member Perspectives"):
            for person_id_str, brief in member_briefs.items():
                st.markdown(f"**{brief.get('name', 'Unknown')}**")
                st.write(brief.get("summary", ""))
                for quote in brief.get("quotes", []):
                    if isinstance(quote, dict):
                        text = quote.get("text", "")
                        link = granicus_quote_link(clip_id, quote.get("start_time"))
                        st.markdown(f"> {text}", unsafe_allow_html=False)
                        if link:
                            st.markdown(link, unsafe_allow_html=True)
                    else:
                        st.markdown(f"> {quote}")
                st.divider()

    if summary.get("model"):
        generated = (summary.get("generated_at") or "")[:10]
        duration_str = ""
        processed_str = ""
        if provenance:
            if provenance.get("duration_seconds"):
                duration_str = f"{int(provenance['duration_seconds'] // 60)} min of audio · "
            if provenance.get("completed_at"):
                processed_str = f"Processed {provenance['completed_at'][:10]} · "
        tooltip_lines = (
            f"<b>Model:</b> {summary['model']}<br>"
            + (f"<b>Generated:</b> {generated}<br>" if generated else "")
            + f"<b>Transcript:</b> {duration_str}{processed_str}ElevenLabs Scribe v2<br>"
            + "<b>Inputs:</b> Speaker-attributed segments only · max 80k chars<br>"
            + "<b>Speaker labels:</b> Assigned manually"
        )
        st.markdown(
            f'<span class="cc-tooltip">Learn how this was generated.'
            f'<span class="cc-tooltiptext">{tooltip_lines}</span></span>',
            unsafe_allow_html=True,
        )

    st.divider()

# ---------------------------------------------------------------------------
# Load segments for selected meeting
# ---------------------------------------------------------------------------

with st.spinner("Loading transcript..."):
    segments_df = load_segments_for_event(selected_meeting["event_id"])

if segments_df.empty:
    st.info("No transcript segments found for this meeting.")
    st.stop()

total = len(segments_df)
speakers = sorted(segments_df["Speaker"].unique())

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

col_kw, col_sp = st.columns([2, 1])
with col_kw:
    keyword = st.text_input("Filter by keyword", placeholder="e.g. budget, zoning, water...")
with col_sp:
    speaker_options = ["All speakers"] + speakers
    selected_speaker = st.selectbox("Filter by speaker", speaker_options)

display_df = segments_df.copy()
if keyword:
    display_df = display_df[display_df["Text"].str.contains(keyword, case=False, na=False)]
if selected_speaker != "All speakers":
    display_df = display_df[display_df["Speaker"] == selected_speaker]

st.caption(
    f"Showing {len(display_df):,} of {total:,} segments  ·  {len(speakers)} speaker(s)"
)

# ---------------------------------------------------------------------------
# Transcript table
# ---------------------------------------------------------------------------

render_transcript_table(display_df[["start_time", "Speaker", "Text"]], clip_id=clip_id)
