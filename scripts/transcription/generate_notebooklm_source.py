"""
generate_notebooklm_source.py — Generate per-meeting Markdown source documents for NotebookLM.

Assembles meeting metadata, AI summary, agenda items, vote records, and the full
diarized transcript into a single Markdown file, uploads it to Cloudflare R2,
and saves the public URL to transcripts.source_doc_url.

The resulting URL can be pasted as a source in NotebookLM. Admins who create a
shared notebook can then store the share link in transcripts.notebooklm_url,
which the Streamlit app will display as an "Open in NotebookLM" button.

Usage:
    python generate_notebooklm_source.py --event-id 4220   # one meeting
    python generate_notebooklm_source.py                   # all missing
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from supabase_client import fetch_all, get_client

load_dotenv()

R2_PUBLIC_BASE = "https://pub-b1d9e555223a4dd3ae4aeea0d7570cc1.r2.dev"
R2_KEY_PREFIX = "notebooklm"

GRANICUS_PLAYER = "https://corpuschristi.granicus.com/player/clip/{clip_id}?view_id=2&redirect=true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_time(seconds) -> str:
    """Convert seconds (int or float) to HH:MM:SS string."""
    if seconds is None:
        return "00:00:00"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_event_data(client, event_id: int) -> dict:
    """
    Fetch all data needed to render the meeting source document.

    Returns a dict with keys:
      event, body_name, summary, segments, items, votes_by_item, attachments_by_matter
    """
    # Event + body name
    event_result = (
        client.table("events")
        .select("*, bodies(body_name)")
        .eq("event_id", event_id)
        .execute()
    )
    if not event_result.data:
        raise ValueError(f"Event {event_id} not found")
    event = event_result.data[0]
    body_name = (event.get("bodies") or {}).get("body_name", "")

    # Meeting summary (may not exist)
    summary_result = (
        client.table("meeting_summaries")
        .select("summary_text, member_briefs")
        .eq("event_id", event_id)
        .execute()
    )
    summary = summary_result.data[0] if summary_result.data else None

    # Transcript segments — use fetch_all (can exceed 1000 rows for long meetings)
    segments = fetch_all(
        client,
        "transcript_segments",
        query_fn=lambda: client.table("transcript_segments")
        .select("speaker_label, start_time, end_time, segment_text, persons(person_full_name)")
        .eq("event_id", event_id)
        .order("start_time"),
    )

    # Event items + matter info
    items = fetch_all(
        client,
        "event_items",
        query_fn=lambda: client.table("event_items")
        .select(
            "event_item_id, event_item_agenda_number, event_item_title, "
            "event_item_action_name, event_item_result, event_item_minutes_note, "
            "matter_id, matters(matter_title, matter_type, matter_status)"
        )
        .eq("event_id", event_id)
        .order("event_item_agenda_number"),
    )

    # Votes — batch fetch by event_item_id to avoid N+1 queries
    item_ids = [i["event_item_id"] for i in items]
    matter_ids = [i["matter_id"] for i in items if i.get("matter_id")]

    votes_by_item: dict[int, list] = {}
    if item_ids:
        all_votes = fetch_all(
            client,
            "votes",
            query_fn=lambda: client.table("votes")
            .select("event_item_id, vote_value_name, vote_result, vote_person_name, persons(person_full_name)")
            .in_("event_item_id", item_ids),
        )
        for v in all_votes:
            votes_by_item.setdefault(v["event_item_id"], []).append(v)

    # Attachments — batch fetch by matter_id
    attachments_by_matter: dict[int, list] = {}
    if matter_ids:
        all_attachments = fetch_all(
            client,
            "matter_attachments",
            query_fn=lambda: client.table("matter_attachments")
            .select("matter_id, attachment_name, attachment_hyperlink")
            .in_("matter_id", matter_ids),
        )
        for a in all_attachments:
            attachments_by_matter.setdefault(a["matter_id"], []).append(a)

    return {
        "event": event,
        "body_name": body_name,
        "summary": summary,
        "segments": segments,
        "items": items,
        "votes_by_item": votes_by_item,
        "attachments_by_matter": attachments_by_matter,
    }


# ---------------------------------------------------------------------------
# Markdown assembly
# ---------------------------------------------------------------------------

def build_markdown(event_data: dict) -> str:
    """
    Assemble a Markdown source document from the fetched meeting data.
    Pure function — no I/O.
    """
    event = event_data["event"]
    body_name = event_data["body_name"]
    summary = event_data["summary"] or {}
    segments = event_data["segments"]
    items = event_data["items"]
    votes_by_item = event_data["votes_by_item"]
    attachments_by_matter = event_data["attachments_by_matter"]

    event_date = event.get("event_date") or "Unknown date"
    clip_id = event.get("event_media")

    lines = []

    # ------- Header -------
    lines.append(f"# Corpus Christi City Council Meeting — {event_date}")
    lines.append("")
    lines.append(f"**Body:** {body_name or '—'}")
    lines.append(f"**Date:** {event_date}")
    lines.append(f"**Location:** {event.get('event_location') or '—'}")

    agenda_url = event.get("event_agenda_file")
    lines.append(f"**Agenda:** {agenda_url if agenda_url else 'Not available'}")

    minutes_url = event.get("event_minutes_file")
    lines.append(f"**Minutes:** {minutes_url if minutes_url else 'Not available'}")

    if clip_id:
        lines.append(f"**Source video:** {GRANICUS_PLAYER.format(clip_id=clip_id)}")

    legistar_url = event.get("event_in_site_url")
    if legistar_url:
        lines.append(f"**Legistar record:** {legistar_url}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ------- Meeting Overview -------
    summary_text = summary.get("summary_text")
    if summary_text:
        lines.append("## Meeting Overview")
        lines.append("")
        lines.append(summary_text)
        lines.append("")
        lines.append("---")
        lines.append("")

    # ------- Council Member Highlights -------
    member_briefs = summary.get("member_briefs") or {}
    if member_briefs:
        lines.append("## Council Member Highlights")
        lines.append("")
        for _pid, brief in member_briefs.items():
            name = brief.get("name") or "Unknown"
            lines.append(f"### {name}")
            lines.append("")
            member_summary = brief.get("summary") or ""
            if member_summary:
                lines.append(member_summary)
                lines.append("")
            quotes = brief.get("quotes") or []
            if quotes:
                lines.append("**Notable quotes:**")
                for q in quotes:
                    if isinstance(q, dict):
                        text = q.get("text") or ""
                        ts = fmt_time(q.get("start_time"))
                        lines.append(f'- "{text}" (at {ts})')
                    else:
                        lines.append(f'- "{q}"')
                lines.append("")
        lines.append("---")
        lines.append("")

    # ------- Agenda Items -------
    if items:
        lines.append("## Agenda Items")
        lines.append("")
        for item in items:
            agenda_num = item.get("event_item_agenda_number") or "—"
            title = item.get("event_item_title") or "Untitled item"
            lines.append(f"### Item {agenda_num}: {title}")
            lines.append("")

            action = item.get("event_item_action_name") or "—"
            result = item.get("event_item_result") or "—"
            lines.append(f"**Action:** {action}  **Result:** {result}")

            matter = item.get("matters") or {}
            if matter:
                m_title = matter.get("matter_title") or "—"
                m_type = matter.get("matter_type") or "—"
                m_status = matter.get("matter_status") or "—"
                lines.append(f"**Matter:** {m_title} ({m_type}, {m_status})")

            minutes_note = item.get("event_item_minutes_note") or "—"
            lines.append(f"**Notes:** {minutes_note}")

            # Attachments
            matter_id = item.get("matter_id")
            attachments = attachments_by_matter.get(matter_id, []) if matter_id else []
            if attachments:
                lines.append("")
                lines.append("**Supporting documents:**")
                for att in attachments:
                    att_name = att.get("attachment_name") or "Document"
                    att_url = att.get("attachment_hyperlink") or ""
                    if att_url:
                        lines.append(f"- [{att_name}]({att_url})")
                    else:
                        lines.append(f"- {att_name}")

            # Votes
            item_id = item["event_item_id"]
            votes = votes_by_item.get(item_id, [])
            if votes:
                lines.append("")
                lines.append("**Vote record:**")
                lines.append("")
                lines.append("| Council Member | Vote |")
                lines.append("|---|---|")
                for v in votes:
                    person_name = (
                        (v.get("persons") or {}).get("person_full_name")
                        or v.get("vote_person_name")
                        or "Unknown"
                    )
                    vote_val = v.get("vote_value_name") or "—"
                    lines.append(f"| {person_name} | {vote_val} |")
                # Show overall result if consistent across votes
                vote_results = {v.get("vote_result") for v in votes if v.get("vote_result")}
                if len(vote_results) == 1:
                    lines.append("")
                    lines.append(f"**Vote result:** {vote_results.pop()}")

            lines.append("")

        lines.append("---")
        lines.append("")

    # ------- Full Transcript -------
    if segments:
        lines.append("## Full Transcript")
        lines.append("")
        lines.append("*All speaker turns in order. Timestamps are HH:MM:SS from the start of the recording.*")
        lines.append("")
        for seg in segments:
            person_name = (seg.get("persons") or {}).get("person_full_name")
            speaker = person_name or seg.get("speaker_label") or "Unknown"
            ts = fmt_time(seg.get("start_time"))
            text = seg.get("segment_text") or ""
            lines.append(f"**[{ts}] {speaker}**")
            lines.append(text)
            lines.append("")

        lines.append("---")
        lines.append("")

    # ------- Footer -------
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines.append(
        f"*Generated {generated}. Source: Corpus Christi Legistar legislative records "
        f"and ElevenLabs Scribe v2 diarized transcription.*"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# R2 upload
# ---------------------------------------------------------------------------

def upload_to_r2(content: str, event_id: int) -> str:
    """Upload Markdown string to Cloudflare R2. Returns the public URL."""
    import boto3
    from botocore.config import Config

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET", "cc-civic-data")

    if not all([account_id, access_key, secret_key]):
        raise RuntimeError("R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY must be set")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    key = f"{R2_KEY_PREFIX}/event_{event_id}.md"
    encoded = content.encode("utf-8")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=encoded,
        ContentType="text/markdown; charset=utf-8",
    )
    url = f"{R2_PUBLIC_BASE}/{key}"
    print(f"  Uploaded to R2: {url}")
    return url


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate_for_event(client, event_id: int) -> None:
    """Generate and upload a NotebookLM source document for one event."""
    # Verify a complete transcript exists
    transcript_result = (
        client.table("transcripts")
        .select("transcript_id")
        .eq("event_id", event_id)
        .eq("status", "complete")
        .execute()
    )
    if not transcript_result.data:
        print(f"  No complete transcript for event_id={event_id} — skipping")
        return
    transcript_id = transcript_result.data[0]["transcript_id"]

    print(f"  Fetching data...")
    event_data = fetch_event_data(client, event_id)

    print(f"  Building Markdown document...")
    md = build_markdown(event_data)
    print(f"  Document size: {len(md):,} chars")

    print(f"  Uploading to R2...")
    url = upload_to_r2(md, event_id)

    client.table("transcripts").update({"source_doc_url": url}).eq("transcript_id", transcript_id).execute()
    print(f"  source_doc_url saved.")


def run(event_id: int | None = None) -> None:
    client = get_client()

    if event_id:
        print(f"Generating NotebookLM source for event_id={event_id}")
        generate_for_event(client, event_id)
        print("Done.")
    else:
        # Find all complete transcripts that don't have a source doc yet
        result = (
            client.table("transcripts")
            .select("event_id")
            .eq("status", "complete")
            .is_("source_doc_url", "null")
            .execute()
        )
        if not result.data:
            print("All transcribed meetings already have source documents.")
            return
        print(f"Generating source documents for {len(result.data)} meeting(s)...")
        for row in result.data:
            eid = row["event_id"]
            print(f"\nEvent {eid}:")
            try:
                generate_for_event(client, eid)
            except Exception as e:
                print(f"  Error: {e}")
        print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate NotebookLM source documents for council meetings."
    )
    parser.add_argument(
        "--event-id",
        type=int,
        help="Generate for a single event (omit to generate all missing)",
    )
    args = parser.parse_args()
    run(event_id=args.event_id)
