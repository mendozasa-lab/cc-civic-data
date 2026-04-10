"""
import_entities.py — Pull entities from ElevenLabs and insert into transcript_entities.

Used when the crash-recovery path (--elevenlabs-id) was used and entities were skipped.
Fetches the stored transcription result, maps char offsets to segment_ids using the
already-inserted segments, and inserts into transcript_entities.

Usage:
    python import_entities.py --event-id 4111
    python import_entities.py --event-id 4111 --elevenlabs-id mK9OUZsMvaU7IdlOZ6G5
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

from supabase_client import get_client, fetch_all

load_dotenv()

ELEVENLABS_GET_URL = "https://api.elevenlabs.io/v1/speech-to-text/transcripts/{transcription_id}"


def find_segment_for_entity(segments, segment_ids, start_char, end_char):
    """Return segment_id whose char range contains the entity. Falls back to best overlap."""
    for i, seg in enumerate(segments):
        if start_char >= seg["char_start"] and end_char <= seg["char_end"]:
            return segment_ids[i]
    # Fallback: most overlap
    best_id = None
    best_overlap = 0
    for i, seg in enumerate(segments):
        overlap = min(end_char, seg["char_end"]) - max(start_char, seg["char_start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_id = segment_ids[i]
    return best_id


def build_char_offsets(db_segments):
    """Reconstruct char_start/char_end for each segment, matching the Edge Function logic.

    The webhook joins segments with a newline between them (+1 char per segment).
    db_segments must be ordered by start_time.
    Returns list of dicts with segment_id, char_start, char_end.
    """
    enriched = []
    char_offset = 0
    for seg in db_segments:
        text = seg["segment_text"]
        char_start = char_offset
        char_end = char_offset + len(text)
        enriched.append({
            "segment_id": seg["segment_id"],
            "char_start": char_start,
            "char_end": char_end,
        })
        char_offset += len(text) + 1  # +1 for newline between segments
    return enriched


def main():
    parser = argparse.ArgumentParser(description="Import ElevenLabs entities into Supabase")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--elevenlabs-id", type=str, default=None,
                        help="ElevenLabs transcription ID (looked up from DB if not provided)")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("Error: ELEVENLABS_API_KEY must be set in .env")

    client = get_client()

    # Look up transcript record
    result = client.table("transcripts").select(
        "transcript_id, event_id, elevenlabs_transcription_id, status"
    ).eq("event_id", args.event_id).single().execute()

    if not result.data:
        sys.exit(f"No transcript found for event_id={args.event_id}")

    transcript = result.data
    tid = transcript["transcript_id"]
    eid = transcript["event_id"]
    el_id = args.elevenlabs_id or transcript.get("elevenlabs_transcription_id")

    if not el_id:
        sys.exit(f"No elevenlabs_transcription_id on record for event_id={eid}. Pass --elevenlabs-id.")

    print(f"transcript_id={tid} event_id={eid} elevenlabs_id={el_id}")

    # Check for existing entities
    existing = client.table("transcript_entities").select("entity_id", count="exact").eq(
        "transcript_id", tid
    ).execute()
    if existing.count and existing.count > 0:
        print(f"Already have {existing.count} entities for this transcript. Aborting to avoid duplicates.")
        print("To re-import, delete existing entities first:")
        print(f"  DELETE FROM transcript_entities WHERE transcript_id = {tid};")
        sys.exit(0)

    # Fetch transcription from ElevenLabs
    print(f"Fetching transcription from ElevenLabs...")
    resp = requests.get(
        ELEVENLABS_GET_URL.format(transcription_id=el_id),
        headers={"xi-api-key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    entities = data.get("entities") or []
    print(f"Found {len(entities)} entities in ElevenLabs response")

    if not entities:
        print("No entities to import.")
        sys.exit(0)

    # Fetch segments from Supabase, ordered by start_time
    print(f"Fetching segments from Supabase...")
    db_segments = fetch_all(
        client,
        "transcript_segments",
        query_fn=lambda: client.table("transcript_segments")
            .select("segment_id, segment_text, start_time")
            .eq("transcript_id", tid)
            .order("start_time"),
    )
    print(f"Found {len(db_segments)} segments")

    if not db_segments:
        sys.exit(f"No segments found for transcript_id={tid}. Run crash recovery first.")

    # Build char offset map
    enriched_segs = build_char_offsets(db_segments)
    segment_ids = [s["segment_id"] for s in enriched_segs]

    # Map entities to segments and build rows
    rows = []
    for e in entities:
        start_char = e.get("start_char", 0)
        end_char = e.get("end_char", 0)
        seg_id = find_segment_for_entity(enriched_segs, segment_ids, start_char, end_char)
        rows.append({
            "transcript_id": tid,
            "event_id": eid,
            "segment_id": seg_id,
            "entity_text": e.get("text", ""),
            "entity_type": e.get("entity_type", ""),
            "start_char": start_char,
            "end_char": end_char,
        })

    # Insert in batches
    print(f"Inserting {len(rows)} entities...")
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        client.table("transcript_entities").insert(batch).execute()
        print(f"  Inserted {min(i + batch_size, len(rows))}/{len(rows)}")

    print("Done.")


if __name__ == "__main__":
    main()
