"""
auto_map_speakers.py — Use Claude to automatically identify speaker labels in a transcript.

Runs after transcription completes (called from transcribe.py or standalone).
Applies high-confidence mappings immediately; stores medium/low suggestions in
speaker_mapping_suggestions for review in the Streamlit Map Speakers admin page.

Usage:
    python auto_map_speakers.py --transcript-id 42
    python auto_map_speakers.py --transcript-id 42 --dry-run
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

import anthropic
from dotenv import load_dotenv

from supabase_client import get_client, fetch_all

load_dotenv()

MODEL = "claude-opus-4-6"
ROLL_CALL_WINDOW = 600   # first 10 minutes
TOP_UTTERANCES = 5       # longest segments to send per speaker label

# Key recurring staff who may not have current office_records in Legistar.
# Add person_id + title here when they're a consistent presence at council meetings.
NAMED_STAFF = [
    {"person_id": 820, "person_full_name": "Peter Zanoni", "title": "City Manager"},
    {"person_id": 628, "person_full_name": "Esteban Ramos", "title": "Assistant Director of Water Supply Management"},
    {"person_id": 517, "person_full_name": "Miles Risley", "title": "City Attorney"},
    {"person_id": 1332, "person_full_name": "Nicholas Winkelmann", "title": "Chief Operating Officer of CCW"},
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_transcript(client, transcript_id: int | None = None, event_id: int | None = None) -> dict:
    q = client.table("transcripts").select("transcript_id, event_id, events(event_date)")
    if transcript_id:
        q = q.eq("transcript_id", transcript_id)
    elif event_id:
        q = q.eq("event_id", event_id)
    else:
        sys.exit("Error: must provide transcript_id or event_id")
    result = q.execute()
    if not result.data:
        ref = f"event_id={event_id}" if event_id else f"transcript_id={transcript_id}"
        sys.exit(f"Transcript not found for {ref}.")
    t = result.data[0]
    t["event_date"] = (t.get("events") or {}).get("event_date", "")
    return t


def load_segments(client, transcript_id: int) -> list:
    return fetch_all(
        client,
        "transcript_segments",
        query_fn=lambda: client.table("transcript_segments")
            .select("speaker_label, start_time, end_time, segment_text")
            .eq("transcript_id", transcript_id)
            .order("start_time"),
    )


STAFF_TITLES = {"City Manager", "City Secretary", "City Attorney"}


def load_roster(client, event_date: str) -> tuple[list, list]:
    """Load council members and key named staff active on the event date.

    Returns (council_members, staff_members) — both lists have the same shape:
    {person_id, person_full_name, person_first_name, person_last_name, title}
    """
    data = fetch_all(
        client,
        "office_records",
        query_fn=lambda: client.table("office_records")
            .select(
                "office_record_title, office_record_start_date, office_record_end_date, "
                "persons(person_id, person_full_name, person_first_name, person_last_name), "
                "bodies(body_name)"
            ),
    )

    council = {}
    staff = {}
    for r in data:
        body = (r.get("bodies") or {}).get("body_name", "")
        title = r.get("office_record_title") or ""
        p = r.get("persons")
        if not p:
            continue
        start = r.get("office_record_start_date") or ""
        end = r.get("office_record_end_date")
        if start > event_date:
            continue
        if end and end < event_date:
            continue
        pid = p["person_id"]
        entry = {
            "person_id": pid,
            "person_full_name": p["person_full_name"],
            "person_first_name": p["person_first_name"],
            "person_last_name": p["person_last_name"],
            "title": title,
        }
        if "city council" in body.lower():
            if pid not in council:
                council[pid] = entry
        elif title in STAFF_TITLES:
            if pid not in staff:
                staff[pid] = entry

    # Merge hardcoded named staff (may not have current office_records in Legistar)
    for s in NAMED_STAFF:
        pid = s["person_id"]
        if pid not in staff and pid not in council:
            staff[pid] = {
                "person_id": pid,
                "person_full_name": s["person_full_name"],
                "person_first_name": s["person_full_name"].split()[0],
                "person_last_name": s["person_full_name"].split()[-1],
                "title": s["title"],
            }

    return list(council.values()), list(staff.values())


def load_existing_mappings(client, transcript_id: int) -> set:
    """Returns set of speaker_labels already mapped."""
    result = client.table("speaker_mappings") \
        .select("speaker_label") \
        .eq("transcript_id", transcript_id) \
        .execute()
    return {r["speaker_label"] for r in result.data}


def load_existing_suggestions(client, transcript_id: int) -> set:
    """Returns set of speaker_labels already in suggestions table."""
    result = client.table("speaker_mapping_suggestions") \
        .select("speaker_label") \
        .eq("transcript_id", transcript_id) \
        .execute()
    return {r["speaker_label"] for r in result.data}


# ---------------------------------------------------------------------------
# Per-label statistics and name evidence
# ---------------------------------------------------------------------------

def compute_label_stats(segments: list) -> dict:
    """Returns per-label stats dict."""
    stats = defaultdict(lambda: {
        "segment_count": 0,
        "total_time": 0.0,
        "first_at": None,
        "last_at": None,
        "segments": [],
    })
    for s in segments:
        label = s["speaker_label"]
        duration = (s["end_time"] or 0) - (s["start_time"] or 0)
        st = stats[label]
        st["segment_count"] += 1
        st["total_time"] += max(0, duration)
        t = s["start_time"] or 0
        if st["first_at"] is None or t < st["first_at"]:
            st["first_at"] = t
        if st["last_at"] is None or t > st["last_at"]:
            st["last_at"] = t
        st["segments"].append(s)
    return dict(stats)


def compute_flags(stats: dict, meeting_duration: float) -> dict:
    """Add descriptive flags to each label's stats."""
    for label, st in stats.items():
        flags = []
        if st["total_time"] < 180:
            flags.append("short_time (<3 min total — may be a split of another label or public commenter)")
        if st["last_at"] is not None and st["last_at"] < 1800:
            flags.append("early_only (last appearance in first 30 min — typical of public commenters)")
        if meeting_duration > 0 and st["last_at"] is not None:
            active_span = st["last_at"] - (st["first_at"] or 0)
            if active_span > meeting_duration * 0.5:
                flags.append("throughout (active across >50% of meeting — strong council member signal)")
        st["flags"] = flags
    return stats


def detect_name_evidence(segments: list, roster: list, staff: list) -> dict:
    """
    Scan all segments for name mentions and self-introductions.
    Returns {speaker_label: {self_intro, addressed_as, roll_call}}
    """
    # Build name patterns from roster + staff
    name_patterns = []
    for m in roster + staff:
        first = m.get("person_first_name") or ""
        last = m.get("person_last_name") or ""
        full = m.get("person_full_name") or ""
        pid = m["person_id"]
        if last:
            name_patterns.append((pid, full, re.compile(
                r'\b' + re.escape(last) + r'\b', re.IGNORECASE
            )))

    self_intro_re = re.compile(
        r'\bmy name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)', re.IGNORECASE
    )
    roll_call_re = re.compile(r'\b(present|here)\b', re.IGNORECASE)
    address_prefixes = re.compile(
        r'\b(council\s*member|councilmember|mayor|commissioner|thank\s+you,?\s*(?:council\s*member|mayor)?)\s+([A-Z][a-z]+)',
        re.IGNORECASE
    )

    evidence = defaultdict(lambda: {"self_intro": [], "addressed_as": [], "roll_call": False})

    for s in segments:
        label = s["speaker_label"]
        text = s["segment_text"]
        t = s["start_time"] or 0

        # Self-introduction
        m = self_intro_re.search(text)
        if m:
            evidence[label]["self_intro"].append(m.group(0))

        # Roll call (first 10 minutes, short response)
        if t < ROLL_CALL_WINDOW and roll_call_re.search(text) and len(text.split()) < 10:
            evidence[label]["roll_call"] = True

        # Direct address using roster names (check OTHER speakers addressing this label's
        # neighbors — we look at all segments for name mentions)
        for pid, full_name, pat in name_patterns:
            if pat.search(text):
                evidence[label]["addressed_as"].append(
                    {"text": text[:200], "person_id": pid, "person_name": full_name}
                )

        # Address prefix patterns (e.g., "Thank you, Council Member Garcia")
        for match in address_prefixes.finditer(text):
            evidence[label]["addressed_as"].append({"text": match.group(0)[:200]})

    return dict(evidence)


def pick_top_utterances(segs: list, n: int = TOP_UTTERANCES) -> list:
    """Return the n longest segments."""
    sorted_segs = sorted(segs, key=lambda s: len(s.get("segment_text", "")), reverse=True)
    return sorted_segs[:n]


# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

def build_prompt(stats: dict, evidence: dict, roster: list, staff: list, event_date: str) -> str:
    roster_lines = "\n".join(
        f"  person_id={m['person_id']} | {m['person_full_name']} | {m['title']}"
        for m in sorted(roster, key=lambda m: m.get("person_last_name") or "")
    )
    staff_lines = "\n".join(
        f"  person_id={m['person_id']} | {m['person_full_name']} | {m['title']}"
        for m in sorted(staff, key=lambda m: m.get("person_last_name") or "")
    ) if staff else "  (none on record)"

    speaker_blocks = []
    for label in sorted(stats.keys()):
        st = stats[label]
        ev = evidence.get(label, {})

        flags_str = ", ".join(st.get("flags", [])) or "none"
        first_fmt = f"{int(st['first_at'] or 0) // 60}:{int(st['first_at'] or 0) % 60:02d}"
        last_fmt = f"{int(st['last_at'] or 0) // 60}:{int(st['last_at'] or 0) % 60:02d}"

        top_segs = pick_top_utterances(st["segments"])
        utterances = "\n".join(
            f"    [{int(s['start_time'] or 0) // 60}:{int(s['start_time'] or 0) % 60:02d}] {s['segment_text'][:400]}"
            for s in top_segs
        )

        self_intro_str = "; ".join(ev.get("self_intro", [])) or "none"
        roll_call_str = "YES — responded during roll call window" if ev.get("roll_call") else "no"

        addressed = ev.get("addressed_as", [])
        addressed_str = "\n".join(
            f"    {a.get('text', '')}" + (f" [→ person_id={a['person_id']}]" if "person_id" in a else "")
            for a in addressed[:5]
        ) or "    none"

        speaker_blocks.append(f"""
--- {label} ---
Stats: {st['segment_count']} segments, {st['total_time']:.0f}s total, active {first_fmt}–{last_fmt}
Flags: {flags_str}
Self-introduction: {self_intro_str}
Roll call response: {roll_call_str}
Name mentions in speech (roster names or address patterns):
{addressed_str}
Longest utterances:
{utterances}""")

    speakers_str = "\n".join(speaker_blocks)

    return f"""You are analyzing a Corpus Christi City Council meeting transcript ({event_date}) to identify who each speaker label belongs to.

COUNCIL ROSTER (elected members — use these person_ids):
{roster_lines}

KEY NAMED STAFF (also identifiable — use these person_ids):
{staff_lines}

OTHER STAFF who commonly speak but are NOT in the roster above:
  - City Attorney (if not listed above)
  - Other department heads, directors, consultants

SPEAKER PROFILES:
{speakers_str}

TASK:
For each speaker label, call the submit_speaker_mappings tool with your identifications.

Rules:
- person_id: use the integer from the council roster OR the key named staff list above; null for unlisted staff/public/unknown
- confidence:
    "high" = direct name evidence (self-introduction, named by another speaker, roll call response match)
    "medium" = role inference (makes motions/seconds, votes, prolonged engagement throughout the full meeting)
    "low" = weak signal only (speaking style, general patterns)
- category: "council" | "staff" | "public" | "unknown"
- Named staff (City Manager, City Secretary, etc.) should be treated the same as council members — assign their person_id and use "high" confidence when there is direct name evidence
- For labels with the "short_time" flag: consider whether this could be a voice split from another council member label (ElevenLabs sometimes assigns the same person two labels)
- Public commenters typically: appear only in a concentrated window, speak once for 2-5 minutes, never make motions
- The City Secretary often: calls roll (reads names, gets "present"/"here" responses), announces vote tallies, reads agenda item titles
- Do not guess — if evidence is insufficient, use confidence "low" and category "unknown"
"""


# ---------------------------------------------------------------------------
# Apply mappings
# ---------------------------------------------------------------------------

def apply_mapping(client, transcript_id: int, speaker_label: str, person_id: int) -> None:
    client.table("speaker_mappings").upsert(
        {"transcript_id": transcript_id, "speaker_label": speaker_label, "person_id": person_id},
        on_conflict="transcript_id,speaker_label",
    ).execute()
    client.table("transcript_segments") \
        .update({"person_id": person_id}) \
        .eq("transcript_id", transcript_id) \
        .eq("speaker_label", speaker_label) \
        .execute()


def store_suggestion(client, transcript_id: int, mapping: dict, status: str) -> None:
    client.table("speaker_mapping_suggestions").upsert(
        {
            "transcript_id": transcript_id,
            "speaker_label": mapping["speaker_label"],
            "person_id": mapping.get("person_id"),
            "confidence": mapping["confidence"],
            "category": mapping["category"],
            "reasoning": mapping.get("reasoning", ""),
            "status": status,
        },
        on_conflict="transcript_id,speaker_label",
    ).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def auto_map_transcript(transcript_id: int | None = None, event_id: int | None = None, dry_run: bool = False) -> None:
    client = get_client()

    transcript = load_transcript(client, transcript_id=transcript_id, event_id=event_id)
    transcript_id = transcript["transcript_id"]
    event_id = transcript["event_id"]
    event_date = transcript["event_date"]
    print(f"Auto-mapping transcript_id={transcript_id} event_id={event_id} ({event_date})")

    segments = load_segments(client, transcript_id)
    if not segments:
        print("  No segments found — skipping.")
        return

    roster, staff = load_roster(client, event_date)
    print(f"  Roster: {len(roster)} active council members, {len(staff)} named staff")

    already_mapped = load_existing_mappings(client, transcript_id)
    already_suggested = load_existing_suggestions(client, transcript_id)
    skip_labels = already_mapped | already_suggested

    stats = compute_label_stats(segments)
    meeting_duration = max((st["last_at"] or 0) for st in stats.values())
    stats = compute_flags(stats, meeting_duration)

    # Filter to only unmapped/unsuggested labels
    labels_to_process = {k: v for k, v in stats.items() if k not in skip_labels}
    if not labels_to_process:
        print("  All labels already mapped or suggested — nothing to do.")
        return

    print(f"  Processing {len(labels_to_process)} labels ({len(skip_labels)} already handled)")

    evidence = detect_name_evidence(segments, roster, staff)

    # Call Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY must be set in .env")
    claude = anthropic.Anthropic(api_key=api_key)

    # Build prompt with only the labels we're processing
    filtered_stats = {k: v for k, v in stats.items() if k in labels_to_process}
    prompt = build_prompt(filtered_stats, evidence, roster, staff, event_date)

    mapping_tool = {
        "name": "submit_speaker_mappings",
        "description": "Submit identified speaker label to person mappings",
        "input_schema": {
            "type": "object",
            "properties": {
                "mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker_label": {"type": "string"},
                            "person_id": {"type": ["integer", "null"]},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "category": {"type": "string", "enum": ["council", "staff", "public", "unknown"]},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["speaker_label", "confidence", "category", "reasoning"],
                    },
                }
            },
            "required": ["mappings"],
        },
    }

    # Pre-filter: labels with BOTH short_time AND early_only are almost certainly
    # public commenters — auto-store them as unknown without calling Claude.
    definite_public = {}
    claude_labels = {}
    for label, st in labels_to_process.items():
        flags = st.get("flags", [])
        has_short = any("short_time" in f for f in flags)
        has_early = any("early_only" in f for f in flags)
        if has_short and has_early:
            definite_public[label] = st
        else:
            claude_labels[label] = st

    print(f"  Pre-filtered {len(definite_public)} likely-public labels (short + early_only)")
    print(f"  Sending {len(claude_labels)} labels to Claude")

    # Auto-store definite public without calling Claude
    if not dry_run:
        for label in definite_public:
            store_suggestion(client, transcript_id, {
                "speaker_label": label,
                "person_id": None,
                "confidence": "low",
                "category": "public",
                "reasoning": "Pre-filtered: short speaking time + only appeared early in meeting",
            }, status="auto_applied")

    # Batch Claude calls: 30 labels per call
    BATCH_SIZE = 30
    all_mappings = []
    claude_label_list = list(claude_labels.keys())
    for batch_start in range(0, len(claude_label_list), BATCH_SIZE):
        batch_keys = claude_label_list[batch_start:batch_start + BATCH_SIZE]
        batch_stats = {k: claude_labels[k] for k in batch_keys}
        batch_prompt = build_prompt(batch_stats, evidence, roster, staff, event_date)

        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(claude_label_list) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Calling Claude ({MODEL}) — batch {batch_num}/{total_batches} ({len(batch_keys)} labels)...")
        message = claude.messages.create(
            model=MODEL,
            max_tokens=16000,
            tools=[mapping_tool],
            tool_choice={"type": "tool", "name": "submit_speaker_mappings"},
            messages=[{"role": "user", "content": batch_prompt}],
        )

        stop_reason = message.stop_reason
        if stop_reason == "max_tokens":
            print(f"  WARNING: Claude hit max_tokens on batch {batch_num} — some labels may be missing")

        tool_block = next((b for b in message.content if b.type == "tool_use"), None)
        if not tool_block:
            print(f"  Claude did not call the mapping tool on batch {batch_num} — skipping batch.")
            continue

        batch_mappings = tool_block.input.get("mappings", [])
        print(f"  Batch {batch_num}: {len(batch_mappings)} suggestions")
        all_mappings.extend(batch_mappings)

    mappings = all_mappings
    print(f"  Claude returned {len(mappings)} suggestions")

    # Counters for summary
    auto_applied = []
    pending = []
    skipped_low = []
    public_unknown = []

    for m in mappings:
        label = m.get("speaker_label")
        if not label or label not in labels_to_process:
            continue

        person_id = m.get("person_id")
        confidence = m.get("confidence", "low")
        category = m.get("category", "unknown")
        reasoning = m.get("reasoning", "")

        if not dry_run:
            if confidence == "high" and person_id and category in ("council", "staff"):
                apply_mapping(client, transcript_id, label, person_id)
                store_suggestion(client, transcript_id, m, status="auto_applied")
                auto_applied.append((label, person_id, reasoning))
            elif category in ("public", "unknown") and not person_id:
                store_suggestion(client, transcript_id, m, status="auto_applied")
                public_unknown.append(label)
            elif confidence in ("medium", "low") and category in ("council", "staff"):
                store_suggestion(client, transcript_id, m, status="pending")
                if confidence == "low":
                    skipped_low.append(label)
                else:
                    pending.append(label)
            else:
                store_suggestion(client, transcript_id, m, status="pending")
                pending.append(label)
        else:
            # Dry run — just print
            pid_str = f"person_id={person_id}" if person_id else "no person"
            print(f"  [DRY RUN] {label}: {category} / {confidence} / {pid_str} — {reasoning[:120]}")

    if not dry_run:
        # Print summary
        print()
        print("  RESULTS:")
        if auto_applied:
            names = ", ".join(f"{lbl} (person_id={pid})" for lbl, pid, _ in auto_applied)
            print(f"  AUTO-APPLIED (high):   {names}")
        if pending:
            print(f"  PENDING REVIEW:        {', '.join(pending)}")
        if skipped_low:
            print(f"  LOW CONFIDENCE:        {', '.join(skipped_low)}")
        if public_unknown:
            print(f"  PUBLIC/UNKNOWN:        {', '.join(public_unknown)}")
        remaining = [l for l in labels_to_process if l not in
                     {m[0] for m in auto_applied} and l not in pending and
                     l not in skipped_low and l not in public_unknown]
        if remaining:
            print(f"  NOT IN RESPONSE:       {', '.join(remaining)}")


def run(transcript_id: int | None = None, event_id: int | None = None, dry_run: bool = False) -> None:
    client = get_client()

    if transcript_id or event_id:
        auto_map_transcript(transcript_id=transcript_id, event_id=event_id, dry_run=dry_run)
    else:
        # Process all complete transcripts
        result = client.table("transcripts").select("transcript_id").eq("status", "complete").execute()
        for t in result.data:
            auto_map_transcript(transcript_id=t["transcript_id"], dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-map speaker labels using Claude.")
    parser.add_argument("--transcript-id", type=int, help="Process a single transcript by transcript ID")
    parser.add_argument("--event-id", type=int, help="Process a single transcript by event ID")
    parser.add_argument("--dry-run", action="store_true", help="Print suggestions without writing to DB")
    args = parser.parse_args()
    run(transcript_id=args.transcript_id, event_id=args.event_id, dry_run=args.dry_run)
