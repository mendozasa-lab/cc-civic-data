"""
transcribe.py — Submit M3U8 URLs to ElevenLabs Scribe v2 and store transcript segments.

Usage:
    python transcribe.py                       # all pending transcripts
    python transcribe.py --transcript-id 42    # single transcript
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from dotenv import load_dotenv

from supabase_client import get_client, upsert_batch

load_dotenv()

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def _upload_with_progress(path: str, label: str, api_key: str) -> requests.Response:
    """Stream a multipart upload to ElevenLabs with progress reporting."""
    total = Path(path).stat().st_size

    def _callback(monitor: MultipartEncoderMonitor) -> None:
        pct = monitor.bytes_read / monitor.len * 100
        mb_read = monitor.bytes_read / 1_000_000
        mb_total = total / 1_000_000
        print(f"\r  Uploading {label}: {mb_read:.1f}/{mb_total:.1f} MB ({pct:.0f}%)", end="", flush=True)

    with open(path, "rb") as f:
        encoder = MultipartEncoder(fields={
            "model_id": "scribe_v2",
            "diarize": "true",
            "timestamps_granularity": "word",
            "file": (label, f, "audio/mpeg"),
        })
        monitor = MultipartEncoderMonitor(encoder, _callback)
        resp = requests.post(
            ELEVENLABS_URL,
            headers={"xi-api-key": api_key, "Content-Type": monitor.content_type},
            data=monitor,
            timeout=3600,
        )
    print()  # newline after final progress line
    return resp


def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Error: ELEVENLABS_API_KEY must be set in .env")
    return key


def words_to_segments(words: list) -> list:
    """
    Group consecutive words with the same speaker_id into speaker-turn segments.
    Each word dict has: text, start, end, speaker_id (and optionally type).
    """
    if not words:
        return []

    segments = []
    current_speaker = None
    current_words = []

    for word in words:
        # skip non-word tokens (spacing etc.) that lack speaker info
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


def transcribe_one(transcript: dict, api_key: str, audio_file: str | None = None) -> None:
    client = get_client()
    tid = transcript["transcript_id"]
    eid = transcript["event_id"]
    m3u8_url = transcript["m3u8_url"]

    print(f"Transcribing transcript_id={tid} event_id={eid}")
    print(f"  M3U8: {m3u8_url}")

    # Mark as processing before the long operation
    client.table("transcripts").update({"status": "processing"}).eq("transcript_id", tid).execute()

    # Use provided audio file or download via ffmpeg
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
                [
                    "ffmpeg", "-y",
                    "-loglevel", "error",  # suppress verbose segment-open lines
                    "-stats",              # but keep the progress line
                    "-i", m3u8_url,
                    "-vn",                 # audio only
                    "-acodec", "mp3",
                    "-q:a", "4",           # ~165 kbps — good quality, manageable size
                    tmp_path,
                ],
                timeout=7200,  # 2-hour download limit
            )
            if result.returncode != 0:
                raise RuntimeError("ffmpeg exited with non-zero status")
            size_mb = Path(tmp_path).stat().st_size / 1_000_000
            print(f"  Downloaded {size_mb:.1f} MB")

        # Upload to ElevenLabs with streaming progress
        resp = _upload_with_progress(tmp_path, f"event_{eid}.mp3", api_key)
        resp.raise_for_status()
    except (requests.RequestException, subprocess.TimeoutExpired, RuntimeError, OSError) as e:
        detail = ""
        if isinstance(e, requests.RequestException) and hasattr(e, "response") and e.response is not None:
            try:
                detail = f" — {e.response.json()}"
            except Exception:
                detail = f" — {e.response.text}"
        print(f"  Error: {e}{detail}")
        client.table("transcripts").update({
            "status": "error",
            "error_message": str(e)[:500],
        }).eq("transcript_id", tid).execute()
        return
    finally:
        if not provided_file:
            Path(tmp_path).unlink(missing_ok=True)

    data = resp.json()
    words = data.get("words", [])
    print(f"  Got {len(words)} words from ElevenLabs")

    segments = words_to_segments(words)
    print(f"  Post-processed into {len(segments)} speaker-turn segments")

    if not segments:
        client.table("transcripts").update({
            "status": "error",
            "error_message": "No segments produced from ElevenLabs response",
        }).eq("transcript_id", tid).execute()
        return

    # Build rows for transcript_segments
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
        for s in segments
        if s["segment_text"]  # skip empty segments
    ]

    upsert_batch(client, "transcript_segments", rows, batch_size=500)
    print(f"  Inserted {len(rows)} segments")

    # Estimate cost: ElevenLabs charges per character of output
    # Rough estimate from duration if available
    last_end = segments[-1]["end_time"] if segments else 0
    cost = round((last_end / 3600) * 0.40, 4)  # ~$0.40/hr

    client.table("transcripts").update({
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": last_end,
        "cost_usd": cost,
    }).eq("transcript_id", tid).execute()

    print(f"  Done. Duration: {last_end:.0f}s, estimated cost: ${cost}")

    # Generate AI summaries if ANTHROPIC_API_KEY is available
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  Generating summaries...")
        from summarize import generate_meeting_summary
        generate_meeting_summary(eid)
    else:
        print(f"  Skipping summaries (ANTHROPIC_API_KEY not set)")


def run(transcript_id: int | None = None, event_id: int | None = None, audio_file: str | None = None) -> None:
    client = get_client()
    api_key = get_api_key()

    if transcript_id:
        result = client.table("transcripts").select("*").eq("transcript_id", transcript_id).execute()
    elif event_id:
        result = client.table("transcripts").select("*").eq("event_id", event_id).execute()
    else:
        result = client.table("transcripts").select("*").eq("status", "pending").execute()

    transcripts = result.data
    if not transcripts:
        print("No pending transcripts found.")
        return

    print(f"Processing {len(transcripts)} transcript(s)")
    for t in transcripts:
        transcribe_one(t, api_key, audio_file=audio_file)
        time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe meetings via ElevenLabs Scribe v2.")
    parser.add_argument("--transcript-id", type=int, help="Process a single transcript by transcript ID")
    parser.add_argument("--event-id", type=int, help="Process a single transcript by event ID")
    parser.add_argument("--audio-file", type=str, help="Path to pre-downloaded audio file (skips ffmpeg download)")
    args = parser.parse_args()
    run(transcript_id=args.transcript_id, event_id=args.event_id, audio_file=args.audio_file)
