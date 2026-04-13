"""sync_legistar.py — Sync Legistar data to Supabase.

Syncs all Legistar tables except bodies, persons, and office_records require no
date filter (full sync). Matters, events, matter_attachments, event_items, and
votes are scoped to the --since date forward, including future scheduled meetings
already in Legistar.

Usage:
  python sync_legistar.py                        # default: 14 days ago
  python sync_legistar.py --since 2026-04-08     # YYYY-MM-DD
  python sync_legistar.py --dry-run              # print counts, no writes

Tables synced (in order):
  1. bodies            — full sync
  2. persons           — full sync
  3. office_records    — full sync
  4. matters           — MatterLastModifiedUtc >= since; missing refs fetched on-demand
  5. events            — EventDate >= since
  6. event_items       — sub-resource per event
  7. matter_attachments — sub-resource per matter synced in step 4
  8. votes             — sub-resource per event_item
"""

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

from supabase_client import get_client, upsert_batch

LEGISTAR_BASE = "https://webapi.legistar.com/v1/corpuschristi"
PROGRESS_INTERVAL_ITEMS = 10
PROGRESS_INTERVAL_VOTES = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def empty_to_none(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def to_utc(ts):
    if not ts:
        return None
    s = str(ts)
    return s if s.endswith("Z") else s + "Z"


def to_date(ts):
    """Strip time portion from ISO 8601 datetime string."""
    if not ts:
        return None
    return str(ts).split("T")[0]


def fetch_legistar(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return []


def fetch_legistar_paginated(endpoint: str, filter_str: str = None) -> list:
    all_records = []
    skip = 0
    top = 1000
    while True:
        url = f"{LEGISTAR_BASE}/{endpoint}?$top={top}&$skip={skip}"
        if filter_str:
            url += f"&$filter={quote(filter_str)}"
        page = fetch_legistar(url)
        all_records.extend(page)
        if len(page) < top:
            break
        skip += top
    return all_records


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def transform_body(r: dict) -> dict:
    return {
        "body_id":            int(r["BodyId"]),
        "body_name":          empty_to_none(r.get("BodyName")),
        "body_type":          empty_to_none(r.get("BodyTypeName")),
        "body_description":   empty_to_none(r.get("BodyDescription")),
        "body_active_flag":   bool(r["BodyActiveFlag"]) if r.get("BodyActiveFlag") is not None else None,
        # BodyMeetDay / BodyMeetTime / BodyMeetLocation not returned by Legistar API
        "body_last_modified": to_utc(r.get("BodyLastModifiedUtc")),
    }


def transform_person(r: dict) -> dict:
    return {
        "person_id":           int(r["PersonId"]),
        "person_full_name":    empty_to_none(r.get("PersonFullName")),
        "person_first_name":   empty_to_none(r.get("PersonFirstName")),
        "person_last_name":    empty_to_none(r.get("PersonLastName")),
        "person_email":        empty_to_none(r.get("PersonEmail")),
        "person_phone":        empty_to_none(r.get("PersonPhone")),
        "person_active_flag":  bool(r["PersonActiveFlag"]) if r.get("PersonActiveFlag") is not None else None,
        "person_last_modified": to_utc(r.get("PersonLastModifiedUtc")),
    }


def transform_office_record(r: dict) -> dict:
    return {
        "office_record_id":           int(r["OfficeRecordId"]),
        "person_id":                  int(r["OfficeRecordPersonId"]) if r.get("OfficeRecordPersonId") else None,
        "body_id":                    int(r["OfficeRecordBodyId"]) if r.get("OfficeRecordBodyId") else None,
        "office_record_title":        empty_to_none(r.get("OfficeRecordTitle")),
        "office_record_start_date":   to_date(r.get("OfficeRecordStartDate")),
        "office_record_end_date":     to_date(r.get("OfficeRecordEndDate")),
        "office_record_member_type":  empty_to_none(r.get("OfficeRecordMemberType")),
        "office_record_last_modified": to_utc(r.get("OfficeRecordLastModifiedUtc")),
    }


def transform_matter(r: dict) -> dict:
    return {
        "matter_id":             int(r["MatterId"]),
        "matter_file":           empty_to_none(r.get("MatterFile")),
        "matter_name":           empty_to_none(r.get("MatterName")),
        "matter_title":          empty_to_none(r.get("MatterTitle")),
        "matter_type":           empty_to_none(r.get("MatterTypeName")),
        "matter_status":         empty_to_none(r.get("MatterStatusName")),
        "matter_body_name":      empty_to_none(r.get("MatterBodyName")),
        "matter_intro_date":     to_date(r.get("MatterIntroDate")),
        "matter_agenda_date":    to_date(r.get("MatterAgendaDate")),
        "matter_passed_date":    to_date(r.get("MatterPassedDate")),
        "matter_enactment_number": empty_to_none(r.get("MatterEnactmentNumber")),
        "matter_last_modified":  to_utc(r.get("MatterLastModifiedUtc")),
    }


def transform_event(r: dict) -> dict:
    return {
        "event_id":             int(r["EventId"]),
        "body_id":              int(r["EventBodyId"]) if r.get("EventBodyId") else None,
        "event_date":           to_date(r.get("EventDate")),
        "event_time":           empty_to_none(r.get("EventTime")),
        "event_location":       empty_to_none(r.get("EventLocation")),
        "event_agenda_status":  empty_to_none(r.get("EventAgendaStatusName")),
        "event_minutes_status": empty_to_none(r.get("EventMinutesStatusName")),
        "event_agenda_file":    empty_to_none(r.get("EventAgendaFile")),
        "event_minutes_file":   empty_to_none(r.get("EventMinutesFile")),
        "event_in_site_url":    empty_to_none(r.get("EventInSiteURL")),
        "event_video_path":     empty_to_none(r.get("EventVideoPath")),
        "event_media":          str(r["EventMedia"]) if r.get("EventMedia") else None,
        "event_last_modified":  to_utc(r.get("EventLastModifiedUtc")),
    }


def transform_event_item(r: dict, event_id: int) -> dict:
    return {
        "event_item_id":            int(r["EventItemId"]),
        "event_id":                 event_id,
        "matter_id":                int(r["EventItemMatterId"]) if r.get("EventItemMatterId") else None,
        "event_item_title":         empty_to_none(r.get("EventItemTitle")),
        "event_item_agenda_number": r.get("EventItemAgendaSequence"),
        "event_item_action_name":   empty_to_none(r.get("EventItemActionName")),
        "event_item_result":        empty_to_none(r.get("EventItemPassedFlagName")),
        "event_item_agenda_note":   empty_to_none(r.get("EventItemAgendaNote")),
        "event_item_minutes_note":  empty_to_none(r.get("EventItemMinutesNote")),
        "event_item_last_modified": to_utc(r.get("EventItemLastModifiedUtc")),
    }


def transform_attachment(r: dict, matter_id: int) -> dict:
    return {
        "attachment_id":           int(r["MatterAttachmentId"]),
        "matter_id":               matter_id,
        "attachment_name":         empty_to_none(r.get("MatterAttachmentName")),
        "attachment_hyperlink":    empty_to_none(r.get("MatterAttachmentHyperlink")),
        "attachment_is_supporting": bool(r["MatterAttachmentIsSupportingDocument"])
                                    if r.get("MatterAttachmentIsSupportingDocument") is not None else None,
        "attachment_last_modified": to_utc(r.get("MatterAttachmentLastModifiedUtc")),
    }


def transform_vote(r: dict, event_item_id: int) -> dict:
    raw_result = r.get("VoteResult")
    if raw_result == 1:
        vote_result = "Pass"
    elif raw_result == 0:
        vote_result = "Fail"
    else:
        vote_result = None

    return {
        "vote_id":            int(r["VoteId"]),
        "event_item_id":      event_item_id,
        "person_id":          int(r["VotePersonId"]) if r.get("VotePersonId") else None,
        "vote_person_name":   empty_to_none(r.get("VotePersonName")),
        "vote_value_name":    empty_to_none(r.get("VoteValueName")),
        "vote_result":        vote_result,
        "vote_last_modified": to_utc(r.get("VoteLastModifiedUtc")),
    }


# ---------------------------------------------------------------------------
# Sync functions
# ---------------------------------------------------------------------------

def sync_bodies(client, dry_run: bool) -> None:
    print("[bodies] Fetching all from Legistar (full sync)...")
    records = fetch_legistar_paginated("Bodies")
    print(f"[bodies] Found {len(records)} bodies.")
    rows = [transform_body(r) for r in records]
    if dry_run:
        print(f"[bodies] DRY RUN — would upsert {len(rows)} rows.")
    else:
        upsert_batch(client, "bodies", rows)
        print(f"[bodies] Upserted {len(rows)} rows.")


def sync_persons(client, dry_run: bool) -> None:
    print("[persons] Fetching all from Legistar (full sync)...")
    records = fetch_legistar_paginated("Persons")
    print(f"[persons] Found {len(records)} persons.")
    rows = [transform_person(r) for r in records]
    if dry_run:
        print(f"[persons] DRY RUN — would upsert {len(rows)} rows.")
    else:
        upsert_batch(client, "persons", rows)
        print(f"[persons] Upserted {len(rows)} rows.")


def sync_office_records(client, dry_run: bool) -> None:
    print("[office_records] Fetching all from Legistar (full sync)...")
    records = fetch_legistar_paginated("OfficeRecords")
    print(f"[office_records] Found {len(records)} office records.")
    rows = [transform_office_record(r) for r in records]
    if dry_run:
        print(f"[office_records] DRY RUN — would upsert {len(rows)} rows.")
    else:
        upsert_batch(client, "office_records", rows)
        print(f"[office_records] Upserted {len(rows)} rows.")


def sync_matters(client, since: str, dry_run: bool) -> list[int]:
    print(f"[matters] Fetching from Legistar (MatterLastModifiedUtc >= {since})...")
    filter_str = f"MatterLastModifiedUtc ge datetime'{since}T00:00:00'"
    records = fetch_legistar_paginated("Matters", filter_str)
    print(f"[matters] Found {len(records)} matters.")
    if not records:
        return []
    rows = [transform_matter(r) for r in records]
    if dry_run:
        print(f"[matters] DRY RUN — would upsert {len(rows)} rows.")
    else:
        upsert_batch(client, "matters", rows)
        print(f"[matters] Upserted {len(rows)} rows.")
    return [r["matter_id"] for r in rows]


def sync_events(client, since: str, dry_run: bool) -> list[int]:
    print(f"[events] Fetching from Legistar (EventDate >= {since})...")
    filter_str = f"EventDate ge datetime'{since}T00:00:00'"
    records = fetch_legistar_paginated("Events", filter_str)
    print(f"[events] Found {len(records)} events.")
    if not records:
        return []
    rows = [transform_event(r) for r in records]
    if dry_run:
        print(f"[events] DRY RUN — would upsert {len(rows)} rows.")
    else:
        upsert_batch(client, "events", rows)
        print(f"[events] Upserted {len(rows)} rows.")
    return [r["event_id"] for r in rows]


def sync_event_items(client, event_ids: list[int], dry_run: bool) -> list[int]:
    print(f"[event_items] Fetching items for {len(event_ids)} events...")
    all_rows = []
    errors = 0

    for i, eid in enumerate(event_ids):
        try:
            items = fetch_legistar(f"{LEGISTAR_BASE}/Events/{eid}/EventItems")
            for item in items:
                all_rows.append(transform_event_item(item, eid))
        except Exception as e:
            errors += 1
            print(f"[event_items]   Error fetching event {eid}: {e}")

        if (i + 1) % PROGRESS_INTERVAL_ITEMS == 0 or i + 1 == len(event_ids):
            print(f"[event_items]   {i + 1}/{len(event_ids)} events processed — {len(all_rows)} items so far.")

    print(f"[event_items] Found {len(all_rows)} items total. Errors: {errors}.")

    if not all_rows:
        return []

    # Fetch any matter_ids not yet in Supabase to avoid FK violations.
    # sync_matters covers recently modified matters; older matters referenced by
    # new agenda items may still be missing and need to be fetched individually.
    known_matters = {
        r["matter_id"]
        for r in client.table("matters").select("matter_id").execute().data
    }
    missing_ids = {
        row["matter_id"]
        for row in all_rows
        if row["matter_id"] is not None and row["matter_id"] not in known_matters
    }
    if missing_ids:
        print(f"[event_items]   {len(missing_ids)} referenced matter(s) not in Supabase — fetching from Legistar...")
        fetched = []
        for mid in missing_ids:
            try:
                data = fetch_legistar(f"{LEGISTAR_BASE}/Matters/{mid}")
                if data:
                    record = data if isinstance(data, dict) else data[0]
                    fetched.append(transform_matter(record))
            except Exception as e:
                print(f"[event_items]   Could not fetch matter {mid}: {e}")
        if fetched:
            if dry_run:
                print(f"[event_items]   DRY RUN — would upsert {len(fetched)} missing matter(s).")
            else:
                upsert_batch(client, "matters", fetched)
                print(f"[event_items]   Upserted {len(fetched)} missing matter(s).")

    if dry_run:
        print(f"[event_items] DRY RUN — would upsert {len(all_rows)} rows.")
    else:
        upsert_batch(client, "event_items", all_rows)
        print(f"[event_items] Upserted {len(all_rows)} rows.")

    return [r["event_item_id"] for r in all_rows]


def sync_matter_attachments(client, matter_ids: list[int], dry_run: bool) -> None:
    if not matter_ids:
        print("[matter_attachments] No matters to fetch attachments for — skipping.")
        return

    print(f"[matter_attachments] Fetching attachments for {len(matter_ids)} matters...")
    all_rows = []
    errors = 0

    for i, mid in enumerate(matter_ids):
        try:
            attachments = fetch_legistar(f"{LEGISTAR_BASE}/Matters/{mid}/Attachments")
            for att in attachments:
                all_rows.append(transform_attachment(att, mid))
        except Exception as e:
            errors += 1
            print(f"[matter_attachments]   Error fetching matter {mid}: {e}")

        if (i + 1) % PROGRESS_INTERVAL_ITEMS == 0 or i + 1 == len(matter_ids):
            print(f"[matter_attachments]   {i + 1}/{len(matter_ids)} matters processed — {len(all_rows)} attachments so far.")

    print(f"[matter_attachments] Found {len(all_rows)} attachments total. Errors: {errors}.")

    if not all_rows:
        return

    if dry_run:
        print(f"[matter_attachments] DRY RUN — would upsert {len(all_rows)} rows.")
    else:
        upsert_batch(client, "matter_attachments", all_rows)
        print(f"[matter_attachments] Upserted {len(all_rows)} rows.")


def sync_votes(client, event_item_ids: list[int], dry_run: bool) -> None:
    print(f"[votes] Fetching votes for {len(event_item_ids)} event items...")
    print("[votes]   Note: most items have no roll-call vote — [] is normal.")
    all_rows = []
    errors = 0

    for i, iid in enumerate(event_item_ids):
        try:
            votes = fetch_legistar(f"{LEGISTAR_BASE}/EventItems/{iid}/Votes")
            for vote in votes:
                all_rows.append(transform_vote(vote, iid))
        except Exception as e:
            errors += 1
            print(f"[votes]   Error fetching event_item {iid}: {e}")

        if (i + 1) % PROGRESS_INTERVAL_VOTES == 0 or i + 1 == len(event_item_ids):
            print(f"[votes]   {i + 1}/{len(event_item_ids)} items processed — {len(all_rows)} votes so far.")

    print(f"[votes] Found {len(all_rows)} votes total. Errors: {errors}.")

    if not all_rows:
        return

    if dry_run:
        print(f"[votes] DRY RUN — would upsert {len(all_rows)} rows.")
    else:
        upsert_batch(client, "votes", all_rows, on_conflict="vote_id,event_item_id")
        print(f"[votes] Upserted {len(all_rows)} rows.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync Legistar data to Supabase.")
    parser.add_argument(
        "--since",
        default=None,
        help="Start date YYYY-MM-DD (default: 14 days ago). Pulls events/matters from this date "
             "forward, including future scheduled meetings already in Legistar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing to Supabase.",
    )
    args = parser.parse_args()

    since = args.since or (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")

    print(f"Legistar sync — since={since}, dry_run={args.dry_run}")
    print()

    client = get_client()

    # Full syncs first (no date dependency)
    sync_bodies(client, args.dry_run)
    print()
    sync_persons(client, args.dry_run)
    print()
    sync_office_records(client, args.dry_run)
    print()

    # Date-filtered syncs
    matter_ids = sync_matters(client, since, args.dry_run)
    print()

    event_ids = sync_events(client, since, args.dry_run)
    print()

    if not event_ids:
        print("No events found — skipping event_items, matter_attachments, and votes.")
        sys.exit(0)

    event_item_ids = sync_event_items(client, event_ids, args.dry_run)
    print()

    sync_matter_attachments(client, matter_ids, args.dry_run)
    print()

    if not event_item_ids:
        print("No event items found — skipping votes.")
        sys.exit(0)

    sync_votes(client, event_item_ids, args.dry_run)
    print()
    print("Done.")


if __name__ == "__main__":
    main()
