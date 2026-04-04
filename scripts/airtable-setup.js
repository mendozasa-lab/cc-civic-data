// =============================================================================
// Corpus Christi Civic Data — Airtable Base Setup Script
// =============================================================================
// Run this once in an Airtable scripting extension to initialize all tables.
//
// AFTER RUNNING, add these fields manually in the Airtable UI:
//   Transcripts > TranscriptId
//     Type: Auto number
//   Transcripts > YouTubeURL
//     Type: Formula
//     Formula: IF({YouTubeVideoId}, "https://www.youtube.com/watch?v=" & {YouTubeVideoId}, "")
//   Transcripts > TranscriptWordCount
//     Type: Formula
//     Formula: IF({TranscriptFullText}, LEN(SUBSTITUTE({TranscriptFullText}, " ", "x")) - LEN(SUBSTITUTE({TranscriptFullText}, " ", "")) + 1, 0)
// =============================================================================

// --- Field definition helpers ------------------------------------------------

const int      = (name) => ({ name, type: 'number',            options: { precision: 0 } });
const text     = (name) => ({ name, type: 'singleLineText' });
const longText = (name) => ({ name, type: 'multilineText' });
const check    = (name) => ({ name, type: 'checkbox',          options: { icon: 'check', color: 'greenBright' } });
const email    = (name) => ({ name, type: 'email' });
const phone    = (name) => ({ name, type: 'phoneNumber' });
const url      = (name) => ({ name, type: 'url' });

const date = (name) => ({
    name, type: 'date',
    options: { dateFormat: { name: 'iso' } },
});

const dateTime = (name) => ({
    name, type: 'dateTime',
    options: {
        dateFormat: { name: 'iso' },
        timeFormat: { name: '12hour' },
        timeZone: 'America/Chicago',
    },
});

const select = (name, choices) => ({
    name, type: 'singleSelect',
    options: { choices: choices.map(c => ({ name: c })) },
});

const link = (name, linkedTableId) => ({
    name, type: 'multipleRecordLinks',
    options: { linkedTableId },
});

// --- Phase 1: Foundation tables (no linked record fields) --------------------

output.text('Phase 1: Creating foundation tables...');

const bodiesId = await base.createTableAsync('Bodies', [
    int('BodyId'),
    text('BodyName'),
    select('BodyType', ['Legislative Body', 'Board', 'Commission', 'Committee', 'Corporation', 'Other']),
    longText('BodyDescription'),
    check('BodyActiveFlag'),
    text('BodyMeetDay'),
    text('BodyMeetTime'),
    text('BodyMeetLocation'),
    dateTime('BodyLastModified'),
]);
output.text('  ✓ Bodies');

const personsId = await base.createTableAsync('Persons', [
    int('PersonId'),
    text('PersonFullName'),
    text('PersonFirstName'),
    text('PersonLastName'),
    email('PersonEmail'),
    phone('PersonPhone'),
    check('PersonActiveFlag'),
    dateTime('PersonLastModified'),
]);
output.text('  ✓ Persons');

const mattersId = await base.createTableAsync('Matters', [
    int('MatterId'),
    text('MatterFile'),
    text('MatterName'),
    longText('MatterTitle'),
    select('MatterType', ['Ordinance', 'Resolution', 'Presentation', 'Motion', 'Report', 'Agreement', 'Minutes', 'Other']),
    select('MatterStatus', ['Introduced', 'Passed', 'Failed', 'Withdrawn', 'Tabled', 'Referred', 'Adopted', 'Other']),
    text('MatterBodyName'),
    date('MatterIntroDate'),
    date('MatterAgendaDate'),
    date('MatterPassedDate'),
    text('MatterEnactmentNumber'),
    dateTime('MatterLastModified'),
]);
output.text('  ✓ Matters');

// --- Phase 2: Tables that link to Phase 1 ------------------------------------

output.text('Phase 2: Creating tables with foundation links...');

const eventsId = await base.createTableAsync('Events', [
    int('EventId'),
    link('Body', bodiesId),
    date('EventDate'),
    text('EventTime'),
    text('EventLocation'),
    url('EventAgendaFile'),
    url('EventMinutesFile'),
    url('EventInSiteURL'),
    url('EventVideoPath'),
    select('EventAgendaStatus',  ['Final', 'Draft', 'Not Available']),
    select('EventMinutesStatus', ['Final', 'Draft', 'Not Available']),
    dateTime('EventLastModified'),
]);
output.text('  ✓ Events');

const matterAttachmentsId = await base.createTableAsync('Matter Attachments', [
    int('AttachmentId'),
    link('Matter', mattersId),
    text('AttachmentName'),
    url('AttachmentHyperlink'),
    check('AttachmentIsSupporting'),
    dateTime('AttachmentLastModified'),
]);
output.text('  ✓ Matter Attachments');

// --- Phase 3: Tables that link to Phase 2 ------------------------------------

output.text('Phase 3: Creating tables with Phase 2 links...');

const eventItemsId = await base.createTableAsync('Event Items', [
    int('EventItemId'),
    link('Event', eventsId),
    link('Matter', mattersId),
    longText('EventItemTitle'),
    int('EventItemAgendaNumber'),
    text('EventItemActionName'),
    select('EventItemResult', ['Pass', 'Fail', 'Withdrawn', 'Tabled', 'Received and Filed', 'No Action', 'Other']),
    longText('EventItemAgendaNote'),
    longText('EventItemMinutesNote'),
    dateTime('EventItemLastModified'),
]);
output.text('  ✓ Event Items');

// Note: TranscriptId (autoNumber), YouTubeURL (formula), and TranscriptWordCount (formula)
// cannot be created via scripting. See manual steps at the top of this file.
// YouTubeVideoId is placed first to serve as the primary field.
const transcriptsId = await base.createTableAsync('Transcripts', [
    text('YouTubeVideoId'),
    link('Event', eventsId),
    select('TranscriptSource', ['YouTube Auto-Captions', 'Whisper AI', 'AssemblyAI', 'Manual', 'Other']),
    longText('TranscriptFullText'),
    select('TranscriptStatus', ['Pending', 'Complete', 'Failed', 'Needs Review']),
    dateTime('TranscriptCreated'),
]);
output.text('  ✓ Transcripts (3 fields need manual addition — see top of script)');

// --- Phase 4: Tables that link to Phase 3 ------------------------------------

output.text('Phase 4: Creating tables with Phase 3 links...');

await base.createTableAsync('Votes', [
    int('VoteId'),
    link('Event Item', eventItemsId),
    link('Person', personsId),
    text('VotePersonName'),
    select('VoteValueName', ['Aye', 'Nay', 'Abstain', 'Absent', 'Recused', 'Present']),
    select('VoteResult', ['Pass', 'Fail']),
    dateTime('VoteLastModified'),
]);
output.text('  ✓ Votes');

// --- Done --------------------------------------------------------------------

output.text('');
output.text('=== Setup complete! All 8 tables created. ===');
output.text('');
output.text('ACTION REQUIRED — Add these 3 fields manually in the Airtable UI:');
output.text('');
output.text('  Table: Transcripts');
output.text('  1. TranscriptId — Auto number');
output.text('  2. YouTubeURL — Formula:');
output.text('     IF({YouTubeVideoId}, "https://www.youtube.com/watch?v=" & {YouTubeVideoId}, "")');
output.text('  3. TranscriptWordCount — Formula:');
output.text('     IF({TranscriptFullText}, LEN(SUBSTITUTE({TranscriptFullText}, " ", "x")) - LEN(SUBSTITUTE({TranscriptFullText}, " ", "")) + 1, 0)');
