"""
map_speakers.py — Admin: review auto-mapping suggestions and map remaining speaker labels.

Password-gated. Requires ADMIN_PASSWORD and SUPABASE_SERVICE_KEY in secrets.toml.

Three sections:
  1. Pending suggestions — Claude's medium/low-confidence suggestions awaiting approval
  2. Auto-applied — high-confidence mappings already applied (expandable, can revoke)
  3. Manual mapping — any labels with no suggestion, with enhanced speaker profiles
"""

from collections import defaultdict

import streamlit as st
from supabase import create_client

from utils.db import (
    load_council_members,
    load_events_with_transcripts,
    load_suggestions_for_transcript,
)
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
# Write helpers
# ---------------------------------------------------------------------------

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


def update_suggestion_status(transcript_id: int, speaker_label: str, status: str) -> None:
    admin = get_admin_client()
    admin.table("speaker_mapping_suggestions") \
        .update({"status": status}) \
        .eq("transcript_id", transcript_id) \
        .eq("speaker_label", speaker_label) \
        .execute()
    st.cache_data.clear()


def approve_suggestion(transcript_id: int, suggestion: dict) -> None:
    person_id = suggestion.get("person_id")
    save_mapping(transcript_id, suggestion["speaker_label"], person_id)
    update_suggestion_status(transcript_id, suggestion["speaker_label"], "approved")


def reject_suggestion(transcript_id: int, suggestion: dict) -> None:
    update_suggestion_status(transcript_id, suggestion["speaker_label"], "rejected")


def revoke_auto_applied(transcript_id: int, suggestion: dict) -> None:
    save_mapping(transcript_id, suggestion["speaker_label"], None)
    update_suggestion_status(transcript_id, suggestion["speaker_label"], "rejected")

# ---------------------------------------------------------------------------
# Speaker profile helpers
# ---------------------------------------------------------------------------

def load_speaker_profile(transcript_id: int, speaker_label: str) -> dict:
    """Load stats and best utterances for a single speaker label."""
    admin = get_admin_client()
    segs = (
        admin.table("transcript_segments")
        .select("start_time, end_time, segment_text")
        .eq("transcript_id", transcript_id)
        .eq("speaker_label", speaker_label)
        .order("start_time")
        .execute()
        .data
    )
    if not segs:
        return {"segs": [], "stats": {}}

    total_time = sum(max(0, (s["end_time"] or 0) - (s["start_time"] or 0)) for s in segs)
    first_at = min(s["start_time"] or 0 for s in segs)
    last_at = max(s["start_time"] or 0 for s in segs)

    # Top 8 by length
    top_segs = sorted(segs, key=lambda s: len(s.get("segment_text", "")), reverse=True)[:8]

    return {
        "segs": top_segs,
        "stats": {
            "count": len(segs),
            "total_min": total_time / 60,
            "first_at": first_at,
            "last_at": last_at,
        },
    }


def fmt_time(secs: float) -> str:
    secs = int(secs or 0)
    return f"{secs // 3600}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def render_speaker_profile(label: str, profile: dict, clip_id: str | None,
                            transcript_id: int, current_name: str | None,
                            member_options: dict) -> None:
    stats = profile["stats"]
    status = f"→ {current_name}" if current_name else "unmapped"
    header = (
        f"**{label}** — {status} &nbsp;|&nbsp; "
        f"{stats.get('count', 0)} segments · "
        f"{stats.get('total_min', 0):.1f} min · "
        f"{fmt_time(stats.get('first_at', 0))}–{fmt_time(stats.get('last_at', 0))}"
    )
    with st.expander(header, expanded=(not current_name)):
        for s in profile["segs"]:
            link_html = time_cell(s["start_time"], clip_id)
            text = s["segment_text"][:400]
            st.markdown(
                f'<div style="margin-bottom:8px;font-size:13px;">{link_html} &nbsp; {text}</div>',
                unsafe_allow_html=True,
            )

        st.markdown("")
        none_opt = "— Not a council member / Skip —"
        options = [none_opt] + list(member_options.keys())
        default_idx = options.index(current_name) if current_name in options else 0
        chosen = st.selectbox("Assign to", options, index=default_idx, key=f"sel_{label}")
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

# Load segments to know which labels exist and which are mapped
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

# Build label → mapped name
groups: dict[str, list] = defaultdict(list)
current_mapping: dict[str, str] = {}
for s in segs:
    label = s["speaker_label"]
    groups[label].append(s)
    if s.get("person_id") and label not in current_mapping:
        name = (s.get("persons") or {}).get("person_full_name", "")
        if name:
            current_mapping[label] = name

all_labels = sorted(groups.keys())
mapped_labels = set(current_mapping.keys())

# Load suggestions
suggestions = load_suggestions_for_transcript(transcript_id)
suggestions_by_label = {s["speaker_label"]: s for s in suggestions}
suggested_labels = set(suggestions_by_label.keys())

pending_suggestions = [s for s in suggestions if s["status"] == "pending"]
auto_applied = [s for s in suggestions if s["status"] == "auto_applied"]
manual_labels = [l for l in all_labels if l not in suggested_labels and l not in mapped_labels]

# Status bar
n_unmapped = len([l for l in all_labels if l not in mapped_labels])
st.caption(
    f"{len(mapped_labels)} mapped · {n_unmapped} unmapped · "
    f"{len(pending_suggestions)} pending review · {len(manual_labels)} need manual mapping · "
    f"{len(all_labels)} total labels"
)

# ---------------------------------------------------------------------------
# Section 1: Pending suggestions
# ---------------------------------------------------------------------------

if pending_suggestions:
    st.subheader(f"Pending Review ({len(pending_suggestions)})")
    st.caption("Claude's suggestions awaiting your approval.")

    for sug in pending_suggestions:
        label = sug["speaker_label"]
        person_name = (sug.get("persons") or {}).get("person_full_name") or "—"
        confidence = sug.get("confidence", "?")
        category = sug.get("category", "?")
        reasoning = sug.get("reasoning", "")
        pid = sug.get("person_id")

        badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(confidence, "⚪")
        header = f"{badge} **{label}** → {person_name} ({category}, {confidence} confidence)"

        with st.expander(header, expanded=True):
            st.markdown(f"**Claude's reasoning:** {reasoning}")

            # Show a few sample utterances
            profile = load_speaker_profile(transcript_id, label)
            for s in profile["segs"][:3]:
                link_html = time_cell(s["start_time"], clip_id)
                st.markdown(
                    f'<div style="font-size:13px;margin-bottom:6px;">{link_html} &nbsp; {s["segment_text"][:300]}</div>',
                    unsafe_allow_html=True,
                )

            col1, col2, col3 = st.columns([1, 1, 4])
            with col1:
                if st.button("✓ Approve", key=f"approve_{label}"):
                    approve_suggestion(transcript_id, sug)
                    st.success(f"Approved: {label} → {person_name}")
                    st.rerun()
            with col2:
                if st.button("✗ Reject", key=f"reject_{label}"):
                    reject_suggestion(transcript_id, sug)
                    st.warning(f"Rejected: {label}")
                    st.rerun()

            st.markdown("**Or map to a different person:**")
            none_opt = "— Not a council member / Skip —"
            override_options = [none_opt] + list(member_options.keys())
            override_default = override_options.index(person_name) if person_name in override_options else 0
            chosen = st.selectbox("Assign to", override_options, index=override_default, key=f"override_{label}")
            if st.button("Save override", key=f"override_btn_{label}"):
                pid_override = member_options.get(chosen) if chosen != none_opt else None
                save_mapping(transcript_id, label, pid_override)
                update_suggestion_status(transcript_id, label, "approved")
                st.success(f"Saved: **{label}** → {chosen if chosen != none_opt else 'unmapped'}")
                st.rerun()

    st.divider()

# ---------------------------------------------------------------------------
# Section 2: Manual mapping (no suggestion exists)
# ---------------------------------------------------------------------------

if manual_labels:
    st.subheader(f"Manual Mapping ({len(manual_labels)})")
    st.caption("These labels have no auto-mapping suggestion. Review and assign manually.")

    for label in manual_labels:
        profile = load_speaker_profile(transcript_id, label)
        render_speaker_profile(
            label, profile, clip_id, transcript_id,
            current_mapping.get(label), member_options,
        )

    st.divider()

# ---------------------------------------------------------------------------
# Section 3: Auto-applied (transparency + revoke)
# ---------------------------------------------------------------------------

if auto_applied:
    with st.expander(f"Auto-applied ({len(auto_applied)} labels) — click to review or revoke"):
        for sug in auto_applied:
            label = sug["speaker_label"]
            person_name = (sug.get("persons") or {}).get("person_full_name") or "no person"
            pid = sug.get("person_id")
            reasoning = sug.get("reasoning", "")
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{label}** → {person_name} &nbsp; *{reasoning[:120]}*")
            with col2:
                if pid and st.button("Revoke", key=f"revoke_{label}"):
                    revoke_auto_applied(transcript_id, sug)
                    st.warning(f"Revoked: {label}")
                    st.rerun()

# ---------------------------------------------------------------------------
# Section 4: Already-mapped labels (can re-assign)
# ---------------------------------------------------------------------------

already_mapped_with_name = [l for l in all_labels if l in mapped_labels]
if already_mapped_with_name:
    with st.expander(f"Mapped ({len(already_mapped_with_name)} labels) — click to re-assign"):
        for label in already_mapped_with_name:
            profile = load_speaker_profile(transcript_id, label)
            render_speaker_profile(
                label, profile, clip_id, transcript_id,
                current_mapping.get(label), member_options,
            )
