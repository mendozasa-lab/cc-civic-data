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
