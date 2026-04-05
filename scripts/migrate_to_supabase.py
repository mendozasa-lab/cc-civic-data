"""
migrate_to_supabase.py — One-time migration from Airtable → Supabase
=====================================================================
Reads all 8 tables from Airtable using pyairtable, resolves linked
record IDs to integer foreign keys, and upserts into Supabase.

Usage:
    pip install pyairtable supabase python-dotenv
    python scripts/migrate_to_supabase.py

Credentials in .env:
    AIRTABLE_PAT=patXXXXXXXXXXXXX
    AIRTABLE_BASE_ID=appXXXXXXXXXXXXX
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY=eyJXXXXXX   (service role key — needed for writes)
"""

import os
import sys
from dotenv import load_dotenv
from pyairtable import Api
from supabase import create_client

load_dotenv()

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def get_airtable():
    pat = os.environ.get("AIRTABLE_API_KEY")
    base_id = os.environ.get("AIRTABLE_BASE_ID")
    if not pat or not base_id:
        sys.exit("Missing AIRTABLE_API_KEY or AIRTABLE_BASE_ID in .env")
    return Api(pat).base(base_id)

def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
    return create_client(url, key)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def linked_id(record, field, resolution_map):
    """Resolve a linked record field to an integer ID via a resolution map."""
    linked = record["fields"].get(field) or []
    if not linked:
        return None
    airtable_id = linked[0]["id"] if isinstance(linked[0], dict) else linked[0]
    return resolution_map.get(airtable_id)

def checkbox(record, field):
    """Return bool for a checkbox field (Airtable omits False values)."""
    return bool(record["fields"].get(field, False))

def field(record, name, default=None):
    """Safe field getter."""
    return record["fields"].get(name, default)

def upsert_batch(supabase, table_name, rows, batch_size=500, on_conflict=None):
    """Upsert rows into Supabase in batches."""
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        q = supabase.table(table_name).upsert(batch)
        if on_conflict:
            q = supabase.table(table_name).upsert(batch, on_conflict=on_conflict)
        q.execute()
        print(f"    {min(i + batch_size, total)} / {total}")
    print(f"  ✓ {table_name}: {total} records upserted")

# ---------------------------------------------------------------------------
# Phase 1 — Foundation tables (no FKs)
# ---------------------------------------------------------------------------

def migrate_bodies(airtable, supabase):
    print("\nBodies...")
    records = airtable.table("Bodies").all()
    resolution_map = {}  # airtable_record_id → body_id

    rows = []
    for r in records:
        body_id = field(r, "BodyId")
        if body_id is None:
            continue
        resolution_map[r["id"]] = int(body_id)
        rows.append({
            "body_id":            int(body_id),
            "body_name":          field(r, "BodyName"),
            "body_type":          field(r, "BodyType"),
            "body_description":   field(r, "BodyDescription"),
            "body_active_flag":   checkbox(r, "BodyActiveFlag"),
            "body_meet_day":      field(r, "BodyMeetDay"),
            "body_meet_time":     field(r, "BodyMeetTime"),
            "body_meet_location": field(r, "BodyMeetLocation"),
            "body_last_modified": field(r, "BodyLastModified"),
        })

    upsert_batch(supabase, "bodies", rows)
    return resolution_map

def migrate_persons(airtable, supabase):
    print("\nPersons...")
    records = airtable.table("Persons").all()
    resolution_map = {}

    rows = []
    for r in records:
        person_id = field(r, "PersonId")
        if person_id is None:
            continue
        resolution_map[r["id"]] = int(person_id)
        rows.append({
            "person_id":            int(person_id),
            "person_full_name":     field(r, "PersonFullName"),
            "person_first_name":    field(r, "PersonFirstName"),
            "person_last_name":     field(r, "PersonLastName"),
            "person_email":         field(r, "PersonEmail"),
            "person_phone":         field(r, "PersonPhone"),
            "person_active_flag":   checkbox(r, "PersonActiveFlag"),
            "person_last_modified": field(r, "PersonLastModified"),
        })

    upsert_batch(supabase, "persons", rows)
    return resolution_map

def migrate_matters(airtable, supabase):
    print("\nMatters...")
    records = airtable.table("Matters").all()
    resolution_map = {}

    rows = []
    for r in records:
        matter_id = field(r, "MatterId")
        if matter_id is None:
            continue
        resolution_map[r["id"]] = int(matter_id)
        rows.append({
            "matter_id":               int(matter_id),
            "matter_file":             field(r, "MatterFile"),
            "matter_name":             field(r, "MatterName"),
            "matter_title":            field(r, "MatterTitle"),
            "matter_type":             field(r, "MatterType"),
            "matter_status":           field(r, "MatterStatus"),
            "matter_body_name":        field(r, "MatterBodyName"),
            "matter_intro_date":       field(r, "MatterIntroDate"),
            "matter_agenda_date":      field(r, "MatterAgendaDate"),
            "matter_passed_date":      field(r, "MatterPassedDate"),
            "matter_enactment_number": field(r, "MatterEnactmentNumber"),
            "matter_last_modified":    field(r, "MatterLastModified"),
        })

    upsert_batch(supabase, "matters", rows)
    return resolution_map

# ---------------------------------------------------------------------------
# Phase 2 — Events (FK → Bodies)
# ---------------------------------------------------------------------------

def migrate_events(airtable, supabase, bodies_map):
    print("\nEvents...")
    records = airtable.table("Events").all()
    resolution_map = {}

    rows = []
    for r in records:
        event_id = field(r, "EventId")
        if event_id is None:
            continue
        resolution_map[r["id"]] = int(event_id)
        rows.append({
            "event_id":             int(event_id),
            "body_id":              linked_id(r, "Body", bodies_map),
            "event_date":           field(r, "EventDate"),
            "event_time":           field(r, "EventTime"),
            "event_location":       field(r, "EventLocation"),
            "event_agenda_status":  field(r, "EventAgendaStatus"),
            "event_minutes_status": field(r, "EventMinutesStatus"),
            "event_agenda_file":    field(r, "EventAgendaFile"),
            "event_minutes_file":   field(r, "EventMinutesFile"),
            "event_in_site_url":    field(r, "EventInSiteURL"),
            "event_video_path":     field(r, "EventVideoPath"),
            "event_media":          field(r, "EventMedia"),
            "event_last_modified":  field(r, "EventLastModified"),
        })

    upsert_batch(supabase, "events", rows)
    return resolution_map

# ---------------------------------------------------------------------------
# Phase 3 — Matter Attachments (FK → Matters)
# ---------------------------------------------------------------------------

def migrate_matter_attachments(airtable, supabase, matters_map):
    print("\nMatter Attachments...")
    records = airtable.table("Matter Attachments").all()

    rows = []
    for r in records:
        attachment_id = field(r, "AttachmentId")
        if attachment_id is None:
            continue
        rows.append({
            "attachment_id":            int(attachment_id),
            "matter_id":                linked_id(r, "Matter", matters_map),
            "attachment_name":          field(r, "AttachmentName"),
            "attachment_hyperlink":     field(r, "AttachmentHyperlink"),
            "attachment_is_supporting": checkbox(r, "AttachmentIsSupporting"),
            "attachment_last_modified": field(r, "AttachmentLastModified"),
        })

    upsert_batch(supabase, "matter_attachments", rows)

# ---------------------------------------------------------------------------
# Phase 4 — Event Items (FK → Events, Matters)
# ---------------------------------------------------------------------------

def migrate_event_items(airtable, supabase, events_map, matters_map):
    print("\nEvent Items...")
    records = airtable.table("Event Items").all()
    resolution_map = {}

    rows = []
    for r in records:
        event_item_id = field(r, "EventItemId")
        if event_item_id is None:
            continue
        resolution_map[r["id"]] = int(event_item_id)
        rows.append({
            "event_item_id":             int(event_item_id),
            "event_id":                  linked_id(r, "Event", events_map),
            "matter_id":                 linked_id(r, "Matter", matters_map),
            "event_item_title":          field(r, "EventItemTitle"),
            "event_item_agenda_number":  field(r, "EventItemAgendaNumber"),
            "event_item_action_name":    field(r, "EventItemActionName"),
            "event_item_result":         field(r, "EventItemResult"),
            "event_item_agenda_note":    field(r, "EventItemAgendaNote"),
            "event_item_minutes_note":   field(r, "EventItemMinutesNote"),
            "event_item_last_modified":  field(r, "EventItemLastModified"),
        })

    upsert_batch(supabase, "event_items", rows)
    return resolution_map

# ---------------------------------------------------------------------------
# Phase 5 ��� Votes (FK → Event Items, Persons)
# ---------------------------------------------------------------------------

def migrate_votes(airtable, supabase, event_items_map, persons_map):
    print("\nVotes...")
    records = airtable.table("Votes").all()

    rows = []
    unresolved_persons = 0
    for r in records:
        vote_id = field(r, "VoteId")
        if vote_id is None:
            continue
        person_id = linked_id(r, "Person", persons_map)
        if person_id is None:
            unresolved_persons += 1
        rows.append({
            "vote_id":            int(vote_id),
            "event_item_id":      linked_id(r, "Event Item", event_items_map),
            "person_id":          person_id,
            "vote_person_name":   field(r, "VotePersonName"),
            "vote_value_name":    field(r, "VoteValueName"),
            "vote_result":        field(r, "VoteResult"),
            "vote_last_modified": field(r, "VoteLastModified"),
        })

    # Composite PK: (vote_id, event_item_id) — must specify conflict target explicitly
    upsert_batch(supabase, "votes", rows, on_conflict="vote_id,event_item_id")
    if unresolved_persons:
        print(f"  Note: {unresolved_persons} votes had no Person link (VotePersonName used as fallback)")

# ---------------------------------------------------------------------------
# Phase 6 — Office Records (FK → Persons, Bodies)
# ---------------------------------------------------------------------------

def migrate_office_records(airtable, supabase, persons_map, bodies_map):
    print("\nOffice Records...")
    records = airtable.table("Office Records").all()

    rows = []
    for r in records:
        office_record_id = field(r, "OfficeRecordId")
        if office_record_id is None:
            continue
        rows.append({
            "office_record_id":            int(office_record_id),
            "person_id":                   linked_id(r, "Person", persons_map),
            "body_id":                     linked_id(r, "Body", bodies_map),
            "office_record_title":         field(r, "OfficeRecordTitle"),
            "office_record_start_date":    field(r, "OfficeRecordStartDate"),
            "office_record_end_date":      field(r, "OfficeRecordEndDate"),
            "office_record_member_type":   field(r, "OfficeRecordMemberType"),
            "office_record_last_modified": field(r, "OfficeRecordLastModified"),
        })

    upsert_batch(supabase, "office_records", rows)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Connecting to Airtable and Supabase...")
    airtable = get_airtable()
    supabase = get_supabase()
    print("Connected.")

    # Phase 1 — Foundation (build resolution maps for FK lookup)
    bodies_map  = migrate_bodies(airtable, supabase)
    persons_map = migrate_persons(airtable, supabase)
    matters_map = migrate_matters(airtable, supabase)

    # Phase 2
    events_map = migrate_events(airtable, supabase, bodies_map)

    # Phase 3
    migrate_matter_attachments(airtable, supabase, matters_map)

    # Phase 4
    event_items_map = migrate_event_items(airtable, supabase, events_map, matters_map)

    # Phase 5
    migrate_votes(airtable, supabase, event_items_map, persons_map)

    # Phase 6
    migrate_office_records(airtable, supabase, persons_map, bodies_map)

    print("\n✓ Migration complete.")

if __name__ == "__main__":
    main()
