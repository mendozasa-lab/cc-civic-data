// =============================================================================
// Event Items Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by EventItemId).
// Fetches event items for every Event already in Airtable. No date prompt —
// scope is determined by which events are present in the Events table.
//
// Event items are a sub-resource: /Events/{EventId}/EventItems
// One Legistar call is made per event (~1,400 calls total).
// Resolves linked records for Event and Matter.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;
const PROGRESS_INTERVAL = 100;

function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// ---------------------------------------------------------------------------
// Fetch all event items for a single event. Returns [] on 404 or error.
// ---------------------------------------------------------------------------
async function fetchEventItems(eventId) {
  const url = `${LEGISTAR_BASE}/Events/${eventId}/EventItems`;
  const response = await remoteFetchAsync(url);
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`Legistar error ${response.status}: ${url}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Ensure all values in `values` exist as choices on `fieldName`.
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
const table = base.getTable('Event Items');
const eventsTable = base.getTable('Events');
const mattersTable = base.getTable('Matters');

output.text('Step 1/7 — Loading Events from Airtable...');
const eventsQuery = await eventsTable.selectRecordsAsync({ fields: ['EventId'] });
const events = eventsQuery.records
  .map(r => ({ airtableId: r.id, eventId: r.getCellValue('EventId') }))
  .filter(e => e.eventId !== null);
output.text(`  Loaded ${events.length} event records.`);

output.text('Step 2/7 — Loading Matters from Airtable...');
const mattersQuery = await mattersTable.selectRecordsAsync({ fields: ['MatterId'] });
const matterIdToRecordId = new Map();
for (const r of mattersQuery.records) {
  const id = r.getCellValue('MatterId');
  if (id !== null) matterIdToRecordId.set(id, r.id);
}
output.text(`  Loaded ${matterIdToRecordId.size} matter records.`);

output.text('Step 3/7 — Fetching event items from Legistar (one call per event)...');
const allItems = []; // { eventAirtableId, ...item }
let fetchErrors = 0;

for (let i = 0; i < events.length; i++) {
  const { airtableId, eventId } = events[i];

  try {
    const items = await fetchEventItems(eventId);
    for (const item of items) {
      allItems.push({ eventAirtableId: airtableId, ...item });
    }
  } catch (err) {
    fetchErrors++;
    output.text(`  Error fetching event ${eventId}: ${err.message}`);
  }

  if ((i + 1) % PROGRESS_INTERVAL === 0 || i + 1 === events.length) {
    output.text(`  Processed ${i + 1} / ${events.length} events — ${allItems.length} items so far.`);
  }
}

output.text(`  Done. ${allItems.length} total event items found.`);
if (fetchErrors > 0) {
  output.text(`  Warning: ${fetchErrors} event(s) had fetch errors and were skipped.`);
}

output.text('Step 4/7 — Syncing select field choices...');
await syncSelectChoices('EventItemResult', allItems.map(i => i.EventItemPassedFlagName));

output.text('Step 5/7 — Loading existing Event Item records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['EventItemId'] });
const existingByItemId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('EventItemId');
  if (id !== null) existingByItemId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByItemId).length} existing records.`);

output.text('Step 6/7 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];
let missingMatters = 0;

for (const item of allItems) {
  const matterRecordId = item.EventItemMatterId
    ? matterIdToRecordId.get(item.EventItemMatterId)
    : null;

  if (item.EventItemMatterId && !matterRecordId) missingMatters++;

  const fields = {
    'EventItemId':          item.EventItemId,
    'Event':                [{ id: item.eventAirtableId }],
    'Matter':               matterRecordId ? [{ id: matterRecordId }] : null,
    'EventItemTitle':       item.EventItemTitle || '',
    'EventItemAgendaNumber': item.EventItemAgendaSequence ?? null,
    'EventItemActionName':  item.EventItemActionName || '',
    'EventItemResult':      item.EventItemPassedFlagName ? { name: item.EventItemPassedFlagName } : null,
    'EventItemAgendaNote':  item.EventItemAgendaNote || '',
    'EventItemMinutesNote': item.EventItemMinutesNote || '',
    'EventItemLastModified': toUtcString(item.EventItemLastModifiedUtc),
  };

  if (existingByItemId[item.EventItemId]) {
    toUpdate.push({ id: existingByItemId[item.EventItemId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);
if (missingMatters > 0) {
  output.text(`  Note: ${missingMatters} item(s) referenced a Matter not in Airtable — Matter field left blank.`);
}

output.text('Step 7/7 — Writing to Airtable...');

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
