# ElevenLabs Speech-to-Text API Reference

Used in `scripts/transcription/transcribe.py` to produce diarized, timestamped transcripts of Corpus Christi city council meetings. Results are stored in Supabase and surfaced in the public Streamlit app.

---

## Overview

| Item | Value |
|------|-------|
| Model (batch) | `scribe_v2` |
| Model (realtime) | `scribe_v2_realtime` |
| Auth header | `xi-api-key: <key>` |
| Base URL | `https://api.elevenlabs.io` |
| Transcript retention | 2 years |

---

## Batch Transcription — POST /v1/speech-to-text

Submit an audio file for transcription. Returns either synchronously (blocks until done) or asynchronously (returns `transcription_id` immediately and POSTs result to a configured webhook).

```
POST https://api.elevenlabs.io/v1/speech-to-text
xi-api-key: <key>
Content-Type: multipart/form-data
```

### Audio source — exactly one required

| Field | Max size | Description |
|-------|----------|-------------|
| `cloud_storage_url` | 2 GB | HTTPS URL to file in R2, S3, GCS, CDN, etc. **This is what we use.** ElevenLabs fetches the file themselves. |
| `file` | 3 GB | Multipart binary upload. Fallback if URL fails. |
| `source_url` | — | YouTube, TikTok, or other hosted video/audio URL. |

### Parameters

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `model_id` | string | **required** | `"scribe_v2"` |
| `diarize` | bool | **use** | `true` — identifies which speaker is talking. Assigns `speaker_id` to each word. |
| `timestamps_granularity` | string | **use** | `"word"` — word-level start/end times. |
| `webhook` | bool | **use** | `true` — async mode. Returns `transcription_id` immediately; ElevenLabs POSTs result to configured webhook when done. Requires webhook configured in ElevenLabs dashboard. |
| `webhook_id` | string | **use** | Target a specific webhook by ID. Set via `ELEVENLABS_WEBHOOK_ID` env var. |
| `webhook_metadata` | string (JSON) | **use** | Custom data included in webhook payload. We pass `{"transcript_id": <tid>}` so the receiver knows which DB record to update. Max 16KB. |
| `entity_detection` | string[] | **use** | `["pii"]` — detect person names, organizations, locations, and other PII. Returns `entities` array in response. Additional cost. |
| `keyterms` | string[] | **use** | Up to 1000 terms (50 chars each) to bias transcription toward. scribe_v2 only. Additional cost. We pass council member names + CC-specific terminology. |
| `language_code` | string | soon | ISO-639-1/3 code. Omit for auto-detection. Consider locking to `"en"`. |
| `num_speakers` | int | soon | Hint for diarization (max 32). CC council ≈ Mayor + 8 members + staff ≈ 12. |
| `tag_audio_events` | bool | optional | Default true. Tags laughter, applause, etc. as `audio_event` words. |
| `no_verbatim` | bool | optional | Remove filler words (scribe_v2 only). |
| `temperature` | float | optional | 0.0–2.0, controls output randomness. |
| `seed` | int | optional | For reproducible results. |

### Response — synchronous (no webhook)

Blocks until transcription completes. Risky for 4–9 hour recordings — connection may time out. **Prefer async+webhook for long files.**

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
  ],
  "entities": [
    {
      "text": "Maria Lopez",
      "entity_type": "person_name",
      "start_char": 234,
      "end_char": 245
    }
  ]
}
```

### Response — async (webhook=true)

Returns immediately:

```json
{
  "message": "Transcription queued",
  "transcription_id": "abc123"
}
```

Full result is POSTed to the configured webhook URL when transcription completes.

### Word object fields

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | The transcribed word or sound |
| `start` | float \| null | Start time in seconds |
| `end` | float \| null | End time in seconds |
| `type` | string | `"word"`, `"spacing"`, or `"audio_event"` |
| `speaker_id` | string \| null | e.g. `"speaker_0"`. Only present when `diarize=true`. |
| `logprob` | float | Confidence (-∞ to 0; closer to 0 = more confident) |

### Supported audio formats

MP3, WAV, FLAC, OGG, M4A, MP4, WebM, MOV, AVI. Optimal: 16-bit PCM at 16kHz.

---

## GET /v1/speech-to-text/transcripts/{transcription_id}

Retrieve a stored transcription result.

```
GET https://api.elevenlabs.io/v1/speech-to-text/transcripts/{transcription_id}
xi-api-key: <key>
```

Returns the same schema as the synchronous POST response. The `words` array is absent while still processing — poll until it appears.

**We use this for:**
- Polling after async submission (check every 60s until `words` present)
- Crash recovery: `transcription_id` is saved in `transcripts.elevenlabs_transcription_id`; next run resumes without re-uploading
- Manual recovery: `python transcribe.py --event-id N --elevenlabs-id <id>`

**Results are stored on ElevenLabs servers for 2 years.**

---

## DELETE /v1/speech-to-text/transcripts/{transcription_id}

Delete a stored transcription.

```
DELETE https://api.elevenlabs.io/v1/speech-to-text/transcripts/{transcription_id}
xi-api-key: <key>
```

---

## Webhooks

Webhooks allow ElevenLabs to POST transcription results to our server when done, eliminating the need for polling and avoiding connection timeouts on long recordings.

### Create a webhook

```
POST https://api.elevenlabs.io/v1/workspace/webhooks
xi-api-key: <key>

{
  "settings": {
    "auth_type": "hmac",
    "name": "CC Civic Data STT",
    "webhook_url": "https://<project>.supabase.co/functions/v1/elevenlabs-webhook"
  }
}
```

Returns `webhook_id` and `webhook_secret`. Save both — the secret is shown only once.

### Update a webhook

```
PATCH https://api.elevenlabs.io/v1/workspace/webhooks/{webhook_id}

{
  "name": "CC Civic Data STT",
  "is_disabled": false,
  "retry_enabled": true
}
```

Set `retry_enabled: true` to automatically retry on 5xx responses and timeouts.

### Delete a webhook

```
DELETE https://api.elevenlabs.io/v1/workspace/webhooks/{webhook_id}
```

### List webhooks

```
GET https://api.elevenlabs.io/v1/workspace/webhooks
```

### Webhook payload (when transcription completes)

ElevenLabs POSTs to our URL with:

```json
{
  "type": "speech_to_text_transcription",
  "request_id": "req_abc",
  "webhook_metadata": "{\"transcript_id\": 42}",
  "transcription": {
    "language_code": "en",
    "language_probability": 0.99,
    "text": "Full transcript...",
    "audio_duration_secs": 9241.5,
    "words": [ ... ],
    "entities": [ ... ]
  }
}
```

### HMAC signature verification

Every incoming webhook request includes an `ElevenLabs-Signature` header. Always verify it before processing:

```typescript
// Deno / Edge Function
const secret = Deno.env.get("ELEVENLABS_WEBHOOK_SECRET")!;
const signature = req.headers.get("ElevenLabs-Signature");
const body = await req.text();

const key = await crypto.subtle.importKey(
  "raw", new TextEncoder().encode(secret),
  { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
);
const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
const expected = btoa(String.fromCharCode(...new Uint8Array(mac)));

if (signature !== expected) {
  return new Response("Unauthorized", { status: 401 });
}
```

### Retry behavior

- ElevenLabs retries on 5xx responses and connection timeouts
- **Never return 5xx after you've started processing** — this causes double-inserts
- Return 200 immediately, then process asynchronously using `EdgeRuntime.waitUntil()`
- Return 4xx for bad requests (no retry)

---

## History API — /v1/history

> ⚠️ **This tracks text-to-speech (TTS) generation history, NOT speech-to-text transcriptions.** It is not useful for our pipeline. Documented here to avoid confusion.

The history endpoints (`GET /v1/history`, `GET /v1/history/{id}`, etc.) list audio generated by the TTS API. They have no relation to Scribe transcription jobs.

---

## Keyterm Prompting

Biases the model toward specific words or phrases. The model uses context intelligently — providing "Choke Canyon" helps it transcribe that phrase correctly while still accurately handling similar-sounding phrases in other contexts.

**When to use:** Proper nouns, acronyms, technical/legal terms, and local names that the model would likely mishear. Do NOT add common words — they don't need boosting.

**Constraints:** Up to 1000 terms, max 50 characters each. scribe_v2 only. Additional cost per request.

### Our keyterms

**Dynamic** (loaded from Supabase at transcription time): active council member first names, last names, and full names for the event date.

**Supplemental hardcoded list:**

```python
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
```

---

## Entity Detection

Identifies specific entities in the transcript text and returns their character offsets.

**Parameter:** `entity_detection: ["pii"]`

**Categories available:** `"pii"` (person names, addresses, SSNs, etc.), `"phi"` (medical), `"pci"` (payment card), `"other"`, `"all"`

**Response:** `entities` array alongside `words`:

```json
"entities": [
  {
    "text": "Maria Lopez",
    "entity_type": "person_name",
    "start_char": 234,
    "end_char": 245
  }
]
```

**`start_char` / `end_char`** are character offsets into the full `text` field of the response, not into individual segment text.

**Mapping to segments:** In our webhook receiver, we track cumulative character position as we build segments, then match each entity's range to the segment that contains it. The matched `segment_id` is stored in `transcript_entities`.

**Use case:** Surface public commenters who appear across multiple meetings; cross-meeting search by person name on the Transparency page.

**Additional cost** beyond base transcription price.

---

## Realtime Streaming (future — live meetings)

For transcribing live Granicus streams as meetings happen.

**Endpoint:** `wss://api.elevenlabs.io/v1/speech-to-text/realtime`  
**Model:** `scribe_v2_realtime`  
**Protocol:** WebSocket

### Auth

- Server-side: `xi-api-key` in connection header (use API key directly)
- Client-side: single-use token (never expose API key to browser)

### Key query parameters

| Param | Description |
|-------|-------------|
| `model_id` | `"scribe_v2_realtime"` |
| `include_timestamps` | `true` for word-level timing |
| `commit_strategy` | `"manual"` or `"vad"` (voice activity detection) |
| `language_code` | ISO-639-1/3 |
| `audio_format` | `"pcm_16000"` (default), or other PCM/ulaw rates |

### Commit strategies

- **Manual** (default): You call `commit()` to finalize a segment. Best practice: commit every 20–30 seconds at a silence or logical break. Auto-commits every 90 seconds. Do not commit in rapid succession — degrades model performance.
- **VAD**: Model auto-detects speech/silence and commits automatically. Recommended for microphone input.

### Events received

| Event | Description |
|-------|-------------|
| `session_started` | Connection confirmed |
| `partial_transcript` | Interim result, may change |
| `committed_transcript` | Finalized segment |
| `committed_transcript_with_timestamps` | Finalized + word-level timing (when `include_timestamps=true`) |

### Audio format requirements

- PCM 16-bit little-endian
- 16kHz sample rate (recommended)
- Mono channel only
- Send chunks every 0.1–1 second

### Server-side URL streaming

The SDK supports streaming directly from a URL using `RealtimeUrlOptions` (handles audio chunking automatically). Requires `ffmpeg` installed.

---

## Our Pipeline (current)

```
1. Download M3U8 from Granicus via ffmpeg → MP3
2. Upload MP3 to Cloudflare R2 → public URL saved to transcripts.audio_url
3. Load keyterms: active council members (from Supabase) + supplemental list
4. POST /v1/speech-to-text
     cloud_storage_url = R2 URL
     diarize = true
     timestamps_granularity = "word"
     webhook = true
     webhook_id = ELEVENLABS_WEBHOOK_ID
     webhook_metadata = {"transcript_id": <tid>}
     entity_detection = ["pii"]
     keyterms = [council names + supplemental list]
   → Returns transcription_id immediately
5. Save transcription_id to transcripts.elevenlabs_transcription_id
6. Set transcripts.status = "processing" → EXIT
7. [async] ElevenLabs POSTs result to Supabase Edge Function
8. Edge Function: insert transcript_segments + transcript_entities
9. Edge Function: mark transcript complete
10. Edge Function: dispatch map_speakers GitHub Actions workflow
```

### Crash recovery

If the runner crashes after upload but before receiving the webhook:
- `elevenlabs_transcription_id` is saved in the DB
- Re-run with `--elevenlabs-id`: polls GET endpoint directly
- To reset a failed transcript: `UPDATE transcripts SET status='pending', error_message=NULL, elevenlabs_transcription_id=NULL WHERE event_id=N`

### Cost estimate

~$0.40/hour of audio. A 4-hour council meeting ≈ $1.60. Entity detection and keyterms add a small additional charge.
