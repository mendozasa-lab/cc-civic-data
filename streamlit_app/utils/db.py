"""
db.py — Supabase connection and query functions for the Streamlit app.

All data-loading functions are cached with a 1-hour TTL so Supabase is
only queried once per session, not on every user interaction.
"""

import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import date

# People who appear at council meetings but lack current office_records in Legistar.
# Mirror of NAMED_STAFF in scripts/transcription/auto_map_speakers.py — keep in sync.
NAMED_PERSONS = [
    {"person_id": 820,  "person_full_name": "Peter Zanoni",        "person_first_name": "Peter",    "person_last_name": "Zanoni",     "person_email": None, "current_title": "City Manager"},
    {"person_id": 628,  "person_full_name": "Esteban Ramos",       "person_first_name": "Esteban",  "person_last_name": "Ramos",      "person_email": None, "current_title": "Assistant Director of Water Supply Management"},
    {"person_id": 517,  "person_full_name": "Miles Risley",        "person_first_name": "Miles",    "person_last_name": "Risley",     "person_email": None, "current_title": "City Attorney"},
    {"person_id": 1332, "person_full_name": "Nicholas Winkelmann", "person_first_name": "Nicholas", "person_last_name": "Winkelmann", "person_email": None, "current_title": "Chief Operating Officer of CCW"},
    {"person_id": 1449, "person_full_name": "Kaylynn Paxson",      "person_first_name": "Kaylynn",  "person_last_name": "Paxson",     "person_email": None, "current_title": "Council Member"},
    {"person_id": 1448, "person_full_name": "Eric Cantu",          "person_first_name": "Eric",     "person_last_name": "Cantu",      "person_email": None, "current_title": "Council Member"},
]


@st.cache_resource
def get_client() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_ANON_KEY"],
    )


def fetch_all(query_fn, page_size=1000) -> list:
    """Paginate through a Supabase query until all records are returned."""
    all_data = []
    offset = 0
    while True:
        result = query_fn(offset, offset + page_size - 1).execute()
        all_data.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_data


@st.cache_data(ttl=3600)
def load_council_members() -> list[dict]:
    """
    Returns one dict per active council member or named staff/official.
    Active = office_record_end_date is null or >= today.
    Supplements with NAMED_PERSONS for people lacking office_records in Legistar.
    Sorted by last name.
    """
    client = get_client()
    today = date.today().isoformat()

    select_str = (
        "office_record_id, office_record_title, "
        "office_record_start_date, office_record_end_date, "
        "persons(person_id, person_full_name, person_first_name, person_last_name, person_email), "
        "bodies(body_name)"
    )
    data = fetch_all(
        lambda lo, hi: client.table("office_records").select(select_str).range(lo, hi)
    )

    # Filter to active City Council records only
    council_records = [
        r for r in data
        if r.get("bodies") and "city council" in (r["bodies"]["body_name"] or "").lower()
        and (r.get("office_record_end_date") is None or r["office_record_end_date"] >= today)
    ]

    # Group terms by person
    persons: dict[int, dict] = {}
    for r in council_records:
        p = r["persons"]
        if not p:
            continue
        pid = p["person_id"]
        if pid not in persons:
            persons[pid] = {
                "person_id":        pid,
                "person_full_name": p["person_full_name"],
                "person_first_name": p["person_first_name"],
                "person_last_name":  p["person_last_name"],
                "person_email":      p["person_email"],
                "terms": [],
            }
        persons[pid]["terms"].append({
            "title":      r["office_record_title"],
            "start_date": r["office_record_start_date"],
            "end_date":   r["office_record_end_date"],
        })

    # Determine current/latest title per person
    for p in persons.values():
        sorted_terms = sorted(
            p["terms"],
            key=lambda t: (t["end_date"] is None, t["start_date"] or ""),
            reverse=True,
        )
        p["current_title"] = sorted_terms[0]["title"] if sorted_terms else None
        p["current_start"]  = sorted_terms[0]["start_date"] if sorted_terms else None
        p["current_end"]    = sorted_terms[0]["end_date"] if sorted_terms else None

    # Append NAMED_PERSONS for people without current office_records
    for np in NAMED_PERSONS:
        if np["person_id"] not in persons:
            persons[np["person_id"]] = {**np, "terms": [], "current_start": None, "current_end": None}

    return sorted(persons.values(), key=lambda p: p["person_last_name"] or "")


@st.cache_data(ttl=3600)
def load_votes_for_person(person_id: int) -> pd.DataFrame:
    """
    Returns all votes for a council member, joined with event date and
    matter title. Returns an empty DataFrame if no votes found.
    """
    client = get_client()

    select_str = (
        "vote_value_name, vote_result, "
        "event_items("
        "  event_item_id, event_item_title, "
        "  events(event_date), "
        "  matters(matter_title, matter_file)"
        ")"
    )
    data = fetch_all(
        lambda lo, hi: client.table("votes").select(select_str).eq("person_id", person_id).range(lo, hi)
    )

    if not data:
        return pd.DataFrame()

    rows = []
    for v in data:
        ei = v.get("event_items") or {}
        event = ei.get("events") or {}
        matter = ei.get("matters") or {}
        rows.append({
            "Date":   event.get("event_date"),
            "Matter": matter.get("matter_title") or ei.get("event_item_title") or "—",
            "File":   matter.get("matter_file"),
            "Vote":   v.get("vote_value_name"),
            "Result": v.get("vote_result"),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=3600)
def load_segments_for_person(person_id: int) -> pd.DataFrame:
    """
    Returns all transcript segments for a council member (where person_id is mapped),
    joined with event date. Sorted newest first.
    """
    client = get_client()

    select_str = (
        "segment_id, event_id, speaker_label, start_time, end_time, segment_text, "
        "events(event_date, event_media)"
    )
    data = fetch_all(
        lambda lo, hi: client.table("transcript_segments")
        .select(select_str)
        .eq("person_id", person_id)
        .range(lo, hi)
    )

    if not data:
        return pd.DataFrame()

    rows = []
    for s in data:
        event = s.get("events") or {}
        rows.append({
            "segment_id":   s["segment_id"],
            "event_id":     s["event_id"],
            "clip_id":      event.get("event_media"),
            "Date":         event.get("event_date"),
            "start_time":   s["start_time"],
            "end_time":     s["end_time"],
            "Text":         s["segment_text"],
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=3600)
def load_events_with_transcripts() -> list[dict]:
    """
    Returns events that have a completed transcript, with event date and body name.
    Sorted newest first.
    """
    client = get_client()

    select_str = (
        "event_id, event_date, event_media, "
        "bodies(body_name), "
        "transcripts(transcript_id, status)"
    )
    data = fetch_all(
        lambda lo, hi: client.table("events").select(select_str).range(lo, hi)
    )

    results = []
    for e in data:
        t = e.get("transcripts")
        if not t or t.get("status") != "complete":
            continue
        body = e.get("bodies") or {}
        results.append({
            "event_id":      e["event_id"],
            "event_date":    e["event_date"],
            "body_name":     body.get("body_name", ""),
            "transcript_id": t["transcript_id"],
            "clip_id":       e.get("event_media"),
        })

    return sorted(results, key=lambda x: x["event_date"] or "", reverse=True)


@st.cache_data(ttl=3600)
def load_segments_for_event(event_id: int) -> pd.DataFrame:
    """
    Returns all transcript segments for a meeting, with person names where mapped.
    Sorted by start_time.
    """
    client = get_client()

    select_str = (
        "segment_id, speaker_label, start_time, end_time, segment_text, "
        "persons(person_full_name)"
    )
    data = fetch_all(
        lambda lo, hi: client.table("transcript_segments")
        .select(select_str)
        .eq("event_id", event_id)
        .order("start_time")
        .range(lo, hi)
    )

    if not data:
        return pd.DataFrame()

    rows = []
    for s in data:
        person = s.get("persons") or {}
        rows.append({
            "segment_id":    s["segment_id"],
            "start_time":    s["start_time"],
            "end_time":      s["end_time"],
            "Speaker":       person.get("person_full_name") or s["speaker_label"],
            "Text":          s["segment_text"],
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_meeting_summary(event_id: int) -> dict | None:
    """Returns meeting summary dict with summary_text, member_briefs, model, and generated_at, or None."""
    client = get_client()
    result = client.table("meeting_summaries").select("summary_text, member_briefs, model, generated_at").eq("event_id", event_id).execute()
    return result.data[0] if result.data else None


@st.cache_data(ttl=3600)
def load_member_summary(person_id: int) -> dict | None:
    """Returns rolling member summary dict with summary_text, quotes, model, and generated_at, or None."""
    client = get_client()
    result = client.table("member_summaries").select("summary_text, quotes, model, generated_at").eq("person_id", person_id).execute()
    return result.data[0] if result.data else None


@st.cache_data(ttl=3600)
def load_transcript_provenance(event_id: int) -> dict | None:
    """Returns transcript metadata for provenance display, or None."""
    client = get_client()
    result = (
        client.table("transcripts")
        .select("m3u8_url, duration_seconds, cost_usd, created_at, completed_at, source_doc_url, notebooklm_url")
        .eq("event_id", event_id)
        .execute()
    )
    if not result.data:
        return None
    data = result.data[0]
    event = client.table("events").select("event_media").eq("event_id", event_id).execute()
    if event.data:
        data["clip_id"] = event.data[0].get("event_media")
    return data


@st.cache_data(ttl=60)
def load_suggestions_for_transcript(transcript_id: int) -> list[dict]:
    """
    Returns all speaker mapping suggestions for a transcript, joined with person name.
    Short TTL so the Map Speakers page reflects approvals quickly.
    """
    client = get_client()
    result = (
        client.table("speaker_mapping_suggestions")
        .select("suggestion_id, speaker_label, person_id, confidence, category, reasoning, status, persons(person_full_name)")
        .eq("transcript_id", transcript_id)
        .order("confidence")  # high → low → medium (alphabetical, acceptable)
        .execute()
    )
    return result.data


@st.cache_data(ttl=3600)
def load_table_sample(table_name: str, limit: int = 50) -> pd.DataFrame:
    """Returns first `limit` rows of a table for display on the Transparency page."""
    client = get_client()
    result = client.table(table_name).select("*").limit(limit).execute()
    return pd.DataFrame(result.data)
