"""
map_speakers.py — Admin: map ElevenLabs speaker labels to council members.

Password-gated. Requires ADMIN_PASSWORD and SUPABASE_SERVICE_KEY in secrets.toml.
"""

from collections import defaultdict

import streamlit as st
from supabase import create_client

from utils.db import load_council_members, load_events_with_transcripts
from utils.render import TOOLTIP_CSS, time_cell

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

def check_password() -> bool:
    if st.session_state.get("admin_authenticated"):
        return True
    st.title("Speaker Mapping — Admin")
    pwd = st.text_input("Admin password", type="password")
    if st.button("Login"):
        if pwd == st.secrets.get("ADMIN_PASSWORD", ""):
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

if not check_password():
    st.stop()

# ---------------------------------------------------------------------------
# Admin Supabase client (service key — can write)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_admin_client():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_KEY"],
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pick_samples(segs: list, n: int = 3) -> list:
    """Pick n evenly-spaced segments from across the recording."""
    if len(segs) <= n:
        return segs
    step = len(segs) // n
    return [segs[i * step] for i in range(n)]


def save_mapping(transcript_id: int, speaker_label: str, person_id: int | None) -> None:
    admin = get_admin_client()
    if person_id:
        admin.table("speaker_mappings").upsert(
            {"transcript_id": transcript_id, "speaker_label": speaker_label, "person_id": person_id},
            on_conflict="transcript_id,speaker_label",
        ).execute()
    else:
        admin.table("speaker_mappings") \
            .delete() \
            .eq("transcript_id", transcript_id) \
            .eq("speaker_label", speaker_label) \
            .execute()
    admin.table("transcript_segments") \
        .update({"person_id": person_id}) \
        .eq("transcript_id", transcript_id) \
        .eq("speaker_label", speaker_label) \
        .execute()
    st.cache_data.clear()


def render_speaker_block(
    label: str,
    segs: list,
    clip_id: str | None,
    transcript_id: int,
    current_name: str | None,
    member_options: dict,
) -> None:
    status = f"→ {current_name}" if current_name else "unmapped"
    with st.expander(f"**{label}** — {status}", expanded=(not current_name)):
        # Sample utterances with video links
        for s in pick_samples(segs):
            link_html = time_cell(s["start_time"], clip_id)
            text = s["segment_text"][:200]
            st.markdown(
                f'<div style="margin-bottom:8px;font-size:14px;">{link_html} &nbsp; {text}</div>',
                unsafe_allow_html=True,
            )

        st.markdown("")

        none_opt = "— Not a council member / Skip —"
        options = [none_opt] + list(member_options.keys())
        default_idx = options.index(current_name) if current_name in options else 0

        chosen = st.selectbox(
            "Assign to",
            options,
            index=default_idx,
            key=f"sel_{label}",
        )
        if st.button("Save", key=f"btn_{label}"):
            pid = member_options.get(chosen) if chosen != none_opt else None
            save_mapping(transcript_id, label, pid)
            st.success(f"Saved: **{label}** → {chosen if chosen != none_opt else 'unmapped'}")
            st.rerun()

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Speaker Mapping")
st.markdown(TOOLTIP_CSS, unsafe_allow_html=True)

council_members = load_council_members()
member_options = {m["person_full_name"]: m["person_id"] for m in council_members}

transcripts = load_events_with_transcripts()
if not transcripts:
    st.info("No completed transcripts yet.")
    st.stop()

t_labels = [f"{t['event_date']} — {t['body_name']}" for t in transcripts]
chosen_label = st.selectbox("Select a transcript", t_labels)
selected = transcripts[t_labels.index(chosen_label)]
transcript_id = selected["transcript_id"]
clip_id = selected.get("clip_id")

st.divider()

# Load all segments for this transcript
admin = get_admin_client()
segs = (
    admin.table("transcript_segments")
    .select("speaker_label, start_time, segment_text, person_id, persons(person_full_name)")
    .eq("transcript_id", transcript_id)
    .order("start_time")
    .execute()
    .data
)

if not segs:
    st.info("No segments found for this transcript.")
    st.stop()

# Group by speaker label
groups: dict[str, list] = defaultdict(list)
current_mapping: dict[str, str] = {}  # label → person_full_name
for s in segs:
    label = s["speaker_label"]
    groups[label].append(s)
    if s.get("person_id") and label not in current_mapping:
        name = (s.get("persons") or {}).get("person_full_name", "")
        if name:
            current_mapping[label] = name

all_labels = sorted(groups.keys())
unmapped = [l for l in all_labels if l not in current_mapping]
mapped   = [l for l in all_labels if l in current_mapping]

st.caption(f"{len(unmapped)} unmapped · {len(mapped)} mapped · {len(all_labels)} total speakers")

if unmapped:
    st.subheader("Unmapped")
    for label in unmapped:
        render_speaker_block(label, groups[label], clip_id, transcript_id, None, member_options)

if mapped:
    st.subheader("Mapped")
    for label in mapped:
        render_speaker_block(label, groups[label], clip_id, transcript_id, current_mapping[label], member_options)
