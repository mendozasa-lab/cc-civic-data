# CC Civic Data — Project Context

This document captures the full project context, decisions, and technical details established during initial planning. Use this as a reference when working on any part of this project.

---

## Project overview

This project pulls all public meeting data from the City of Corpus Christi's Legistar system into Airtable, and generates meeting transcripts from YouTube recordings of council meetings.

**Two workstreams:**
1. **Legistar → Airtable sync**: Pull structured data from the Legistar Web API and maintain it in Airtable tables
2. **Meeting transcription**: Extract transcripts from YouTube recordings of council meetings and store them in Airtable linked to the corresponding Event records

---

## Data source: Legistar Web API

- **Base URL**: `https://webapi.legistar.com/v1/corpuschristi/`
- **Auth**: None required — the Corpus Christi Legistar API is fully public
- **Format**: JSON responses
- **Protocol**: OData v3.0 URL conventions
- **Pagination**: Responses are capped at 1,000 records per request. Use `$top` and `$skip` OData parameters to page through results. Example: `?$top=1000&$skip=0`, then `?$top=1000&$skip=1000`, etc.
- **Filtering**: OData `$filter` parameter supported. Example: `?$filter=EventLastModifiedUtc gt datetime'2025-01-01'`
- **Ordering**: Use `$orderby` parameter. For incremental syncs, ordering by ID and filtering with `gt` (greater than) the highest synced ID may be more stable than offset-based paging on busy endpoints.

### Key endpoints

| Endpoint | Description |
|---|---|
| `/bodies` | Governmental bodies (City Council, boards, commissions, committees) |
| `/events` | All meetings (past, current, scheduled) |
| `/events/{EventId}/eventitems` | Agenda line items for a specific meeting. Supports `?AgendaNote=1&MinutesNote=1&Attachments=1` query params. |
| `/matters` | Legislation, ordinances, resolutions, presentations |
| `/matters/{MatterId}/attachments` | Document attachments for a specific matter |
| `/matters/{MatterId}/histories` | History/timeline of a matter through the legislative process. Supports `?AgendaNote=1&MinutesNote=1`. |
| `/persons` | Council members, board members, officials |
| `/events/{EventId}/eventitems/{EventItemId}/votes` | Individual roll call votes on a specific agenda item |
| `/bodytypes` | Lookup table for body type categories |
| `/actions` | Lookup table for action types |

### Important API behaviors

- The API returns all fields regardless of whether they have values — expect many null fields
- Date fields come back as strings in the format `2025-03-18T11:30:00` (UTC)
- The `EventVideoPath` field may contain a Granicus URL, a YouTube URL, or be empty
- The `EventInSiteURL` field gives the public-facing Legistar meeting page
- Matter attachments include a hyperlink field for downloading the actual PDF/document
- Some endpoints support expanding related data inline (e.g., EventItems on an Event), but separate calls are more reliable for pagination

---

## Airtable schema

### Table structure and relationships

Eight tables total. The schema was designed to mirror Legistar's data model with the addition of a Transcripts table.

**Bodies** → has many **Events**
**Events** → has many **Event Items**, has one **Transcript**
**Event Items** → belongs to one **Event**, optionally references one **Matter**, has many **Votes**
**Matters** → has many **Matter Attachments**, referenced by many **Event Items**
**Persons** → has many **Votes**
**Votes** → belongs to one **Event Item**, belongs to one **Person**
**Transcripts** → belongs to one **Event**

### Table details

**Bodies**
- BodyId (integer) — primary key from Legistar
- BodyName (text)
- BodyType (single select: Legislative Body, Board, Commission, Committee, Corporation, Other)
- BodyDescription (long text)
- BodyActiveFlag (checkbox)
- BodyMeetDay (text)
- BodyMeetTime (text)
- BodyMeetLocation (text)
- BodyLastModified (date with time)
- Linked: Events, Members (Persons)

**Events**
- EventId (integer) — primary key from Legistar
- Body (link to Bodies)
- EventDate (date)
- EventTime (text)
- EventLocation (text)
- EventAgendaFile (URL)
- EventMinutesFile (URL)
- EventInSiteURL (URL)
- EventVideoPath (URL)
- EventAgendaStatus (single select: Final, Draft, Not Available)
- EventMinutesStatus (single select: Final, Draft, Not Available)
- EventLastModified (date with time)
- Linked: Event Items, Transcript

**Event Items**
- EventItemId (integer) — primary key from Legistar
- Event (link to Events)
- Matter (link to Matters) — may be empty for procedural items
- EventItemTitle (long text)
- EventItemAgendaNumber (integer)
- EventItemActionName (text)
- EventItemResult (single select: Pass, Fail, Withdrawn, Tabled, Received and Filed, No Action, Other)
- EventItemAgendaNote (long text)
- EventItemMinutesNote (long text)
- EventItemLastModified (date with time)
- Linked: Votes

**Matters**
- MatterId (integer) — primary key from Legistar
- MatterFile (text) — the file number (e.g., "2025-0123")
- MatterName (text)
- MatterTitle (long text)
- MatterType (single select: Ordinance, Resolution, Presentation, Motion, Report, Agreement, Minutes, Other)
- MatterStatus (single select: Introduced, Passed, Failed, Withdrawn, Tabled, Referred, Adopted, Other)
- MatterBodyName (text)
- MatterIntroDate (date)
- MatterAgendaDate (date)
- MatterPassedDate (date)
- MatterEnactmentNumber (text)
- MatterLastModified (date with time)
- Linked: Matter Attachments, Event Items

**Matter Attachments**
- AttachmentId (integer) — primary key from Legistar
- Matter (link to Matters)
- AttachmentName (text)
- AttachmentHyperlink (URL)
- AttachmentIsSupporting (checkbox)
- AttachmentLastModified (date with time)

**Persons**
- PersonId (integer) — primary key from Legistar
- PersonFullName (text)
- PersonFirstName (text)
- PersonLastName (text)
- PersonEmail (email)
- PersonPhone (phone)
- PersonActiveFlag (checkbox)
- PersonLastModified (date with time)
- Linked: Votes

**Votes**
- VoteId (integer) — primary key from Legistar
- Event Item (link to Event Items)
- Person (link to Persons)
- VotePersonName (text) — backup in case linked record isn't matched
- VoteValueName (single select: Aye, Nay, Abstain, Absent, Recused, Present)
- VoteResult (single select: Pass, Fail)
- VoteLastModified (date with time)

**Transcripts**
- TranscriptId (autonumber)
- Event (link to Events)
- YouTubeVideoId (text)
- YouTubeURL (formula from YouTubeVideoId)
- TranscriptSource (single select: YouTube Auto-Captions, Whisper AI, AssemblyAI, Manual, Other)
- TranscriptFullText (long text)
- TranscriptStatus (single select: Pending, Complete, Failed, Needs Review)
- TranscriptCreated (date with time)
- TranscriptWordCount (formula)

---

## Sync strategy

### Sync order (respects foreign key dependencies)

1. Bodies
2. Persons
3. Matters
4. Events (links to Bodies)
5. Matter Attachments (links to Matters)
6. Event Items (links to Events and Matters)
7. Votes (links to Event Items and Persons)
8. Transcripts (links to Events) — separate workflow

### Initial vs. incremental sync

**Initial sync**: Page through all records for each endpoint using `$top=1000&$skip=0`, incrementing `$skip` by 1000 until fewer than 1000 records are returned.

**Incremental sync (daily/weekly)**: Use the `LastModifiedUtc` fields with OData `$filter` to pull only records changed since the last sync. Store the last sync timestamp somewhere (either in Airtable or a local config file). Example filter: `$filter=EventLastModifiedUtc gt datetime'2025-06-01T00:00:00'`

### Record matching (upsert logic)

Each Legistar record has a unique integer ID (BodyId, EventId, MatterId, etc.). When syncing:
1. Fetch records from Legistar
2. Search Airtable for existing records with matching IDs
3. If found, update the Airtable record
4. If not found, create a new Airtable record

For linked record fields (e.g., linking an Event to its Body), you need to look up the Airtable record ID for the linked record using the Legistar foreign key. For example, to link an Event to its Body, find the Airtable record in the Bodies table where BodyId matches the Event's EventBodyId, then use that Airtable record ID in the link field.

### Airtable API considerations

- Airtable's REST API allows batch creates/updates of up to **10 records per request**
- Rate limit: **5 requests per second per base**
- For large initial syncs, build in delays between batches
- Use the `filterByFormula` parameter to look up records by their Legistar ID: `filterByFormula=({BodyId}=123)`

---

## Transcript pipeline

### Phase 1: YouTube auto-captions (start here)

1. Use the YouTube Data API to list videos from the city's channel (channel: `CCTVCorpusChristi`, URL: `https://www.youtube.com/user/CCTVCorpusChristi`)
2. Match videos to Events by date and title
3. Use the `youtube-transcript-api` Python library to pull auto-generated captions (no API key required for this library)
4. Store the transcript text in the Transcripts table linked to the matching Event
5. Set TranscriptSource to "YouTube Auto-Captions"

**Limitations of YouTube auto-captions:**
- No speaker identification (just a stream of timestamped text)
- Names, local terminology, and technical jargon may be inaccurate
- Quality is generally decent for formal meeting settings with clear audio

### Phase 2: AI transcription (future upgrade)

For higher quality and speaker diarization, download audio from YouTube and run through:
- **OpenAI Whisper** — free, open source, very accurate, runs locally or via API. No built-in speaker diarization but can pair with `pyannote-audio`.
- **AssemblyAI** — paid API with excellent built-in speaker diarization and entity detection.
- **Deepgram** — similar to AssemblyAI, fast with speaker labels.

Council member names from the Persons table can be fed into transcription services to improve name accuracy.

---

## City of Corpus Christi specifics

- **Legistar client name**: `corpuschristi`
- **YouTube channel**: CCTVCorpusChristi (`https://www.youtube.com/user/CCTVCorpusChristi`)
- **Granicus archived video**: `https://corpuschristi.granicus.com/ViewPublisher.php?view_id=13` (older meetings, pre-YouTube)
- **Legistar public site**: `https://corpuschristi.legistar.com/`
- **City website agendas page**: `https://www.corpuschristitx.gov/department-directory/city-secretary/agendas-and-minutes/`
- Council meetings are typically held on Tuesdays
- The city streams meetings live on YouTube and CCTV (AT&T Uverse Ch. 99, Grande Ch. 20, Spectrum Ch. 1300)
- Archived agendas, minutes, and video from October 2006 through December 2014 are in a separate archived section on Legistar
- Meeting videos can run 2-4+ hours

---

## Technology choices

- **Runtime**: Node.js
- **Key packages**: axios (HTTP), airtable (Airtable SDK), dotenv (env vars)
- **Transcript extraction**: youtube-transcript-api (Python library — may require a separate Python script or subprocess call from Node)
- **Version control**: Git + GitHub
- **Sync scheduling**: TBD — options include Airtable Automations (for lightweight triggers), n8n/Pipedream (for more robust scheduling), or cron/Task Scheduler running locally

---

## Open decisions and future considerations

- **Sync scheduling tool**: Not yet decided. Airtable Automations have a **30-second timeout** for scripts, so complex syncs may need to run externally.
- **Transcript segmentation**: Currently storing full transcript text in one field. May later add a Transcript Segments table with timestamped, searchable chunks if needed for analysis.
- **Meeting-to-video matching**: Need to develop logic for matching YouTube videos to Event records (likely by date + body name in the video title).
- **Historical backfill depth**: How far back to sync — all available data, or starting from a specific year.
- **Error handling and logging**: Need a strategy for handling API failures, partial syncs, and data quality issues.
