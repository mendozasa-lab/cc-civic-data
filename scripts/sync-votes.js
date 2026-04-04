// =============================================================================
// Votes Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by VoteId).
// Fetches votes for every Event Item already in Airtable. No date prompt —
// scope is determined by which event items are present in the Event Items table.
//
// Votes are a sub-resource: /EventItems/{EventItemId}/Votes
// There is no top-level /Votes endpoint. One Legistar call is made per event
// item — expect this to run for 20–40 minutes depending on item count.
// Most items will return [], as only roll-call votes have vote records.
// Resolves linked records for Event Item and Person.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;
const PROGRESS_INTERVAL = 500;

function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// ---------------------------------------------------------------------------
// Fetch all votes for a single event item. Returns [] on 404 or error.
// ---------------------------------------------------------------------------
async function fetchVotes(eventItemId) {
  const url = `${LEGISTAR_BASE}/EventItems/${eventItemId}/Votes`;
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
const table = base.getTable('Votes');
const eventItemsTable = base.getTable('Event Items');
const personsTable = base.getTable('Persons');

output.text('Step 1/7 — Loading Event Items from Airtable...');
const itemsQuery = await eventItemsTable.selectRecordsAsync({ fields: ['EventItemId'] });
const eventItems = itemsQuery.records
  .map(r => ({ airtableId: r.id, eventItemId: r.getCellValue('EventItemId') }))
  .filter(i => i.eventItemId !== null);
output.text(`  Loaded ${eventItems.length} event item records.`);

output.text('Step 2/7 — Loading Persons from Airtable...');
const personsQuery = await personsTable.selectRecordsAsync({ fields: ['PersonId'] });
const personIdToRecordId = new Map();
for (const r of personsQuery.records) {
  const id = r.getCellValue('PersonId');
  if (id !== null) personIdToRecordId.set(id, r.id);
}
output.text(`  Loaded ${personIdToRecordId.size} person records.`);

output.text('Step 3/7 — Fetching votes from Legistar (one call per event item)...');
output.text('  Note: most items have no roll-call vote — [] responses are normal.');
const allVotes = []; // { eventItemAirtableId, ...vote }
let fetchErrors = 0;

for (let i = 0; i < eventItems.length; i++) {
  const { airtableId, eventItemId } = eventItems[i];

  try {
    const votes = await fetchVotes(eventItemId);
    for (const vote of votes) {
      allVotes.push({ eventItemAirtableId: airtableId, ...vote });
    }
  } catch (err) {
    fetchErrors++;
    output.text(`  Error fetching event item ${eventItemId}: ${err.message}`);
  }

  if ((i + 1) % PROGRESS_INTERVAL === 0 || i + 1 === eventItems.length) {
    output.text(`  Processed ${i + 1} / ${eventItems.length} items — ${allVotes.length} votes so far.`);
  }
}

output.text(`  Done. ${allVotes.length} total votes found.`);
if (fetchErrors > 0) {
  output.text(`  Warning: ${fetchErrors} item(s) had fetch errors and were skipped.`);
}

output.text('Step 4/7 — Syncing select field choices...');
await syncSelectChoices('VoteValueName', allVotes.map(v => v.VoteValueName));
await syncSelectChoices('VoteResult',    allVotes.map(v => v.VoteResult === 1 ? 'Pass' : v.VoteResult === 0 ? 'Fail' : null));

output.text('Step 5/7 — Loading existing Vote records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['VoteId'] });
const existingByVoteId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('VoteId');
  if (id !== null) existingByVoteId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByVoteId).length} existing records.`);

output.text('Step 6/7 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];
let missingPersons = 0;

for (const vote of allVotes) {
  const personRecordId = vote.VotePersonId
    ? personIdToRecordId.get(vote.VotePersonId)
    : null;

  if (vote.VotePersonId && !personRecordId) missingPersons++;

  const voteResult = vote.VoteResult === 1 ? 'Pass' : vote.VoteResult === 0 ? 'Fail' : null;

  const fields = {
    'VoteId':           vote.VoteId,
    'Event Item':       [{ id: vote.eventItemAirtableId }],
    'Person':           personRecordId ? [{ id: personRecordId }] : null,
    'VotePersonName':   vote.VotePersonName || '',
    'VoteValueName':    vote.VoteValueName ? { name: vote.VoteValueName } : null,
    'VoteResult':       voteResult ? { name: voteResult } : null,
    'VoteLastModified': toUtcString(vote.VoteLastModifiedUtc),
  };

  if (existingByVoteId[vote.VoteId]) {
    toUpdate.push({ id: existingByVoteId[vote.VoteId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);
if (missingPersons > 0) {
  output.text(`  Note: ${missingPersons} vote(s) referenced a Person not in Airtable — Person field left blank.`);
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
