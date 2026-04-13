"""
transcribe.py — Submit M3U8 URLs to ElevenLabs Scribe v2 and store transcript segments.

Normal flow (async + webhook):
  1. Download audio from Granicus M3U8 via ffmpeg → MP3
  2. Upload MP3 to Cloudflare R2 → public URL
  3. Submit R2 URL to ElevenLabs with webhook=true → get transcription_id immediately
  4. Save transcription_id, set status=processing, EXIT
  5. ElevenLabs POSTs result to Supabase Edge Function when done

Resume / crash recovery flow (--elevenlabs-id):
  python transcribe.py --event-id N --elevenlabs-id <id>
  Polls ElevenLabs directly and inserts segments locally (no webhook needed).

Usage:
    python transcribe.py                       # all pending transcripts
    python transcribe.py --event-id 42         # single event
    python transcribe.py --event-id 42 --elevenlabs-id abc123  # crash recovery
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from supabase_client import get_client, fetch_all, upsert_batch

load_dotenv()

ELEVENLABS_SUBMIT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_GET_URL = "https://api.elevenlabs.io/v1/speech-to-text/transcripts/{transcription_id}"
POLL_INTERVAL = 60    # seconds between polls (crash recovery only)
POLL_MAX_WAIT = 7200  # give up after 2 hours

R2_PUBLIC_BASE = "https://pub-b1d9e555223a4dd3ae4aeea0d7570cc1.r2.dev"

# Corpus Christi-specific terms that ElevenLabs would likely mishear.
# Council member names are added dynamically from Supabase.
SUPPLEMENTAL_KEYTERMS = [
    # Water supply infrastructure
    "O.N. Stevens", "Choke Canyon", "Lake Texana", "Mary Rhodes Pipeline",
    "Inner Harbor", "Harbor Island", "Baffin Bay",
    # Companies & organizations active in CC water crisis
    "Acciona Agua", "MasTec Industrial", "Corpus Christi Desal Partners",
    "Corpus Christi Polymers", "Aquatech", "Evangeline Laguna",
    "Nueces River Authority", "Lavaca-Navidad River Authority",
    "Texas Water Development Board",
    # Agencies & acronyms
    "TCEQ", "LNRA", "TIRZ", "ETJ", "TPDES", "MS4", "GMA", "GCD", "MGD",
    # Water policy & technical terms
    "curtailment", "desalination", "brackish", "brine discharge",
    "groundwater rights", "wastewater recycling", "dead pool",
    "surcharge", "interlocal", "disannexation", "platting",
]


# ---------------------------------------------------------------------------
# Keyterms
# ---------------------------------------------------------------------------

def load_keyterms(client, event_date: str) -> list[str]:
    """Build keyterm list: active council member names + supplemental CC terms."""
    data = fetch_all(
        client,
        "office_records",
        query_fn=lambda: client.table("office_records")
            .select(
                "office_record_start_date, office_record_end_date, "
                "persons(person_full_name, person_first_name, person_last_name), "
                "bodies(body_name)"
            ),
    )

    names: set[str] = set()
    for r in data:
        body = (r.get("bodies") or {}).get("body_name", "")
        if "city council" not in body.lower():
            continue
        p = r.get("persons")
        if not p:
            continue
        start = r.get("office_record_start_date") or ""
        end = r.get("office_record_end_date")
        if start > event_date:
            continue
        if end and end < event_date:
            continue
        for name in [p.get("person_first_name"), p.get("person_last_name"), p.get("person_full_name")]:
            if name and len(name) <= 50:
                names.add(name)

    all_terms = list(names) + SUPPLEMENTAL_KEYTERMS
    # Deduplicate and enforce 50-char limit
    seen: set[str] = set()
    result = []
    for term in all_terms:
        if term and len(term) <= 50 and term not in seen:
            seen.add(term)
            result.append(term)
    return result[:1000]  # ElevenLabs max


# ---------------------------------------------------------------------------
# ElevenLabs submission (async + webhook)
# ---------------------------------------------------------------------------

def _submit_async(audio_url: str, tid: int, keyterms: list[str], api_key: str) -> str:
    """Submit audio URL to ElevenLabs with webhook=true.
    ElevenLabs fetches the file from R2 and POSTs the result to our webhook.
    Returns transcription_id immediately."""

    webhook_id = os.environ.get("ELEVENLABS_WEBHOOK_ID")
    if not webhook_id:
        sys.exit("Error: ELEVENLABS_WEBHOOK_ID must be set. Create a webhook in ElevenLabs dashboard first.")

    fields = {
        "model_id": "scribe_v2",
        "diarize": "true",
        "timestamps_granularity": "word",
        "cloud_storage_url": audio_url,
        "webhook": "true",
        "webhook_id": webhook_id,
        "webhook_metadata": json.dumps({"transcript_id": tid}),
        "entity_detection": "pii",
    }

    # requests doesn't support repeated keys in dict — use list of tuples
    data: list[tuple[str, str]] = [(k, v) for k, v in fields.items()]
    for term in keyterms:
        data.append(("keyterms", term))

    print(f"  Submitting to ElevenLabs (async, {len(keyterms)} keyterms)...", flush=True)
    resp = requests.post(
        ELEVENLABS_SUBMIT_URL,
        headers={"xi-api-key": api_key},
        data=data,
        timeout=(30, 60),
    )
    resp.raise_for_status()
    result = resp.json()

    transcription_id = result.get("transcription_id")
    if not transcription_id:
        raise RuntimeError(f"No transcription_id in ElevenLabs response: {str(result)[:300]}")

    print(f"  Submitted. ElevenLabs transcription_id: {transcription_id}")
    return transcription_id


# ---------------------------------------------------------------------------
# ElevenLabs polling (crash recovery only)
# ---------------------------------------------------------------------------

def _poll_for_result(transcription_id: str, api_key: str) -> dict:
    """Poll ElevenLabs until transcription is complete. Returns full response dict.
    Used only for --elevenlabs-id crash recovery, not the normal async flow."""
    url = ELEVENLABS_GET_URL.format(transcription_id=transcription_id)
    headers = {"xi-api-key": api_key}
    waited = 0
    while waited < POLL_MAX_WAIT:
        print(f"  Polling... ({waited}s elapsed)", flush=True)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            print(f"  Poll request failed ({e}), will retry")
            time.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            continue
        if resp.status_code == 200:
            data = resp.json()
            if data.get("words"):
                return data
        elif resp.status_code not in (202, 404):
            print(f"  Unexpected poll response: {resp.status_code} {resp.text[:200]}")
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    raise TimeoutError(f"Transcription {transcription_id} did not complete within {POLL_MAX_WAIT}s")


# ---------------------------------------------------------------------------
# R2 upload
# ---------------------------------------------------------------------------

def _upload_to_r2(path: str, filename: str) -> str:
    """Upload MP3 to Cloudflare R2. Returns public URL."""
    import boto3
    from botocore.config import Config

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET", "cc-civic-audio")

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

    total = Path(path).stat().st_size
    uploaded = [0]

    def _progress(bytes_amount: int) -> None:
        uploaded[0] += bytes_amount
        pct = uploaded[0] / total * 100
        mb = uploaded[0] / 1_000_000
        mb_total = total / 1_000_000
        print(f"  Uploading to R2: {mb:.0f}/{mb_total:.0f} MB ({pct:.0f}%)", flush=True)

    print(f"  Uploading {filename} to R2...", flush=True)
    s3.upload_file(path, bucket, filename, Callback=_progress, ExtraArgs={"ContentType": "audio/mpeg"})
    url = f"{R2_PUBLIC_BASE}/{filename}"
    print(f"  Audio URL: {url}")
    return url


# ---------------------------------------------------------------------------
# Segment building (used in crash recovery / polling path)
# ---------------------------------------------------------------------------

def words_to_segments(words: list) -> list:
    """Group consecutive words with the same speaker_id into speaker-turn segments."""
    if not words:
        return []

    segments = []
    current_speaker = None
    current_words = []

    for word in words:
        speaker = word.get("speaker_id") or word.get("speaker")
        if speaker is None:
            if current_words:
                current_words.append(word)
            continue
        if speaker != current_speaker:
            if current_words and current_speaker is not None:
                segments.append(_build_segment(current_speaker, current_words))
            current_speaker = speaker
            current_words = [word]
        else:
            current_words.append(word)

    if current_words and current_speaker is not None:
        segments.append(_build_segment(current_speaker, current_words))

    return segments


def _build_segment(speaker: str, words: list) -> dict:
    text_parts = [w.get("text", "") for w in words if w.get("text")]
    return {
        "speaker_label": speaker,
        "start_time": words[0].get("start", 0),
        "end_time": words[-1].get("end", 0),
        "segment_text": " ".join(text_parts).strip(),
    }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Error: ELEVENLABS_API_KEY must be set in .env")
    return key


def _handle_request_error(e: Exception) -> str:
    """Extract detail from a requests error for logging."""
    if isinstance(e, requests.RequestException) and hasattr(e, "response") and e.response is not None:
        try:
            return f" — {e.response.json()}"
        except Exception:
            return f" — {e.response.text}"
    return ""


# ---------------------------------------------------------------------------
# Main transcription logic
# ---------------------------------------------------------------------------

def transcribe_one(
    transcript: dict,
    api_key: str,
    audio_file: str | None = None,
    elevenlabs_id: str | None = None,
) -> None:
    client = get_client()
    tid = transcript["transcript_id"]
    eid = transcript["event_id"]
    m3u8_url = transcript["m3u8_url"]
    event_date = transcript.get("event_date", "")

    print(f"Transcribing transcript_id={tid} event_id={eid}")

    # --- Crash recovery path: poll an existing transcription_id ---
    # Use --elevenlabs-id if provided, otherwise fall back to what's already in the DB.
    # This handles the case where the webhook failed but the job was submitted successfully.
    el_tid = elevenlabs_id or transcript.get("elevenlabs_transcription_id")
    if el_tid:
        print(f"  Crash recovery: polling ElevenLabs transcription_id={el_tid}")
        client.table("transcripts").update({"status": "processing"}).eq("transcript_id", tid).execute()
        _poll_and_insert(client, tid, eid, el_tid, api_key)
        return

    # --- Normal async path ---
    client.table("transcripts").update({"status": "processing"}).eq("transcript_id", tid).execute()

    # Step 1: Get audio URL (upload to R2 if not already there)
    saved_audio_url = transcript.get("audio_url")
    if saved_audio_url:
        print(f"  Audio already in R2: {saved_audio_url}")
        audio_url = saved_audio_url
    else:
        print(f"  M3U8: {m3u8_url}")
        provided_file = audio_file is not None
        if provided_file:
            tmp_path = audio_file
            size_mb = Path(tmp_path).stat().st_size / 1_000_000
            print(f"  Using provided audio file: {tmp_path} ({size_mb:.1f} MB)")
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            tmp_path = tmp.name

        try:
            if not provided_file:
                print(f"  Downloading stream via ffmpeg...")
                result = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-stats",
                     "-i", m3u8_url, "-vn", "-acodec", "mp3", "-q:a", "4", tmp_path],
                    timeout=7200,
                )
                if result.returncode != 0:
                    raise RuntimeError("ffmpeg exited with non-zero status")
                size_mb = Path(tmp_path).stat().st_size / 1_000_000
                print(f"  Downloaded {size_mb:.1f} MB")

            audio_url = _upload_to_r2(tmp_path, f"event_{eid}.mp3")
            client.table("transcripts").update({"audio_url": audio_url}).eq("transcript_id", tid).execute()
        except (requests.RequestException, subprocess.TimeoutExpired, RuntimeError, OSError) as e:
            detail = _handle_request_error(e)
            print(f"  Error: {e}{detail}")
            client.table("transcripts").update({
                "status": "error",
                "error_message": str(e)[:500],
            }).eq("transcript_id", tid).execute()
            return
        finally:
            if not provided_file:
                Path(tmp_path).unlink(missing_ok=True)

    # Step 2: Load keyterms
    keyterms = load_keyterms(client, event_date)
    print(f"  Keyterms: {len(keyterms)} terms ({sum(1 for t in keyterms if t not in SUPPLEMENTAL_KEYTERMS)} council names + {len(SUPPLEMENTAL_KEYTERMS)} supplemental)")

    # Step 3: Submit to ElevenLabs async with webhook
    try:
        new_el_tid = _submit_async(audio_url, tid, keyterms, api_key)
        client.table("transcripts").update({
            "elevenlabs_transcription_id": new_el_tid,
        }).eq("transcript_id", tid).execute()
        print(f"  Submitted. Webhook will handle completion. transcript_id={tid} status=processing")
    except (requests.RequestException, RuntimeError) as e:
        detail = _handle_request_error(e)
        print(f"  Error submitting to ElevenLabs: {e}{detail}")
        client.table("transcripts").update({
            "status": "error",
            "error_message": str(e)[:500],
        }).eq("transcript_id", tid).execute()


def _poll_and_insert(client, tid: int, eid: int, el_tid: str, api_key: str) -> None:
    """Crash recovery: poll ElevenLabs and insert segments locally (no entity detection)."""
    try:
        data = _poll_for_result(el_tid, api_key)
    except Exception as e:
        print(f"  Polling failed: {e}")
        client.table("transcripts").update({
            "status": "error",
            "error_message": str(e)[:500],
        }).eq("transcript_id", tid).execute()
        return

    words = data.get("words", [])
    entities = data.get("entities") or []
    print(f"  Got {len(words)} words, {len(entities)} entities from ElevenLabs")

    segments = words_to_segments(words)
    print(f"  Post-processed into {len(segments)} speaker-turn segments")

    if not segments:
        client.table("transcripts").update({
            "status": "error",
            "error_message": "No segments produced from ElevenLabs response",
        }).eq("transcript_id", tid).execute()
        return

    rows = [
        {
            "transcript_id": tid,
            "event_id": eid,
            "person_id": None,
            "speaker_label": s["speaker_label"],
            "start_time": s["start_time"],
            "end_time": s["end_time"],
            "segment_text": s["segment_text"],
        }
        for s in segments if s["segment_text"]
    ]

    upsert_batch(client, "transcript_segments", rows, batch_size=500)
    print(f"  Inserted {len(rows)} segments")

    # Insert entities if present — map char offsets to segment_ids
    if entities:
        # Fetch back the inserted segment_ids (in start_time order)
        db_segs = fetch_all(
            client,
            "transcript_segments",
            query_fn=lambda: client.table("transcript_segments")
                .select("segment_id, segment_text, start_time")
                .eq("transcript_id", tid)
                .order("start_time"),
        )
        # Rebuild char offsets (same logic as Edge Function / import_entities.py)
        char_offset = 0
        enriched = []
        for seg in db_segs:
            text = seg["segment_text"]
            enriched.append({
                "segment_id": seg["segment_id"],
                "char_start": char_offset,
                "char_end": char_offset + len(text),
            })
            char_offset += len(text) + 1

        def _find_seg(start_char, end_char):
            best_id, best_overlap = None, 0
            for s in enriched:
                if start_char >= s["char_start"] and end_char <= s["char_end"]:
                    return s["segment_id"]
                overlap = min(end_char, s["char_end"]) - max(start_char, s["char_start"])
                if overlap > best_overlap:
                    best_overlap, best_id = overlap, s["segment_id"]
            return best_id

        entity_rows = [
            {
                "transcript_id": tid,
                "event_id": eid,
                "segment_id": _find_seg(e.get("start_char", 0), e.get("end_char", 0)),
                "entity_text": e.get("text", ""),
                "entity_type": e.get("entity_type", ""),
                "start_char": e.get("start_char"),
                "end_char": e.get("end_char"),
            }
            for e in entities
        ]
        upsert_batch(client, "transcript_entities", entity_rows, batch_size=500)
        print(f"  Inserted {len(entity_rows)} entities")

    last_end = segments[-1]["end_time"] if segments else 0
    cost = round((last_end / 3600) * 0.40, 4)

    client.table("transcripts").update({
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": last_end,
        "cost_usd": cost,
    }).eq("transcript_id", tid).execute()

    print(f"  Done (polling path). Duration: {last_end:.0f}s, estimated cost: ${cost}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    transcript_id: int | None = None,
    event_id: int | None = None,
    audio_file: str | None = None,
    elevenlabs_id: str | None = None,
) -> None:
    client = get_client()
    api_key = get_api_key()

    if transcript_id:
        result = client.table("transcripts").select("*, events(event_date)").eq("transcript_id", transcript_id).execute()
    elif event_id:
        result = client.table("transcripts").select("*, events(event_date)").eq("event_id", event_id).execute()
    else:
        pending = client.table("transcripts").select("*, events(event_date)").eq("status", "pending").execute().data
        # Also pick up processing transcripts without a transcription_id (submit failed, audio already in R2)
        stalled = (
            client.table("transcripts").select("*, events(event_date)")
            .eq("status", "processing")
            .is_("elevenlabs_transcription_id", "null")
            .execute().data
        )
        transcripts = pending + stalled
        if not transcripts:
            print("No pending or stalled transcripts found.")
            return
        print(f"Processing {len(transcripts)} transcript(s)")
        for t in _flatten_event_date(transcripts):
            transcribe_one(t, api_key, audio_file=audio_file)
            time.sleep(1)
        return

    transcripts = _flatten_event_date(result.data)
    if not transcripts:
        print("No matching transcripts found.")
        return

    print(f"Processing {len(transcripts)} transcript(s)")
    for t in transcripts:
        transcribe_one(t, api_key, audio_file=audio_file, elevenlabs_id=elevenlabs_id)
        time.sleep(1)


def _flatten_event_date(transcripts: list) -> list:
    """Move events.event_date up to the transcript dict."""
    for t in transcripts:
        events = t.pop("events", None) or {}
        t["event_date"] = events.get("event_date", "")
    return transcripts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe meetings via ElevenLabs Scribe v2.")
    parser.add_argument("--transcript-id", type=int, help="Process a single transcript by transcript ID")
    parser.add_argument("--event-id", type=int, help="Process a single transcript by event ID")
    parser.add_argument("--audio-file", type=str, help="Path to pre-downloaded audio file (skips ffmpeg download)")
    parser.add_argument("--elevenlabs-id", type=str, help="Crash recovery: poll an existing ElevenLabs transcription ID and insert segments locally")
    args = parser.parse_args()
    run(
        transcript_id=args.transcript_id,
        event_id=args.event_id,
        audio_file=args.audio_file,
        elevenlabs_id=args.elevenlabs_id,
    )
