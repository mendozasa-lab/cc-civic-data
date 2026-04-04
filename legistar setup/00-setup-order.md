# Corpus Christi Civic Data — Setup Order Guide

## Create tables in this order:

The order matters because some tables link to others that need to exist first.

### Phase 1: Foundation tables (no dependencies)
1. **Bodies** — `01-bodies.md`
2. **Persons** — `02-persons.md`
3. **Matters** — `04-matters.md`

### Phase 2: Tables that link to foundation tables
4. **Events** — `03-events.md` (links to Bodies)
5. **Matter Attachments** — `07-matter-attachments.md` (links to Matters)

### Phase 3: Tables that link to Phase 2 tables
6. **Event Items** — `05-event-items.md` (links to Events and Matters)
7. **Transcripts** — `08-transcripts.md` (links to Events)

### Phase 4: Tables that link to Phase 3 tables
8. **Votes** — `06-votes.md` (links to Event Items and Persons)

## After all tables are created:

Verify these linked record relationships exist:
- Events → Bodies (each event belongs to one body)
- Event Items → Events (each item belongs to one meeting)
- Event Items → Matters (each item may reference one matter)
- Votes → Event Items (each vote is on one agenda item)
- Votes → Persons (each vote is cast by one person)
- Matter Attachments → Matters (each attachment belongs to one matter)
- Transcripts → Events (each transcript belongs to one meeting)

## Airtable views to create after setup:

Consider adding these views for usability:
- **Events**: Calendar view grouped by Body
- **Events**: Gallery view filtered to "EventMinutesStatus = Final"
- **Matters**: Grid view grouped by MatterType
- **Matters**: Grid view grouped by MatterStatus
- **Votes**: Grid view grouped by VoteValueName
- **Transcripts**: Grid view filtered to "TranscriptStatus = Complete"
