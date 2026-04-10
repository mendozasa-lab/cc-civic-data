# Corpus Christi Civic Data — Claude Context

## Project Overview

Public civic data platform for Corpus Christi. Pulls all public meeting data from the Legistar API into Supabase (PostgreSQL), generates diarized transcripts from Granicus video recordings, and serves everything via a public Streamlit app.

**Three workstreams:**
1. **Legistar → Supabase sync** — Python scripts call the Legistar API and upsert into Supabase. Scheduled via GitHub Actions. The older Airtable JS scripts in `scripts/` are reference implementations only (Airtable retired as of 2026-04-04).
2. **Streamlit app** — Public-facing app in `streamlit_app/`. Three pages: Meetings (transcript browser + AI summaries), Persons (voting records + rolling AI summaries), Transparency (data provenance). Built with Streamlit + supabase-py + Plotly.
3. **Meeting transcription** — Working pipeline in `scripts/transcription/`. Fetches Granicus M3U8 URLs, downloads audio via ffmpeg, submits to ElevenLabs Scribe v2 for diarized transcription, stores segments in Supabase, maps speaker labels to Person records, generates AI summaries via Claude.

**Architecture (migrated 2026-04-04):** Supabase (PostgreSQL) + Streamlit. Airtable retired — hit 125k record limit; transcript segments alone would add ~255k records. Supabase is free tier, unlimited rows, real SQL joins.

**Historical depth:** All sync scripts prompt for a start date at runtime. Bodies and Persons are full syncs (no date filter). Matters, Events, and downstream tables filter from the user-supplied start date onward.

**Corpus Christi specifics:**
- Legistar client slug: `corpuschristi`
- YouTube channel: `CCTVCorpusChristi`
- Council meetings typically on Tuesdays; videos run 2–4+ hours
- Archived data (Oct 2006–Dec 2014) is in a separate Legistar section

## Supabase Schema

14 tables. Schema: `supabase/schema.sql`. All tables have public read RLS policies (anon key can SELECT, not write).

**Legistar tables (synced from API):**

| Table | PK | Foreign Keys |
|-------|-----|-------------|
| bodies | body_id | — |
| persons | person_id | — |
| matters | matter_id | — |
| events | event_id | body_id → bodies |
| matter_attachments | attachment_id | matter_id → matters |
| event_items | event_item_id | event_id → events, matter_id → matters (nullable) |
| votes | (vote_id, event_item_id) | event_item_id → event_items, person_id → persons (nullable) |
| office_records | office_record_id | person_id → persons, body_id → bodies |

**Transcription tables:**

| Table | PK | Notes |
|-------|-----|-------|
| transcripts | transcript_id | One per event. status: pending → processing → complete/error. Stores `elevenlabs_transcription_id` and `audio_url` (R2 public URL) |
| transcript_segments | segment_id | One per speaker turn. person_id null until mapped |
| speaker_mappings | mapping_id | Maps speaker_label → person_id per transcript |
| speaker_mapping_suggestions | suggestion_id | Claude's auto-mapping suggestions. status: pending → approved/rejected/auto_applied |
| transcript_entities | entity_id | Named entities (PII mode) from ElevenLabs. Char offsets mapped to segment_id |
| meeting_summaries | summary_id | AI-generated overview + per-member briefs (JSONB) |
| member_summaries | member_summary_id | Rolling AI narrative per council member |

**Critical: `votes` has a composite PK `(vote_id, event_item_id)`.** Legistar assigns one VoteId per person per meeting — the same VoteId appears on every agenda item voted on that day. VoteId alone is NOT unique.

**Events.event_media** = Granicus clip ID (text). 637 of 1,398 events have a value. Used to extract M3U8 URLs for transcription.

**Supabase row limit:** Default PostgREST page size is 1000 rows. Always paginate using the `fetch_all()` helper in `streamlit_app/utils/db.py` rather than relying on `.limit()`.

## Streamlit App

`streamlit_app/` — public-facing, deployed on Streamlit Community Cloud.

- **`app.py`** — main entry point, navigation
- **`pages/meetings.py`** — meeting selector in sidebar, AI summary, transcript browser (keyword + speaker filters), provenance tooltip
- **`pages/persons.py`** — council member profiles, voting record, vote breakdown chart, AI rolling summary with quotes, statements expander
- **`pages/transparency.py`** — data provenance page explaining data sources and AI methodology
- **`utils/db.py`** — all Supabase queries with `@st.cache_data(ttl=3600)` caching
- **`utils/fetch_all()`** — pagination helper; use for ALL Supabase queries to avoid the 1000-row default limit
- **Credentials:** `streamlit_app/.streamlit/secrets.toml` (gitignored) — needs `SUPABASE_URL` and `SUPABASE_ANON_KEY`
- **Run:** `cd streamlit_app && python -m streamlit run app.py`

## Legistar Sync Script Status

All scripts complete. The JS scripts in `scripts/` were the original Airtable implementations and are kept as reference only. The canonical data is now in Supabase.

| Table | Records |
|-------|---------|
| bodies | 51 |
| persons | 5,008 |
| matters | 9,795 (2020-01-01 onward) |
| events | 1,398 (2020-01-01 onward) |
| matter_attachments | 21,305 (~50 fetch errors, skipped) |
| event_items | 29,749 (136 matter links unresolved — pre-2020) |
| votes | 42,579 (~105 fetch errors skipped) |
| office_records | 1,004 |

## Transcription Pipeline

**Goal:** "Who said what and when" — diarized, timestamped transcripts linked to Person records.

**Scripts in `scripts/transcription/`:**

| Script | Purpose |
|--------|---------|
| `fetch_m3u8.py` | Scrapes Granicus player pages, extracts M3U8 URLs, creates `transcripts` records (status=pending) |
| `transcribe.py` | Downloads audio via ffmpeg, uploads to R2, submits to ElevenLabs async with webhook; exits after submission. Segment insertion handled by Edge Function. |
| `auto_map_speakers.py` | Uses Claude to identify speaker labels from transcript text; applies high-confidence mappings, stores medium/low in `speaker_mapping_suggestions` |
| `import_entities.py` | Backfills `transcript_entities` for transcripts processed via crash-recovery path (which previously skipped entities). Usage: `python import_entities.py --event-id N` |
| `manage_named_staff.py` | Search persons by name and add to `NAMED_STAFF` in auto_map_speakers.py. Used by the `manage_named_staff.yml` workflow. |
| `summarize.py` | Generates meeting summaries + rolling member summaries via Claude (claude-opus-4-6) |
| `supabase_client.py` | Shared Supabase client (service key), `fetch_all()`, `upsert_batch()` helpers |

**Run order:**
```
[transcribe.yml GitHub Action]
  → fetch_m3u8.py → transcribe.py (exits after ElevenLabs submission)

[ElevenLabs webhook → Supabase Edge Function: elevenlabs-webhook]
  → insert transcript_segments + transcript_entities
  → mark transcript complete
  → dispatch map_speakers GitHub Actions workflow

[map_speakers.yml GitHub Action] (dispatched by Edge Function or manually)
  → auto_map_speakers.py

[Streamlit admin]
  → Map Speakers page: approve/reject suggestions, manual mapping
```

**GitHub Actions workflows:**
- `transcribe.yml` — fetch M3U8s + submit to ElevenLabs. Input: `event_id` (blank = all pending). Does NOT insert segments (webhook does that).
- `map_speakers.yml` — auto-mapping only. Dispatched automatically by Edge Function after webhook, or manually. Inputs: `event_id`, `dry_run`

**ElevenLabs async+webhook flow (as of 2026-04-09):**
1. `transcribe.py` downloads audio via ffmpeg, uploads MP3 to Cloudflare R2, saves public URL to `transcripts.audio_url`
2. Submits to ElevenLabs with `cloud_storage_url` (R2 URL), `webhook=true`, `webhook_id`, `webhook_metadata={"transcript_id": N}`, `entity_detection=pii`, and keyterms
3. Saves `elevenlabs_transcription_id`, sets status=processing, exits — GitHub Action completes in <2 min
4. ElevenLabs POSTs full result to Supabase Edge Function `elevenlabs-webhook` when done
5. Edge Function inserts segments + entities, marks complete, dispatches `map_speakers`

**Crash recovery:** If job submission succeeds but Edge Function never fires:
- `python transcribe.py --event-id N --elevenlabs-id <id>` — polls ElevenLabs directly and inserts segments locally (no entities on this path)
- To reset fully: `UPDATE transcripts SET status='pending', error_message=NULL, elevenlabs_transcription_id=NULL, audio_url=NULL WHERE event_id=N`
- To re-run from existing R2 audio (skip re-upload): `audio_url` is preserved; transcribe.py skips upload if set

**ElevenLabs Scribe v2 parameters (verified):**
- Auth: `xi-api-key` header
- Submit: `POST https://api.elevenlabs.io/v1/speech-to-text` — form data (not JSON)
- `cloud_storage_url` — R2 public URL (not `url` or `audio_url`)
- `model_id=scribe_v2`, `diarize=true`, `webhook=true`, `webhook_id=<id>`, `entity_detection=pii`
- `keyterms` — repeated form field, up to 1000 terms × 50 chars, scribe_v2 only
- Poll: `GET https://api.elevenlabs.io/v1/speech-to-text/transcripts/{id}`
- Speaker labels: `"speaker_0"`, `"speaker_1"` etc. (arbitrary per recording, no cross-recording identity)
- Cost: ~$0.40/hr. Results stored for 2 years on ElevenLabs servers.
- Full reference: `docs/elevenlabs-api.md`

**Keyterm prompting:**
- `load_keyterms(supabase, event_date)` — queries active council members from `office_records + persons`, returns first/last/full names
- Appends `SUPPLEMENTAL_KEYTERMS` (hardcoded in `transcribe.py`): CC water infrastructure, organizations, water policy terms, acronyms
- Dynamic roster ensures newly seated members are included automatically

**Audio storage — Cloudflare R2:**
- Bucket: `cc-civic-data` (public read enabled)
- Public URL base: `https://pub-b1d9e555223a4dd3ae4aeea0d7570cc1.r2.dev`
- Object key: `audio/event_{event_id}.mp3`
- Access via boto3 S3-compatible client using `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- 10GB free tier; files are ~380–476MB each

**Supabase Edge Function:**
- `supabase/functions/elevenlabs-webhook/index.ts` — Deno/TypeScript
- Verifies HMAC-SHA256 signature (`ELEVENLABS_WEBHOOK_SECRET`)
- Returns 200 immediately; processes async via `EdgeRuntime.waitUntil()`
- Never returns 5xx (would trigger ElevenLabs retry → double-insert)
- Secrets needed: `ELEVENLABS_WEBHOOK_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL`, `GITHUB_PAT`
- Deploy: `supabase functions deploy elevenlabs-webhook`

**Speaker mapping:** Two-stage process:
1. `auto_map_speakers.py` — Claude analyzes transcript text for name mentions (self-introductions, direct address, roll call). Uses forced tool use (`tool_choice`) to guarantee JSON output. Pre-filters public commenters (short + early speakers) without calling Claude. Batches 30 labels per Claude call, `max_tokens=16000`. `load_roster()` returns `(council, staff)` — council from office_records (city council body), staff from office_records (City Manager/Secretary/Attorney titles) + `NAMED_STAFF` hardcoded supplement. High-confidence staff mappings auto-apply same as council.
2. Streamlit Map Speakers admin page — review pending suggestions (approve/reject with Claude's reasoning shown), manually map any remaining unlabeled speakers with enhanced profiles (8 longest utterances, speaking time stats)

**NAMED_STAFF** — hardcoded at top of `auto_map_speakers.py`. Add key recurring staff who have a `person_id` in Supabase but no office_records in Legistar. Peter Zanoni (City Manager, person_id=820) is there — Legistar has no record for him. Rebecca Huerta (City Secretary, person_id=179) is picked up from office_records automatically. To add someone: use the `manage_named_staff.yml` GitHub Actions workflow (search by name, then add with person_id + title).

**Known issues:**
- event_id 4086: repeated ElevenLabs failures and duplicate charges. Support ticket submitted 2026-04-08. Use `--elevenlabs-id` when support provides the transcription ID.
- event_id 4111: webhook did not fire (zero Edge Function invocations). Recovered via crash recovery path. Likely cause: webhook_id or URL misconfiguration in ElevenLabs dashboard. Verify before next submission.
- Some recordings are 7–9 hours long → ~380–476MB MP3 files, ~$3.60/recording at $0.40/hr

**Credentials:**
- `.env` file: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `ELEVENLABS_WEBHOOK_ID`
- GitHub Actions secrets: same as above + `ELEVENLABS_WEBHOOK_ID`
- Supabase Edge Function secrets: `ELEVENLABS_WEBHOOK_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL`, `GITHUB_PAT`

**Scope:** City Council meetings only, manually triggered per event. ~637 events have a Granicus clip ID.

## Next Session Priorities

1. **Legistar sync workflow** — No GitHub Actions workflow exists to pull new events from Legistar. Need on-demand script + workflow to sync events, event_items, and votes for new meetings. City council met 2026-04-10 — that data needs to be pulled.
2. **Transcription notifications** — Push notifications (ntfy.sh or similar) after: (a) ElevenLabs webhook fires and segments are inserted, (b) auto_map_speakers completes. Add to Edge Function and map_speakers workflow.
3. **Verify ElevenLabs webhook** — check that webhook_id and URL in ElevenLabs dashboard match deployed Edge Function. Submit a test transcription to confirm the callback fires before queueing more meetings.

## Full API References

- `docs/legistar-api.md` — all Legistar endpoints with live-verified field schemas and known quirks
- `docs/elevenlabs-api.md` — complete ElevenLabs Scribe v2 reference: correct param names, webhook setup, entity detection, keyterms, realtime streaming
- `docs/airtable-scripting-api.md` — kept for reference; Airtable no longer primary data store
