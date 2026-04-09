# ElevenLabs Speech-to-Text API Reference

Used in `scripts/transcription/transcribe.py` to diarize Corpus Christi city council meeting recordings.

## Authentication

All requests require `xi-api-key` header.

## POST /v1/speech-to-text — Submit transcription

```
POST https://api.elevenlabs.io/v1/speech-to-text
xi-api-key: <key>
Content-Type: multipart/form-data
```

### Required parameters

| Field | Type | Description |
|-------|------|-------------|
| `model_id` | string | `"scribe_v2"` (use this) or `"scribe_v1"` |
| `file` **or** `cloud_storage_url` **or** `source_url` | — | Exactly one must be provided (see below) |

### Audio source — pick one

| Field | Type | Notes |
|-------|------|-------|
| `file` | binary (multipart) | Audio/video file upload, max 3 GB, min 100ms |
| `cloud_storage_url` | string (HTTPS URL) | Direct link to file in S3, GCS, R2, CDN, etc. Max 2 GB. **Use this for R2 links.** |
| `source_url` | string (URL) | YouTube, TikTok, or other hosted video/audio |

### Optional parameters we use

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `diarize` | bool | false | Enable speaker diarization — assigns `speaker_id` to each word |
| `timestamps_granularity` | string | `"none"` | `"word"` for word-level timestamps (use this) or `"character"` |
| `num_speakers` | int | auto | Max 32. Omit to let ElevenLabs detect. |

### Other optional parameters (not currently used)

| Field | Type | Description |
|-------|------|-------------|
| `language_code` | string | ISO-639-1/3 code. Omit for auto-detection. |
| `tag_audio_events` | bool | Label non-speech sounds (default: true) |
| `keyterms` | string[] | Up to 1000 terms (50 chars each) to boost recognition |
| `temperature` | float | 0.0–2.0, controls randomness |
| `seed` | int | For reproducible results |
| `webhook` | bool | Requires webhook URL configured in ElevenLabs workspace settings — **not configured, do not use** |

### Supported audio formats

MP3, WAV, FLAC, OGG, M4A, MP4, WebM, MOV, AVI. Optimal: 16-bit PCM at 16kHz.

### Response — synchronous

When not using `webhook`, the response contains the full transcription (may take minutes for long files):

```json
{
  "transcription_id": "abc123",
  "language_code": "en",
  "language_probability": 0.99,
  "text": "Full transcript text...",
  "audio_duration_secs": 9241.5,
  "words": [
    {
      "text": "Hello",
      "start": 0.24,
      "end": 0.61,
      "type": "word",
      "speaker_id": "speaker_0",
      "logprob": -0.003
    }
  ]
}
```

### Response — async (webhook)

If `webhook=true` is set (requires workspace webhook config), returns immediately:

```json
{
  "message": "Transcription queued",
  "transcription_id": "abc123"
}
```

**We do not use webhook mode** — workspace webhook not configured. We submit synchronously and poll by `transcription_id`.

### Word types

| `type` | Description |
|--------|-------------|
| `"word"` | Spoken word |
| `"spacing"` | Pause/silence between words |
| `"audio_event"` | Non-speech sound (laughter, applause, etc.) |

---

## GET /v1/speech-to-text/transcripts/{transcription_id} — Retrieve result

```
GET https://api.elevenlabs.io/v1/speech-to-text/transcripts/{transcription_id}
xi-api-key: <key>
```

Used for polling after async submission or resuming a job after a crash.

### Response

Same schema as the synchronous POST response above. The `words` array is absent while still processing — poll until it appears.

### Our polling logic

- Poll every 60 seconds
- Timeout after 2 hours
- If the runner crashes mid-poll: `elevenlabs_transcription_id` is saved in `transcripts` table — next run resumes from here without re-uploading
- To manually resume: `python transcribe.py --event-id N --elevenlabs-id <id>`

---

## How we use it (our flow)

```
1. Download audio from Granicus M3U8 via ffmpeg → MP3
2. Upload MP3 to Cloudflare R2 → public URL saved to transcripts.audio_url
3. POST /v1/speech-to-text with cloud_storage_url=<R2 URL>
   - ElevenLabs fetches the file from R2 themselves
   - Returns transcription_id immediately (or full result synchronously)
4. Save elevenlabs_transcription_id to transcripts table
5. Poll GET /transcripts/{id} every 60s until words array appears
6. Convert words → speaker-turn segments → insert into transcript_segments
```

### Cost

~$0.40/hour of audio. A 4-hour council meeting ≈ $1.60.

---

## Speaker diarization output

ElevenLabs assigns arbitrary labels per recording (`speaker_0`, `speaker_1`, etc.). Labels are **not consistent across recordings** — the same person gets a different label in each meeting. Our `auto_map_speakers.py` script maps these labels to `persons` records.
