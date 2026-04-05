# Corpus Christi Civic Data — Claude Context

## Project Overview

Public civic data platform for Corpus Christi. Pulls all public meeting data from the Legistar API into Supabase (PostgreSQL) and serves it via a public Streamlit app. Also plans to generate diarized transcripts from Granicus video recordings of council meetings.

**Three workstreams:**
1. **Legistar → Supabase sync** — Python scripts call the Legistar API and upsert into Supabase. Scheduled via GitHub Actions. The older Airtable JS scripts in `scripts/` are reference implementations only.
2. **Streamlit app** — Public-facing app in `streamlit_app/`. Currently shows council member profiles with voting records. Built with Streamlit + supabase-py + Plotly.
3. **Meeting transcription** — Planned. Fetch Granicus M3U8 URLs, submit to ElevenLabs Scribe v2 for diarized transcription, store segments in Supabase, manually map speaker labels to Person records.

**Architecture (decided 2026-04-04):** Migrated from Airtable to Supabase after Airtable's 125k record limit became a constraint (transcript segments alone would add ~255k records). Supabase is free tier, unlimited rows, real SQL joins.

**Historical depth:** All sync scripts prompt for a start date at runtime. Bodies and Persons are full syncs (no date filter). Matters, Events, and downstream tables filter from the user-supplied start date onward.

**Corpus Christi specifics:**
- Legistar client slug: `corpuschristi`
- YouTube channel: `CCTVCorpusChristi`
- Council meetings typically on Tuesdays; videos run 2–4+ hours
- Archived data (Oct 2006–Dec 2014) is in a separate Legistar section

## Supabase Schema

9 tables mirroring the Legistar data model. Schema: `supabase/schema.sql`. All tables have public read RLS policies (anon key can SELECT, not write).

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

**Critical: `votes` has a composite PK `(vote_id, event_item_id)`.** Legistar assigns one VoteId per person per meeting — the same VoteId appears on every agenda item voted on that day. VoteId alone is NOT unique.

**Events.event_media** = Granicus clip ID (text). 637 of 1,398 events have a value. Used to extract M3U8 URLs for transcription.

**Supabase row limit:** Default PostgREST page size is 1000 rows. Always paginate using the `fetch_all()` helper in `streamlit_app/utils/db.py` rather than relying on `.limit()`.

## Streamlit App

`streamlit_app/` — public-facing app, currently shows council member profiles.

- **`app.py`** — main entry point
- **`utils/db.py`** — all Supabase queries with `@st.cache_data(ttl=3600)` caching
- **`utils/fetch_all()`** — pagination helper; use for ALL Supabase queries to avoid the 1000-row default limit
- **Credentials:** `streamlit_app/.streamlit/secrets.toml` (gitignored) — needs `SUPABASE_URL` and `SUPABASE_ANON_KEY`
- **Run:** `cd streamlit_app && python -m streamlit run app.py`

## Sync Script Patterns (established 2026-04-03)

All sync scripts follow this pattern. See completed scripts for reference implementations.

- **`remoteFetchAsync`** for all Legistar calls (not `fetch` — CORS blocked)
- **Pagination** on every endpoint — always use `$top=1000&$skip=N` loop, stop when `page.length < 1000`
- **`toUtcString(ts)`** — appends `'Z'` to Legistar UTC timestamps for dateTime fields
- **`toDateString(ts)`** — strips `T00:00:00` for date-only fields (MatterIntroDate etc.)
- **`emptyToNull(val)`** — converts empty strings to null for email/phone field types
- **`syncSelectChoices(fieldName, values)`** — adds missing choices to a singleSelect field before writing records (see sync-matters.js)
- **Upsert** — load existing records by ID into a map, then split into toCreate/toUpdate arrays, batch write at 50

## Sync Script Status

| Script | Status | Records |
|--------|--------|---------|
| `scripts/sync-bodies.js` | ✅ Complete | 51 |
| `scripts/sync-persons.js` | ✅ Complete | 5,008 |
| `scripts/sync-matters.js` | ✅ Complete | 9,795 (2020-01-01 onward) |
| `scripts/sync-events.js` | ✅ Complete | 1,398 (2020-01-01 onward) |
| `scripts/sync-matter-attachments.js` | ✅ Complete | 21,305 (~50 fetch errors, skipped) |
| `scripts/sync-event-items.js` | ✅ Complete | 29,749 (136 matter links unresolved — pre-2020) |
| `scripts/sync-votes.js` | ✅ Complete | 42,579 (~105 fetch errors skipped) |
| `scripts/sync-office-records.js` | ✅ Complete | 1,004 |

**Running Airtable record count: ~111,069 / 125,000** (all Legistar tables complete)

## Field Types That Cannot Be Created via Script

`formula`, `createdTime`, `rollup`, `count`, `multipleLookupValues`, `autoNumber`,
`lastModifiedTime`, `button`, `createdBy`, `lastModifiedBy`, `externalSyncSource`, `aiText`

## Batch Operation Limits

**Airtable Scripting API** (used in extension/automation scripts):
- `createRecordsAsync` — max **50** records per call
- `updateRecordsAsync` — max **50** records per call
- `deleteRecordsAsync` — max **50** records per call
- `selectRecordsAsync` with `recordIds` — max **100** records per call

**Automation scripts** have a **30-second execution timeout** — initial bulk syncs should run as extensions (manual), not automations. Automations are suited for incremental/triggered syncs.

## Sync Strategy

**Upsert pattern:** Each Legistar entity has a unique integer ID. Search Airtable for an existing record matching that ID, update if found, create if not. Use `table.selectRecordsAsync` with a filter to find the existing record.

**Linked record resolution:** To link e.g. an Event to its Body, find the Airtable record ID in Bodies where `BodyId` = `EventBodyId`, then use that Airtable record ID in the link field.

**Sync order** (respects foreign key dependencies): Bodies → Persons → Matters → Events → Matter Attachments → Event Items → Votes → Office Records → Transcripts (separate workflow)

**Incremental sync filter syntax:** `$filter=EventLastModifiedUtc gt datetime'2025-06-01T00:00:00'`

## Transcription Pipeline (planned, not yet built)

**Goal:** "Who said what and when" — diarized, timestamped transcripts linked to Person records.

**Video source:** Granicus (not YouTube). Videos are at `corpuschristi.granicus.com`.
- `event_media` field on events holds the Granicus clip ID (e.g. `"2171"`)
- Player page: `https://corpuschristi.granicus.com/player/clip/{clipId}?view_id=2&redirect=true`
- Media URL extracted via regex on page source: `video_url="(https://archive-stream\.granicus\.com/[^"]+\.m3u8)"`

**Transcription service:** ElevenLabs Scribe v2 (chosen for best WER accuracy at 2.3%)
- Auth: `xi-api-key` header
- Endpoint: `POST https://api.elevenlabs.io/v1/speech-to-text`
- Body: `{ audio_url, model_id: "scribe_v2", diarize: true, timestamps_granularity: "word" }`
- Returns **word-level** data — must post-process into utterances (group consecutive same-speaker words)
- Speaker labels: `"speaker_0"`, `"speaker_1"` etc. (not "Speaker A")
- Timestamps in **decimal seconds** (not milliseconds)
- Synchronous API — no polling needed; 3-hour files may take several minutes to respond
- Cost: ~$0.40/hr → ~$760 for full 637-meeting backfill

**Data model — transcript_segments table (not yet created in Supabase):**
One record per speaker turn, linked to transcript, event, and person.
| Column | Type | Notes |
|--------|------|-------|
| transcript_id | integer FK | |
| event_id | integer FK | denormalized for easy querying |
| person_id | integer FK | null until speaker mapping step |
| speaker_label | text | e.g. "speaker_0" |
| start_time | numeric | decimal seconds |
| end_time | numeric | decimal seconds |
| segment_text | text | |

**Speaker mapping:** ElevenLabs returns arbitrary labels per recording — no cross-recording recognition. User maps labels to Person records after reviewing sample utterances. Mapping stored in Supabase.

**Scope:** City Council meetings only, manually triggered per event. ~637 events have a Granicus clip ID.

## Full API References

- `docs/legistar-api.md` — all Legistar endpoints with live-verified field schemas and known quirks
- `docs/airtable-scripting-api.md` — kept for reference; Airtable no longer primary data store
