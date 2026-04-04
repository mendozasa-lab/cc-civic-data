# Corpus Christi Civic Data — Claude Context

## Project Overview

Pulls all public meeting data from the City of Corpus Christi's Legistar system into Airtable, and generates transcripts from YouTube recordings of council meetings.

**Two workstreams:**
1. **Legistar → Airtable sync** — Node.js scripts (`scripts/`) call the Legistar API and upsert into Airtable via the REST API
2. **Meeting transcription** — Pull YouTube auto-captions (via `youtube-transcript-api` Python lib) and store in Transcripts table; future upgrade to Whisper/AssemblyAI

**Tech stack:** Node.js, axios, airtable SDK, dotenv. Transcript work may require a Python subprocess.

**Corpus Christi specifics:**
- Legistar client slug: `corpuschristi`
- YouTube channel: `CCTVCorpusChristi`
- Council meetings typically on Tuesdays; videos run 2–4+ hours
- Archived data (Oct 2006–Dec 2014) is in a separate Legistar section

Work also involves Airtable extension scripts (run manually in the scripting extension) and Airtable automation scripts (triggered automatically). See extension vs. automation distinction below.

## Airtable Base Structure

8 tables. See `legistar setup/` for full field specs. Setup script: `scripts/airtable-setup.js`.

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

*TranscriptId (autoNumber), YouTubeURL (formula), and TranscriptWordCount (formula) must be added manually — autoNumber and formula fields cannot be created via script.

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
| Create/modify tables & fields | ✅ | ❌ |

## Field Types That Cannot Be Created via Script

`formula`, `createdTime`, `rollup`, `count`, `multipleLookupValues`, `autoNumber`,
`lastModifiedTime`, `button`, `createdBy`, `lastModifiedBy`, `externalSyncSource`, `aiText`

## Batch Operation Limits

**Airtable Scripting API** (used in extension/automation scripts):
- `createRecordsAsync` — max **50** records per call
- `updateRecordsAsync` — max **50** records per call
- `deleteRecordsAsync` — max **50** records per call
- `selectRecordsAsync` with `recordIds` — max **100** records per call

**Airtable REST API** (used in Node.js sync scripts):
- Batch creates/updates — max **10** records per request
- Rate limit — **5 requests/second** per base

**Automation scripts** have a **30-second execution timeout** — complex syncs must run externally (not via Airtable automations).

## Sync Strategy

**Upsert pattern:** Each Legistar entity has a unique integer ID. Search Airtable for an existing record matching that ID (`filterByFormula=({BodyId}=123)`), update if found, create if not.

**Linked record resolution:** To link e.g. an Event to its Body, find the Airtable record ID in Bodies where `BodyId` = `EventBodyId`, then use that Airtable record ID in the link field.

**Sync order** (respects foreign key dependencies): Bodies → Persons → Matters → Events → Matter Attachments → Event Items → Votes → Transcripts (separate workflow)

**Incremental sync filter syntax:** `$filter=EventLastModifiedUtc gt datetime'2025-06-01T00:00:00'`

## Full API References

- `docs/airtable-scripting-api.md` — complete Airtable scripting method signatures, field type options schemas, and examples
- `docs/legistar-api.md` — all Legistar endpoints with live-verified field schemas, Airtable field mappings, and known quirks
