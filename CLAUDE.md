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

13 tables. Schema: `supabase/schema.sql`. All tables have public read RLS policies (anon key can SELECT, not write).

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
| transcripts | transcript_id | One per event. status: pending → processing → complete/error |
| transcript_segments | segment_id | One per speaker turn. person_id null until mapped |
| speaker_mappings | mapping_id | Maps speaker_label → person_id per transcript |
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
| `transcribe.py` | Downloads audio via ffmpeg, uploads to ElevenLabs Scribe v2, inserts `transcript_segments`, triggers summarize |
| `map_speakers.py` | Interactive CLI: shows sample utterances per speaker label, user maps to person_id |
| `summarize.py` | Generates meeting summaries + rolling member summaries via Claude (claude-opus-4-6) |
| `supabase_client.py` | Shared Supabase client (service key), `fetch_all()`, `upsert_batch()` helpers |

**Run order:**
```
python fetch_m3u8.py [--event-id N]
python transcribe.py [--event-id N | --transcript-id N | --audio-file path]
python map_speakers.py --transcript-id N
python summarize.py [--event-id N | --person-id N]
```

**GitHub Actions:** `.github/workflows/transcribe.yml` — manually triggered via `workflow_dispatch`. Takes optional `event_id` input; blank = all pending. Runs on `ubuntu-latest` with ffmpeg installed. Use this instead of running locally.

**Known transcription issues:**
- Some Corpus Christi recordings are 7–9 hours long (not just 2–3hr council meetings) — these produce ~380MB MP3 files
- ElevenLabs sometimes drops the connection (`RemoteDisconnected`) or returns 500 on large files — retry by resetting `status='pending'` and rerunning
- To reset a failed transcript: `UPDATE transcripts SET status='pending', error_message=NULL WHERE event_id=N`
- Upload uses `requests-toolbelt` `MultipartEncoderMonitor` for streaming with progress; timeout is `(60, None)` (no read timeout)

**Video source:** Granicus (not YouTube).
- `event_media` field on events holds the Granicus clip ID (e.g. `"2171"`)
- Player page: `https://corpuschristi.granicus.com/player/clip/{clipId}?view_id=2&redirect=true`
- M3U8 URL extracted via regex: `video_url="(https://archive-stream\.granicus\.com/[^"]+\.m3u8)"`

**ElevenLabs Scribe v2:**
- Auth: `xi-api-key` header
- Endpoint: `POST https://api.elevenlabs.io/v1/speech-to-text`
- Returns word-level data — post-processed into speaker-turn segments
- Speaker labels: `"speaker_0"`, `"speaker_1"` etc.
- Timestamps in decimal seconds
- Cost: ~$0.40/hr → ~$760 for full 637-meeting backfill

**Speaker mapping:** ElevenLabs returns arbitrary labels per recording — no cross-recording recognition. User maps labels to Person records after reviewing sample utterances. Mapping stored in `speaker_mappings`; `transcript_segments.person_id` updated in place.

**Credentials:** `.env` file — `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`

**Scope:** City Council meetings only, manually triggered per event. ~637 events have a Granicus clip ID.

## Full API References

- `docs/legistar-api.md` — all Legistar endpoints with live-verified field schemas and known quirks
- `docs/airtable-scripting-api.md` — kept for reference; Airtable no longer primary data store
