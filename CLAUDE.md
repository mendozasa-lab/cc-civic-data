# Corpus Christi Civic Data — Claude Context

## Project Overview

Pulls all public meeting data from the City of Corpus Christi's Legistar system into Airtable, and generates transcripts from YouTube recordings of council meetings.

**Two workstreams:**
1. **Legistar → Airtable sync** — Airtable extension and automation scripts call the Legistar API via `fetch`/`remoteFetchAsync` and write to Airtable using scripting globals (`base`, `table`, etc.). No external runtime, no credentials needed.
2. **Meeting transcription** — Fetch Granicus video URLs, submit to AssemblyAI for diarized/timestamped transcription, store in Transcripts + Transcript Segments tables, link segments to Persons.

**All scripts run inside Airtable** — either as scripting extensions (manual) or automations (triggered). The Node.js scaffolding in `scripts/` and `package.json` is not used for Airtable work.

**Historical depth (decided 2026-04-04):** All sync scripts prompt for a start date at runtime. Bodies and Persons are full syncs (no date filter). Matters, Events, and downstream tables filter by their primary date field from the user-supplied start date onward. The duplicate-base exploration strategy was set aside in favor of this approach.

**Corpus Christi specifics:**
- Legistar client slug: `corpuschristi`
- YouTube channel: `CCTVCorpusChristi`
- Council meetings typically on Tuesdays; videos run 2–4+ hours
- Archived data (Oct 2006–Dec 2014) is in a separate Legistar section

Work also involves Airtable extension scripts (run manually in the scripting extension) and Airtable automation scripts (triggered automatically). See extension vs. automation distinction below.

## Airtable Base Structure

9 tables. See `legistar setup/` for full field specs. Setup script: `scripts/airtable-setup.js`. Office Records table created via `scripts/create-office-records-table.js`.

| Table | Primary Field | Links To |
|-------|--------------|----------|
| Bodies | BodyId (number) | — |
| Persons | PersonId (number) | — |
| Matters | MatterId (number) | — |
| Events | EventId (number) | Bodies |
| Matter Attachments | AttachmentId (number) | Matters |
| Event Items | EventItemId (number) | Events, Matters |
| Transcripts | YouTubeVideoId (text)* | Events |
| Votes | VoteId (number) | Event Items, Persons |
| Office Records | OfficeRecordId (number) | Persons, Bodies |

*TranscriptId (autoNumber), YouTubeURL (formula), and TranscriptWordCount (formula) must be added manually — autoNumber and formula fields cannot be created via script.

**Events.EventMedia** = Granicus clip ID (text). 637 of 1,398 events have a value. Used to look up the Granicus player page and extract the M3U8 media URL for transcription.

## Airtable Scripting Conventions

- **Timezone:** `America/Chicago` (Corpus Christi is Central Time)
- **Date format:** `iso` (`YYYY-MM-DD`) for all date and dateTime fields
- **Time format:** `12hour` for all dateTime fields
- **Field helpers:** Factory function pattern established in `scripts/airtable-setup.js` — use as a template

## Extension vs. Automation — Critical Distinction

These are two different script contexts. Always be clear about which context a script targets.

| Capability | Extension | Automation |
|-----------|-----------|------------|
| Interactive input | `input.textAsync/buttonsAsync/tableAsync/viewAsync/fieldAsync/recordAsync/fileAsync()` | ❌ |
| Persistent settings UI | `input.config(settingsObj)` | ❌ |
| Pre-configured inputs | ❌ | `input.config()` — returns `{key: value}` |
| Secrets (API keys, etc.) | ❌ | `input.secret('Key Name')` |
| Display output to user | `output.text/markdown/table/inspect/clear()` | ❌ |
| Pass output to next step | ❌ | `output.set(key, value)` (JSON-serializable) |
| `cursor` global | ✅ `cursor.activeTableId`, `cursor.activeViewId` | ❌ |
| `session` global | ✅ `session.currentUser` | ❌ |
| `fetch` | Browser-native | Server-side (no cookies, no CORS issues, 4.5MB response limit) |
| `remoteFetchAsync` | ✅ Requests from Airtable servers — bypasses CORS | ❌ |

**Always use `remoteFetchAsync` for Legistar API calls in extension scripts.** The Legistar API does not set CORS headers, so browser-native `fetch` will be blocked.

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
| `scripts/sync-votes.js` | ⬜ Not started | — |
| `scripts/sync-office-records.js` | ⬜ Not started | — |

**Running Airtable record count: ~67,306 / 125,000** (pending: Votes, Office Records)

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
- `EventMedia` field on Events holds the Granicus clip ID (e.g. `"2171"`)
- Player page: `https://corpuschristi.granicus.com/player/clip/{clipId}?view_id=2&redirect=true`
- Media URL extracted via regex on page source: `video_url="(https://archive-stream\.granicus\.com/[^"]+\.m3u8)"`
- M3U8 HLS streams are supported by AssemblyAI directly — no download step needed

**Transcription service:** AssemblyAI (`speaker_labels: true` for diarization)
- Workflow: submit job → get job ID → poll for completion → parse segments
- Requires AssemblyAI API key stored via `input.secret('AssemblyAI Key')` in an automation

**Data model — Transcript Segments table (not yet created):**
One record per speaker turn, linked to Transcript, Event, and Person.
| Field | Type |
|-------|------|
| Transcript | linked → Transcripts |
| Person | linked → Persons (after speaker mapping) |
| SpeakerLabel | text (e.g. "Speaker A") |
| StartTime | number (ms) |
| EndTime | number (ms) |
| SegmentText | longText |

**Speaker mapping:** AssemblyAI returns "Speaker A", "Speaker B", etc. User maps labels to Person records after reviewing the transcript. This step is manual per meeting.

**Scope:** City Council meetings only, manually triggered per event. ~637 events have a Granicus clip ID.

## Full API References

- `docs/airtable-scripting-api.md` — complete Airtable scripting method signatures, field type options schemas, and examples
- `docs/legistar-api.md` — all Legistar endpoints with live-verified field schemas, Airtable field mappings, and known quirks
