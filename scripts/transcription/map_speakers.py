"""
map_speakers.py — Interactively map speaker labels to Person records.

Usage:
    python map_speakers.py --transcript-id 42
"""

import argparse
import sys

from supabase_client import get_client


def show_samples(client, transcript_id: int, speaker_label: str, n: int = 3) -> None:
    result = (
        client.table("transcript_segments")
        .select("start_time, segment_text")
        .eq("transcript_id", transcript_id)
        .eq("speaker_label", speaker_label)
        .limit(n)
        .execute()
    )
    for seg in result.data:
        mins = int(seg["start_time"] // 60)
        secs = int(seg["start_time"] % 60)
        preview = seg["segment_text"][:120].replace("\n", " ")
        print(f"    [{mins:02d}:{secs:02d}] {preview}")


def run(transcript_id: int) -> None:
    client = get_client()

    # Verify transcript exists
    t = client.table("transcripts").select("transcript_id, event_id, status").eq("transcript_id", transcript_id).execute()
    if not t.data:
        sys.exit(f"No transcript found with id={transcript_id}")
    transcript = t.data[0]
    print(f"Transcript {transcript_id} | event_id={transcript['event_id']} | status={transcript['status']}\n")

    # Get distinct speaker labels
    result = (
        client.table("transcript_segments")
        .select("speaker_label")
        .eq("transcript_id", transcript_id)
        .execute()
    )
    labels = sorted({r["speaker_label"] for r in result.data})
    if not labels:
        sys.exit("No segments found for this transcript.")

    print(f"Found {len(labels)} speaker label(s): {', '.join(labels)}\n")

    # Load already-mapped labels
    existing = client.table("speaker_mappings").select("speaker_label, person_id").eq("transcript_id", transcript_id).execute()
    already_mapped = {r["speaker_label"]: r["person_id"] for r in existing.data}

    for label in labels:
        if label in already_mapped:
            print(f"{label}: already mapped to person_id={already_mapped[label]} (skipping)")
            continue

        print(f"\n--- {label} ---")
        print("  Sample utterances:")
        show_samples(client, transcript_id, label)

        while True:
            raw = input(f"  Map {label} to person_id (or 's' to skip): ").strip()
            if raw.lower() == "s":
                print(f"  Skipped {label}")
                break
            if raw.isdigit():
                person_id = int(raw)
                # Verify person exists
                p = client.table("persons").select("person_id, person_full_name").eq("person_id", person_id).execute()
                if not p.data:
                    print(f"  No person found with id={person_id}. Try again.")
                    continue
                name = p.data[0]["person_full_name"]
                confirm = input(f"  Confirm: map {label} → {name} (person_id={person_id})? [y/n]: ").strip().lower()
                if confirm == "y":
                    # Upsert speaker mapping
                    client.table("speaker_mappings").upsert(
                        {"transcript_id": transcript_id, "speaker_label": label, "person_id": person_id},
                        on_conflict="transcript_id,speaker_label",
                    ).execute()
                    # Update segments
                    client.table("transcript_segments").update({"person_id": person_id}).eq(
                        "transcript_id", transcript_id
                    ).eq("speaker_label", label).execute()
                    print(f"  Mapped {label} → {name}")
                    break
            else:
                print("  Enter a numeric person_id or 's' to skip.")

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Map speaker labels to Person records.")
    parser.add_argument("--transcript-id", type=int, required=True, help="Transcript ID to map")
    args = parser.parse_args()
    run(transcript_id=args.transcript_id)
