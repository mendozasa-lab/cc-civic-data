# CC Civic Data — Development Diary

Append-only log of decisions, discoveries, and open questions. Never edit past entries — add new ones instead.

Entry template:
```
## YYYY-MM-DD — [Short title]
**Context:** What problem or question prompted this.
**Decision:** What was decided.
**Alternatives considered:** What else was on the table and why it was rejected.
**Open questions / follow-up:** Anything deferred or still unresolved.
```

---

## 2026-04-03 — Project scaffolding and documentation strategy

**Context:** Starting the project fresh in VS Code / Claude Code after initial planning was done in Claude.ai web. Needed to establish a documentation strategy that would give Claude persistent context across sessions without re-explaining the project every time.

**Decision:** Use three layers of documentation:
1. `CLAUDE.md` (project root) — auto-loaded by Claude Code every session; kept concise; covers current conventions, architecture, and critical API behaviors
2. `docs/` — detailed reference docs that Claude reads on demand (`legistar-api.md`, `airtable-scripting-api.md`, `10-project-context-for-claude-code.md`)
3. `docs/dev-diary.md` (this file) — append-only log of decisions and discoveries

**Alternatives considered:** Putting everything in CLAUDE.md. Rejected because a large CLAUDE.md wastes context window on content that isn't relevant to every task.

**Open questions / follow-up:** None.

---

## 2026-04-03 — Airtable base setup approach

**Context:** Needed to initialize the Airtable base with 8 tables and all their fields.

**Decision:** Write a one-time setup script (`scripts/airtable-setup.js`) that runs in the Airtable scripting extension. Used `base.createTableAsync()` in dependency order so linked record fields have their target tables available. Captured returned table IDs (strings, not table objects) to use in subsequent `multipleRecordLinks` field definitions.

**Alternatives considered:** Creating tables manually in the Airtable UI. Rejected because a script is repeatable, reviewable, and documents the intended schema precisely.

**Open questions / follow-up:** Three fields in the Transcripts table (`TranscriptId`, `YouTubeURL`, `TranscriptWordCount`) must be added manually because `autoNumber` and `formula` field types cannot be created via the scripting API. Noted in script comments and CLAUDE.md.

---

## 2026-04-03 — Legistar API documentation method

**Context:** Needed accurate field-level documentation for the Legistar API before writing sync scripts.

**Decision:** Fetched live responses from `webapi.legistar.com` for each endpoint using real Corpus Christi data rather than relying on Claude's training data or pasting static docs. Captured actual field names, types, and null behaviors. Saved to `docs/legistar-api.md`.

**Alternatives considered:** Using the Legistar Help docs at `webapi.legistar.com/Help`. Those docs exist but don't capture real-world field behaviors (which fields are actually null, which values appear in practice, etc.). Live responses are more reliable.

**Key discoveries from live fetch:**
- `$orderby` returns HTTP 400 on some fields — cannot be relied upon
- `MatterLastModifiedUtc` can be null on older records
- Votes have no top-level endpoint — must be fetched as `/EventItems/{id}/Votes`
- `MatterId` is not included in the Attachments response — must be tracked from parent loop
- `EventDate` includes a bogus `T00:00:00` time component — real time is in the separate `EventTime` string

**Open questions / follow-up:** Haven't yet verified the `/BodyTypes`, `/Actions`, or `/Matters/{id}/Histories` endpoints with live data. Do so before writing sync scripts that use them.

---

## 2026-04-03 — Airtable scripting API documentation

**Context:** Planning to write many Airtable extension and automation scripts. Needed reliable API documentation so Claude wouldn't guess at field type strings or options schemas.

**Decision:** Pasted all 15 pages of the Airtable scripting API docs into the session and saved them to `docs/airtable-scripting-api.md`. Also added the critical extension-vs-automation distinction to `CLAUDE.md` so it's available in every session without reading the full doc.

**Key discoveries:**
- `base.createTableAsync()` returns a `string` (table ID), not a Table object
- `input.config()` is completely different in extensions vs. automations — different signatures, different purposes
- `output.set()` (automations) vs. `output.text/markdown()` (extensions) — no overlap
- `input.secret()` is automations only — the right pattern for API keys in automation scripts
- Automation scripts have a 30-second execution timeout — complex syncs cannot run as Airtable automations

**Open questions / follow-up:** None for now. Revisit if the Airtable scripting API changes materially.

---

## 2026-04-03 — All scripts run inside Airtable (correction to initial assumption)

**Context:** Initial project scaffolding included Node.js, axios, and the Airtable SDK, implying sync scripts would run externally. Clarified that all scripts — including Legistar sync — will run inside Airtable as extensions or automations.

**Decision:** Use Airtable's scripting environment for everything. Legistar API calls use `fetch`/`remoteFetchAsync`. Airtable reads/writes use scripting globals (`base`, `table`, etc.). No external runtime, no credentials, no `.env`.

**Implications:**
- Initial bulk syncs must run as **extensions** (manual) due to the 30-second automation timeout
- Incremental/triggered syncs can run as automations once the backfill is done
- The Node.js scaffolding in `scripts/` and `package.json` is vestigial — not used for Airtable work

**Open questions / follow-up:** Decide whether to keep or remove the Node.js scaffolding. It's not harmful but could be confusing.

---

## 2026-04-03 — Actual record counts from initial sync (Bodies + Persons)

**Context:** Running the first two sync scripts revealed actual record counts, which differed significantly from estimates.

**Findings:**
- Bodies: 51 records (matched estimate)
- Persons: 5,008 records (estimated 330 — off by 15x)
- Persons hit the 1,000-record Legistar page cap on the first run, silently truncating results. Pagination was added and the full dataset was retrieved on the second run.
- Persons likely includes all staff, contractors, and historical figures — not just elected officials.

**Running record count:** ~5,059 / 50,000 Airtable limit used after two tables.

**Implications:** Earlier estimates for total records are unreliable. Monitor the running total as each table is synced. If the limit becomes a concern, Persons could be filtered to active records or those with vote history.

**Open questions / follow-up:** Revisit record limit headroom after Matters and Events are synced — those are the next largest tables.

---

## 2026-04-03 — Multi-base strategy for managing record limits

**Context:** After syncing Bodies (51), Persons (5,008), and Matters (16,204), the running total hit 21,263 / 50,000 records. Remaining tables — especially Matter Attachments and Votes — threatened to exceed the limit.

**Decision:** Duplicate the base and use copies to sync remaining tables in full, explore what data is actually needed, and determine sensible date cutoffs. The primary base will only receive data that's actively useful. A future "slim" base may hold only what's needed for short-term work.

**Alternatives considered:** Filtering Persons to active-only, skipping Matter Attachments, upgrading plan. All deferred — explore first, decide later.

**Open questions / follow-up:** After exploring the duplicate bases, decide which tables and date ranges belong in the primary base.

---

## 2026-04-03 — Session 1 sync progress summary

Completed: Bodies, Persons, Matters sync scripts. All working and verified with re-runs.

Key patterns established (now documented in CLAUDE.md):
- `remoteFetchAsync` required for Legistar (CORS)
- Pagination required on all endpoints (hit the 1000-record wall on Persons)
- `syncSelectChoices` helper for singleSelect fields
- `toDateString` / `toUtcString` / `emptyToNull` utility functions

Remaining scripts to write: Events, Matter Attachments, Event Items, Votes.

---

## 2026-04-03 — Sync script technology choices

**Context:** Needed to choose a runtime and HTTP/Airtable libraries for the Node.js sync scripts.

**Decision:** Node.js with axios (HTTP), the official `airtable` SDK (REST API), and dotenv. These were established in the initial planning session on Claude.ai web and carried over.

**Alternatives considered:** Python. Rejected for the sync scripts because the project owner is more comfortable with JavaScript. Python may still be used for transcript extraction (`youtube-transcript-api` doesn't have a Node equivalent).

**Open questions / follow-up:**
- Sync scheduling tool not yet decided. Options: Airtable Automations (limited by 30s timeout), n8n/Pipedream, or local cron/Task Scheduler. Decision needed before writing the incremental sync.
- Historical backfill depth not decided — sync everything, or start from a specific year?
- Error handling and logging strategy not yet designed.

---

## 2026-04-04 — All Legistar tables synced to Airtable

All 9 tables fully synced. Final record counts:
- Bodies: 51 | Persons: 5,008 | Matters: 9,795 | Events: 1,398
- Matter Attachments: 21,305 (~50 fetch errors skipped)
- Event Items: 29,749 (136 matter links unresolved — pre-2020)
- Votes: 42,579 (~105 fetch errors skipped)
- Office Records: 1,004
- **Total: ~111,069 / 125,000 Airtable record limit**

**Key discovery — VoteId is not globally unique.** Legistar assigns one VoteId per person per meeting; the same VoteId appears on every agenda item that person voted on that day. The true unique key is `(VoteId, EventItemId)`. This was discovered when the initial migration to Supabase failed with a duplicate key conflict.

---

## 2026-04-04 — Architecture pivot: Airtable → Supabase + Streamlit

**Context:** Planning the transcription pipeline revealed that Transcript Segments (one record per speaker turn, ~300-600 per meeting × 637 meetings ≈ 255k records) would far exceed the Airtable Business plan limit of 125k. Upgrading Airtable wasn't acceptable. The project goal is a **public-facing civic data app**, which Airtable's sharing model doesn't support well.

**Decision:** Migrate all data to Supabase (PostgreSQL, free tier, unlimited rows) and build a public Streamlit app. Airtable is retired as the primary data store.

**Implications:**
- Legistar sync scripts will be rewritten in Python (structurally identical logic, different syntax)
- Scheduled syncs will use GitHub Actions (free on public repos) instead of Airtable automations
- Manual data edits use Supabase's Table Editor (equivalent to Airtable grid view)
- The existing JavaScript sync scripts in `scripts/` remain as reference implementations

**Alternatives considered:**
- Multiple Airtable bases with cross-base sync: messy linked records, still Airtable-constrained
- Upgrading to Airtable Enterprise: cost-prohibitive
- Keeping Airtable for Legistar + Supabase only for transcripts: two systems to maintain

**Open questions / follow-up:** Python sync scripts not yet written. GitHub Actions workflow not yet configured. Transcription pipeline planning deferred until app foundation is stable.

---

## 2026-04-04 — Supabase schema design: composite PK on votes

**Context:** Discovered during migration that VoteId is not a unique identifier (see above). Initial schema used `vote_id INTEGER PRIMARY KEY`, which caused a constraint violation during upsert.

**Decision:** Changed votes primary key to `PRIMARY KEY (vote_id, event_item_id)`. This matches Legistar's actual data model where a vote record is uniquely identified by the combination of the person's meeting-level vote ID and the specific agenda item.

---

## 2026-04-04 — Airtable → Supabase migration: field name bug in matter_attachments

**Context:** After migration, `attachment_name` and `attachment_hyperlink` columns in Supabase were null for all records.

**Cause:** The migration script used Legistar source field names (`MatterAttachmentName`, `MatterAttachmentHyperlink`) instead of the Airtable field names (`AttachmentName`, `AttachmentHyperlink`). The Airtable scripting API strips the `Matter` prefix when storing these fields.

**Fix:** Updated field references in `scripts/migrate_to_supabase.py` to use Airtable field names.

---

## 2026-04-05 — Streamlit prototype: council member profiles live

**Context:** First working version of the public Streamlit app built against Supabase.

**What's working:**
- Council member list in sidebar (sourced from office_records + bodies join, filtered to City Council body)
- Profile header: name, current title, term dates, email
- Vote metrics: total votes, Aye %, Nay count, Absent count
- Voting breakdown pie chart (Plotly)
- Vote history table with keyword search
- Term history expander

**Key bugs fixed during this session:**
1. Supabase default row limit of 1000 silently truncating vote counts — fixed with `fetch_all()` pagination helper that pages through results in chunks of 1000 until exhausted
2. `load_council_members` also needed pagination (1004 office records > 1000 default)

**Stack:** Streamlit (UI) + supabase-py (data) + Plotly (charts) + Pandas (data manipulation). Files in `streamlit_app/`.

**Open questions / follow-up:**
- Transcription pipeline not yet started (service choice: ElevenLabs Scribe v2 selected for best accuracy)
- Python Legistar sync scripts not yet written (will replace Airtable JS scripts)
- GitHub Actions scheduling not yet configured
- Additional app pages (meetings, vote explorer, matters browser) not yet built
- Streamlit Community Cloud deployment not yet done

---

## 2026-04-09 — ElevenLabs async pipeline, webhook, entity detection, keyterms, R2 storage

**Context:** Multiple transcription attempts failed due to: synchronous ElevenLabs submission timing out on long recordings, wrong API parameter names, Supabase Storage 50MB file size limit, and Claude returning prose instead of JSON for auto-map speakers.

**Decisions and fixes:**

1. **Cloudflare R2 for audio storage** — replaced Supabase Storage (50MB limit) with R2 (10GB free tier). Audio files are uploaded as `event_{eid}.mp3` and the public URL is saved to `transcripts.audio_url`. If audio is already in R2 on retry, upload is skipped.

2. **ElevenLabs async + webhook flow** — replaced synchronous polling (which times out on 4–9 hour recordings) with async submission (`webhook=true`). ElevenLabs returns `transcription_id` immediately and POSTs the full result to our Supabase Edge Function when done. `transcription_id` is saved to DB immediately so crash recovery is possible.

3. **ElevenLabs correct parameters** — correct param for R2 URL is `cloud_storage_url` (not `url`, `audio_url`, or `file_url`). `webhook=true` requires a webhook configured in the ElevenLabs workspace dashboard with an HTTPS callback URL.

4. **Supabase Edge Function** — `supabase/functions/elevenlabs-webhook/index.ts` (Deno/TypeScript): verifies HMAC signature, converts words→segments, maps entity char offsets→segment_id, inserts `transcript_segments` and `transcript_entities`, marks transcript complete, dispatches `map_speakers` GitHub Actions workflow via GitHub API.

5. **Entity detection** — added `entity_detection=pii` to ElevenLabs submission. New `transcript_entities` table stores detected entities (person names, organizations, etc.) with char offsets and segment references. Enables cross-meeting queries like "find all meetings where X was mentioned."

6. **Keyterm prompting** — added dynamic keyterms (active council member names from Supabase) + hardcoded `SUPPLEMENTAL_KEYTERMS` (water crisis proper nouns: Choke Canyon, Acciona Agua, TCEQ, curtailment, brine discharge, etc.). 63 terms total on first test.

7. **Auto-map speakers JSON fix** — claude-opus-4-6 doesn't support assistant prefill. Switched to forced tool use (`tool_choice={"type":"tool","name":"submit_speaker_mappings"}`) to guarantee JSON output. Also added pre-filtering of labels with both `short_time` + `early_only` flags (likely public commenters) and batching (30 labels per Claude call) to avoid hitting token limits.

8. **Full ElevenLabs API docs** — `docs/elevenlabs-api.md` rewritten with correct parameters, all endpoints, webhook setup, keyterm/entity guidance, and realtime streaming reference.

**Infrastructure added:**
- Cloudflare R2 bucket `cc-civic-audio` (public URL: `https://pub-b1d9e555223a4dd3ae4aeea0d7570cc1.r2.dev`)
- Supabase Edge Function `elevenlabs-webhook` deployed
- `transcript_entities` table in Supabase
- New GitHub secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `ELEVENLABS_WEBHOOK_ID`
- New Supabase secrets: `ELEVENLABS_WEBHOOK_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_PAT`

**First successful async submission:** event_id=4111, transcript_id=3, ElevenLabs transcription_id=`mK9OUZsMvaU7IdlOZ6G5`

**Known open issue — event 4086:** Has had repeated ElevenLabs failures. History API is TTS-only and can't help. Need `transcription_id` from ElevenLabs support → recover via `python transcribe.py --event-id 4086 --elevenlabs-id <id>`.

**Open questions / follow-up:**
1. **Legistar sync workflow** — no GitHub Actions workflow exists to pull new events. City council meeting tomorrow (2026-04-10). Need on-demand Legistar sync script urgently.
2. **Transcription notifications** — want push notifications after ElevenLabs webhook fires and after auto-map speakers completes. Plan: ntfy.sh or similar, added to Edge Function and map_speakers workflow.
3. Verify webhook actually fires and segments are inserted for event 4111 (check Edge Function logs).

---

## 2026-04-10 — Event 4111 recovery, entity import, staff speaker mapping

**Context:** Event 4111 (9-hour meeting) was submitted to ElevenLabs async but the webhook never fired — Supabase Edge Function logs showed zero invocations. ElevenLabs had completed transcription (180,060 words). Recovered via crash recovery path. Also discovered speaker mapping was missing key staff.

**What happened with the webhook:** The transcription completed on ElevenLabs' side but the webhook did not fire — likely a misconfiguration of the `webhook_id` or the webhook URL in the ElevenLabs workspace dashboard. Need to verify the webhook URL matches the deployed Edge Function URL and test with a new submission.

**Decisions and fixes:**

1. **Crash recovery for event 4111** — ran `python transcribe.py --event-id 4111 --elevenlabs-id mK9OUZsMvaU7IdlOZ6G5`. Inserted 3,175 segments. Duration was 32,406s (~9 hrs), cost $3.60.

2. **Entity import script** — `_poll_and_insert` in `transcribe.py` was silently dropping entities on the crash recovery path. Fixed in two ways:
   - `_poll_and_insert` now also fetches `entities` from the ElevenLabs response and inserts them, rebuilding char offsets from the already-inserted segments to map to `segment_id`s
   - New `scripts/transcription/import_entities.py` — one-shot script for backfilling entities on transcripts that went through crash recovery before the fix. Used it to insert 2,039 entities for event 4111.

3. **Named staff in speaker mapping** — `load_roster()` only queried city council members, so Claude had no `person_id` for key staff like City Manager. Fixed:
   - `load_roster()` now returns `(council, staff)` tuple — staff comes from office_records with titles City Manager/City Secretary/City Attorney, plus a hardcoded `NAMED_STAFF` supplement
   - Peter Zanoni (person_id=820, City Manager) has **no office_records in Legistar at all** — added to `NAMED_STAFF` hardcoded list
   - Rebecca Huerta (person_id=179, City Secretary) is in Legistar with an open-ended record — picked up automatically
   - Claude prompt updated to show staff with person_ids and treat them same as council for auto-apply

4. **manage_named_staff workflow** — new GitHub Actions workflow (`manage_named_staff.yml`) + script (`manage_named_staff.py`) for adding people to `NAMED_STAFF` without editing code manually:
   - Run with name only → logs matching persons + person_ids
   - Run with name + person_id + title → edits `auto_map_speakers.py` and commits to main

5. **Entity detection not integrated into speaker mapping** — discussed and decided against it. Current regex-based name detection in `detect_name_evidence()` provides equivalent signal. Real gap was missing person_ids for staff, not missing name detection. Entities are better used in Streamlit search/analytics.

**Open questions / follow-up:**
1. **Legistar sync workflow** — still needed urgently (city council meeting today 2026-04-10). No GitHub Actions workflow exists to pull new events/items/votes.
2. **Transcription notifications** — ntfy.sh or similar, after webhook fires and after map_speakers completes.
3. **Verify webhook** — submit a new transcription and confirm the Edge Function actually receives the callback. Check webhook URL and `webhook_id` in ElevenLabs dashboard.
4. **Re-run map_speakers for event 4111** — needs another run now that Zanoni is in the staff roster.
