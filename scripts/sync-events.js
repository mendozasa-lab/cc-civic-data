// =============================================================================
// Events Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by EventId).
// Prompts for a start date and filters to events on or after that date.
// Paginates Legistar in pages of 1000 until all records are fetched.
// Resolves the Body linked record from the Bodies table.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;

// Legistar UTC timestamps — append 'Z' for Airtable dateTime fields.
function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// EventDate arrives as "2021-03-09T00:00:00" — strip the time component.
function toDateString(ts) {
  if (!ts) return null;
  return ts.split('T')[0];
}

// URL fields reject empty strings — return null instead.
function emptyToNull(val) {
  return val && val.trim() !== '' ? val.trim() : null;
}

// ---------------------------------------------------------------------------
// Fetch all Events from Legistar on or after startDate (YYYY-MM-DD).
// ---------------------------------------------------------------------------
async function fetchLegistarEvents(startDate) {
  const all = [];
  let skip = 0;
  const top = 1000;
  const filter = `EventDate ge datetime'${startDate}T00:00:00'`;

  while (true) {
    const url = `${LEGISTAR_BASE}/Events?$top=${top}&$skip=${skip}&$filter=${encodeURIComponent(filter)}`;
    const response = await remoteFetchAsync(url);
    if (!response.ok) throw new Error(`Legistar error ${response.status}: ${url}`);
    const page = await response.json();
    all.push(...page);
    if (page.length < top) break;
    skip += top;
  }

  return all;
}

// ---------------------------------------------------------------------------
// Ensure all values in `values` exist as choices on `fieldName`.
// Adds any missing ones in a single updateOptionsAsync call.
// ---------------------------------------------------------------------------
async function syncSelectChoices(fieldName, values) {
  const field = table.getField(fieldName);
  const existingNames = new Set(field.options.choices.map(c => c.name));

  const newChoices = [...new Set(values.filter(v => v && !existingNames.has(v)))]
    .map(name => ({ name }));

  if (newChoices.length === 0) {
    output.text(`  ${fieldName}: no new choices.`);
    return;
  }

  await field.updateOptionsAsync({
    choices: [...field.options.choices, ...newChoices],
  });
  output.text(`  ${fieldName}: added ${newChoices.length} choice(s): ${newChoices.map(c => c.name).join(', ')}`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const table = base.getTable('Events');
const bodiesTable = base.getTable('Bodies');

const startDate = await input.textAsync('Start date for sync (YYYY-MM-DD):');
if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate)) {
  throw new Error(`Invalid date format: "${startDate}". Expected YYYY-MM-DD (e.g. 2020-01-01).`);
}

output.text('Step 1/6 — Fetching events from Legistar...');
const legistarEvents = await fetchLegistarEvents(startDate);
output.text(`  Found ${legistarEvents.length} events (${startDate} onward).`);

output.text('Step 2/6 — Syncing select field choices...');
await syncSelectChoices('EventAgendaStatus',  legistarEvents.map(e => e.EventAgendaStatusName));
await syncSelectChoices('EventMinutesStatus', legistarEvents.map(e => e.EventMinutesStatusName));

output.text('Step 3/6 — Loading existing Events records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['EventId'] });
const existingByEventId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('EventId');
  if (id !== null) existingByEventId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByEventId).length} existing records.`);

output.text('Step 4/6 — Loading Bodies for linked record resolution...');
const bodiesQuery = await bodiesTable.selectRecordsAsync({ fields: ['BodyId'] });
const bodyIdToRecordId = new Map();
for (const record of bodiesQuery.records) {
  const id = record.getCellValue('BodyId');
  if (id !== null) bodyIdToRecordId.set(id, record.id);
}
output.text(`  Loaded ${bodyIdToRecordId.size} body records.`);

output.text('Step 5/6 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];
let missingBodies = 0;

for (const event of legistarEvents) {
  const bodyRecordId = bodyIdToRecordId.get(event.EventBodyId);
  if (!bodyRecordId) missingBodies++;

  const fields = {
    'EventId':            event.EventId,
    'Body':               bodyRecordId ? [{ id: bodyRecordId }] : null,
    'EventDate':          toDateString(event.EventDate),
    'EventTime':          event.EventTime || '',
    'EventLocation':      event.EventLocation || '',
    'EventAgendaFile':    emptyToNull(event.EventAgendaFile),
    'EventMinutesFile':   emptyToNull(event.EventMinutesFile),
    'EventInSiteURL':     emptyToNull(event.EventInSiteURL),
    'EventVideoPath':     emptyToNull(event.EventVideoPath),
    'EventMedia':         event.EventMedia ? String(event.EventMedia) : null,
    'EventAgendaStatus':  event.EventAgendaStatusName  ? { name: event.EventAgendaStatusName }  : null,
    'EventMinutesStatus': event.EventMinutesStatusName ? { name: event.EventMinutesStatusName } : null,
    'EventLastModified':  toUtcString(event.EventLastModifiedUtc),
  };

  if (existingByEventId[event.EventId]) {
    toUpdate.push({ id: existingByEventId[event.EventId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);
if (missingBodies > 0) {
  output.text(`  Warning: ${missingBodies} event(s) had no matching Body record — Body field left blank.`);
}

output.text('Step 6/6 — Writing to Airtable...');

for (let i = 0; i < toCreate.length; i += BATCH_SIZE) {
  const batch = toCreate.slice(i, i + BATCH_SIZE);
  await table.createRecordsAsync(batch);
  output.text(`  Created ${i + batch.length} / ${toCreate.length}`);
}

for (let i = 0; i < toUpdate.length; i += BATCH_SIZE) {
  const batch = toUpdate.slice(i, i + BATCH_SIZE);
  await table.updateRecordsAsync(batch);
  output.text(`  Updated ${i + batch.length} / ${toUpdate.length}`);
}

output.text('');
output.text(`✓ Done. ${toCreate.length} created, ${toUpdate.length} updated.`);
