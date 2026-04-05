"""
db.py — Supabase connection and query functions for the Streamlit app.

All data-loading functions are cached with a 1-hour TTL so Supabase is
only queried once per session, not on every user interaction.
"""

import streamlit as st
from supabase import create_client, Client
import pandas as pd


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
    Returns one dict per person who has ever held a council office.
    Includes all their office record terms and their current/latest title.
    Sorted by last name.
    """
    client = get_client()

    select_str = (
        "office_record_id, office_record_title, "
        "office_record_start_date, office_record_end_date, "
        "persons(person_id, person_full_name, person_first_name, person_last_name, person_email), "
        "bodies(body_name)"
    )
    data = fetch_all(
        lambda lo, hi: client.table("office_records").select(select_str).range(lo, hi)
    )

    # Filter to City Council records only
    council_records = [
        r for r in data
        if r.get("bodies") and "city council" in (r["bodies"]["body_name"] or "").lower()
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
                "person_id":       pid,
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
        # Sort terms: current (no end date) first, then most recent
        sorted_terms = sorted(
            p["terms"],
            key=lambda t: (t["end_date"] is None, t["start_date"] or ""),
            reverse=True,
        )
        p["current_title"] = sorted_terms[0]["title"] if sorted_terms else None
        p["current_start"]  = sorted_terms[0]["start_date"] if sorted_terms else None
        p["current_end"]    = sorted_terms[0]["end_date"] if sorted_terms else None

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
