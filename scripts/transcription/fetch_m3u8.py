"""
fetch_m3u8.py — Scrape Granicus player pages and create transcript records.

Usage:
    python fetch_m3u8.py                  # all events with event_media, skips existing
    python fetch_m3u8.py --event-id 1234  # single event
"""

import argparse
import re
import sys
import time

import requests

from supabase_client import get_client, upsert_batch

PLAYER_URL = "https://corpuschristi.granicus.com/player/clip/{clip_id}?view_id=2&redirect=true"
M3U8_RE = re.compile(r'video_url="(https://archive-stream\.granicus\.com/[^"]+\.m3u8)"')


def fetch_m3u8_url(clip_id: str) -> str | None:
    """Scrape the Granicus player page and extract the M3U8 URL."""
    url = PLAYER_URL.format(clip_id=clip_id)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  HTTP error for clip {clip_id}: {e}")
        return None
    match = M3U8_RE.search(resp.text)
    if not match:
        print(f"  No M3U8 URL found in page for clip {clip_id}")
        return None
    return match.group(1)


def run(event_id: int | None = None) -> None:
    client = get_client()

    # Load events with event_media set
    if event_id:
        result = client.table("events").select("event_id, event_media").eq("event_id", event_id).execute()
    else:
        result = client.table("events").select("event_id, event_media").not_.is_("event_media", "null").execute()

    events = result.data
    if not events:
        print("No matching events found.")
        return

    # Load already-processed event IDs to skip
    existing = client.table("transcripts").select("event_id").execute()
    existing_ids = {r["event_id"] for r in existing.data}

    to_process = [e for e in events if e["event_id"] not in existing_ids]
    print(f"{len(events)} events with media, {len(existing_ids)} already have transcripts, {len(to_process)} to process")

    records = []
    for i, event in enumerate(to_process, 1):
        eid = event["event_id"]
        clip_id = event["event_media"]
        print(f"[{i}/{len(to_process)}] event_id={eid} clip_id={clip_id} ... ", end="", flush=True)
        m3u8 = fetch_m3u8_url(clip_id)
        if m3u8:
            print(f"OK")
            records.append({"event_id": eid, "m3u8_url": m3u8, "status": "pending"})
        else:
            print(f"SKIP")
        time.sleep(0.5)  # be polite to Granicus

    if records:
        upsert_batch(client, "transcripts", records, on_conflict="event_id")
        print(f"\nCreated {len(records)} transcript records.")
    else:
        print("\nNothing to insert.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Granicus M3U8 URLs and create transcript records.")
    parser.add_argument("--event-id", type=int, help="Process a single event by ID")
    args = parser.parse_args()
    run(event_id=args.event_id)
