"""
summarize.py — Generate AI summaries of meetings and council member records.

Uses Claude to produce:
  1. A per-meeting summary with an overview and per-member briefs + quotes
  2. A rolling per-member summary across all transcribed meetings

Called automatically at the end of transcribe.py, or standalone:

Usage:
    python summarize.py --event-id 4220     # meeting + member summaries for one event
    python summarize.py --person-id 123     # regenerate rolling summary for one person
    python summarize.py                     # generate all missing meeting summaries
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from supabase_client import get_client

load_dotenv()

MODEL = "claude-opus-4-6"


def get_anthropic_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Error: ANTHROPIC_API_KEY must be set in .env")
    return anthropic.Anthropic(api_key=key)


# ---------------------------------------------------------------------------
# Meeting summary
# ---------------------------------------------------------------------------

MEETING_PROMPT = """\
You are summarizing a Corpus Christi City Council meeting for the general public.

Meeting date: {event_date}

Transcript (Time | Speaker | Statement):
{transcript}

Write a structured summary. Respond ONLY with valid JSON in exactly this structure:
{{
  "overview": "2-3 sentence overview of what was discussed and decided at this meeting",
  "members": {{
    "<person_id as string>": {{
      "name": "Full name",
      "summary": "2-4 sentences describing what this council member focused on and their positions",
      "quotes": [
        {{"text": "direct verbatim quote", "start_time": 323}},
        {{"text": "direct verbatim quote", "start_time": 1205}},
        {{"text": "direct verbatim quote", "start_time": 2847}}
      ]
    }}
  }}
}}

Rules:
- Include only council members who actually spoke (exclude City Manager, City Attorney, staff, public commenters)
- Quotes must be verbatim from the transcript
- start_time is the integer number of seconds from the beginning of the recording (convert MM:SS from the transcript — e.g. 05:23 → 323)
- Keep the overview factual and neutral
- Do not include any text outside the JSON
"""


def format_transcript_for_prompt(segments: list, max_chars: int = 80000) -> str:
    """Format segments as Time | Speaker | Statement, truncated to fit context."""
    lines = []
    for s in segments:
        mins = int(s["start_time"] // 60)
        secs = int(s["start_time"] % 60)
        speaker = s.get("persons", {}).get("person_full_name") or s["speaker_label"]
        lines.append(f"{mins:02d}:{secs:02d} | {speaker} | {s['segment_text']}")
    full = "\n".join(lines)
    if len(full) > max_chars:
        full = full[:max_chars] + "\n[transcript truncated]"
    return full


def generate_meeting_summary(event_id: int) -> None:
    client = get_client()
    ai = get_anthropic_client()

    # Load event date
    event = client.table("events").select("event_date").eq("event_id", event_id).execute()
    if not event.data:
        print(f"  No event found for event_id={event_id}")
        return
    event_date = event.data[0]["event_date"] or "Unknown"

    # Load transcript record
    transcript = client.table("transcripts").select("transcript_id").eq("event_id", event_id).eq("status", "complete").execute()
    if not transcript.data:
        print(f"  No complete transcript found for event_id={event_id}")
        return
    transcript_id = transcript.data[0]["transcript_id"]

    # Load segments with person names (only mapped speakers)
    segments = client.table("transcript_segments") \
        .select("start_time, speaker_label, segment_text, persons(person_id, person_full_name)") \
        .eq("event_id", event_id) \
        .not_.is_("person_id", "null") \
        .order("start_time") \
        .execute().data

    if not segments:
        print(f"  No mapped segments for event_id={event_id} — run map_speakers.py first")
        return

    print(f"  Generating meeting summary ({len(segments)} mapped segments)...")
    transcript_text = format_transcript_for_prompt(segments)

    response = ai.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": MEETING_PROMPT.format(event_date=event_date, transcript=transcript_text),
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  Failed to parse Claude response as JSON: {e}")
        print(f"  Raw response: {raw[:500]}")
        return

    client.table("meeting_summaries").upsert({
        "transcript_id": transcript_id,
        "event_id": event_id,
        "summary_text": parsed.get("overview", ""),
        "member_briefs": parsed.get("members", {}),
        "model": MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="transcript_id").execute()

    print(f"  Meeting summary saved. Members covered: {len(parsed.get('members', {}))}")

    # Generate rolling summaries for each person who spoke in this meeting
    person_ids = list({s["persons"]["person_id"] for s in segments if s.get("persons")})
    for person_id in person_ids:
        generate_member_summary(person_id)


# ---------------------------------------------------------------------------
# Rolling member summary
# ---------------------------------------------------------------------------

MEMBER_PROMPT = """\
You are summarizing a Corpus Christi City Council member's record across multiple meetings.

Council member: {person_name}
Statements across {n_meetings} meeting(s) (Date | event_id | Time | Statement):
{statements}

Write a summary of this council member's record. Respond ONLY with valid JSON in exactly this structure:
{{
  "summary": "3-5 sentences describing what issues this council member consistently focuses on, their general positions and values, and any notable patterns in how they engage",
  "quotes": [
    {{"text": "verbatim quote", "event_id": 123, "event_date": "YYYY-MM-DD", "start_time": 323}},
    {{"text": "verbatim quote", "event_id": 124, "event_date": "YYYY-MM-DD", "start_time": 1205}},
    {{"text": "verbatim quote", "event_id": 125, "event_date": "YYYY-MM-DD", "start_time": 2847}}
  ]
}}

Rules:
- Choose 3-5 quotes that best illustrate their record and positions
- Quotes must be verbatim from the statements provided
- start_time is the integer number of seconds from the beginning of the recording (convert MM:SS from the statement line — e.g. 05:23 → 323)
- event_id and event_date must match the statement line the quote came from
- The summary should be factual, neutral, and based only on the statements provided
- Do not include any text outside the JSON
"""


def generate_member_summary(person_id: int) -> None:
    client = get_client()
    ai = get_anthropic_client()

    # Load person name
    person = client.table("persons").select("person_full_name").eq("person_id", person_id).execute()
    if not person.data:
        print(f"  No person found for person_id={person_id}")
        return
    person_name = person.data[0]["person_full_name"]

    # Load all mapped segments for this person, with event dates and clip IDs
    segments = client.table("transcript_segments") \
        .select("segment_text, event_id, start_time, events(event_date, event_media)") \
        .eq("person_id", person_id) \
        .order("event_id") \
        .execute().data

    if not segments:
        print(f"  No segments for {person_name} (person_id={person_id})")
        return

    # Build clip_id lookup from loaded segments
    clip_id_map = {
        s["event_id"]: (s.get("events") or {}).get("event_media")
        for s in segments
    }

    # Group by event for context, build statement list with timestamps
    lines = []
    event_ids = sorted({s["event_id"] for s in segments})
    for seg in segments:
        event = seg.get("events") or {}
        date = event.get("event_date", "Unknown")
        mins = int(seg["start_time"] // 60)
        secs = int(seg["start_time"] % 60)
        lines.append(f"{date} | event_id:{seg['event_id']} | {mins:02d}:{secs:02d} | {seg['segment_text']}")

    statements_text = "\n".join(lines)
    if len(statements_text) > 80000:
        statements_text = statements_text[:80000] + "\n[truncated]"

    print(f"  Generating rolling summary for {person_name} ({len(segments)} segments, {len(event_ids)} meeting(s))...")

    response = ai.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": MEMBER_PROMPT.format(
                person_name=person_name,
                n_meetings=len(event_ids),
                statements=statements_text,
            ),
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  Failed to parse Claude response as JSON: {e}")
        print(f"  Raw response: {raw[:500]}")
        return

    # Enrich quotes with clip_id for video deep-links
    quotes = parsed.get("quotes", [])
    for q in quotes:
        eid = q.get("event_id")
        if eid:
            q["clip_id"] = clip_id_map.get(eid)

    client.table("member_summaries").upsert({
        "person_id": person_id,
        "summary_text": parsed.get("summary", ""),
        "quotes": quotes,
        "model": MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="person_id").execute()

    print(f"  Rolling summary saved for {person_name}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(event_id: int | None = None, person_id: int | None = None) -> None:
    client = get_client()

    if event_id:
        generate_meeting_summary(event_id)
    elif person_id:
        generate_member_summary(person_id)
    else:
        # All events with complete transcripts but no meeting summary yet
        transcripts = client.table("transcripts").select("event_id").eq("status", "complete").execute().data
        existing = {r["event_id"] for r in client.table("meeting_summaries").select("event_id").execute().data}
        pending = [t["event_id"] for t in transcripts if t["event_id"] not in existing]
        if not pending:
            print("All transcribed meetings already have summaries.")
            return
        print(f"Generating summaries for {len(pending)} meeting(s)...")
        for eid in pending:
            print(f"\nEvent {eid}:")
            generate_meeting_summary(eid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate AI summaries of meetings and council members.")
    parser.add_argument("--event-id", type=int, help="Generate meeting + member summaries for one event")
    parser.add_argument("--person-id", type=int, help="Regenerate rolling summary for one person")
    args = parser.parse_args()
    run(event_id=args.event_id, person_id=args.person_id)
