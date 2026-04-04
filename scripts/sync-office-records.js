// =============================================================================
// Office Records Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by OfficeRecordId).
// Fetches all office records (no date filter — full history is meaningful here,
// as tenure dates tell you who held which seat and when).
// Resolves linked records for Person and Body.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;

function toDateString(ts) {
  if (!ts) return null;
  return ts.split('T')[0];
}

function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// ---------------------------------------------------------------------------
// Fetch all Office Records from Legistar (paginated).
// ---------------------------------------------------------------------------
async function fetchOfficeRecords() {
  const all = [];
  let skip = 0;
  const top = 1000;

  while (true) {
    const url = `${LEGISTAR_BASE}/OfficeRecords?$top=${top}&$skip=${skip}`;
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
const table = base.getTable('Office Records');
const personsTable = base.getTable('Persons');
const bodiesTable  = base.getTable('Bodies');

output.text('Step 1/6 — Fetching office records from Legistar...');
const legistarRecords = await fetchOfficeRecords();
output.text(`  Found ${legistarRecords.length} office records.`);

output.text('Step 2/6 — Syncing select field choices...');
await syncSelectChoices('OfficeRecordTitle',      legistarRecords.map(r => r.OfficeRecordTitle));
await syncSelectChoices('OfficeRecordMemberType', legistarRecords.map(r => r.OfficeRecordMemberType));

output.text('Step 3/6 — Loading Persons and Bodies for linked record resolution...');
const personsQuery = await personsTable.selectRecordsAsync({ fields: ['PersonId'] });
const personIdToRecordId = new Map();
for (const r of personsQuery.records) {
  const id = r.getCellValue('PersonId');
  if (id !== null) personIdToRecordId.set(id, r.id);
}

const bodiesQuery = await bodiesTable.selectRecordsAsync({ fields: ['BodyId'] });
const bodyIdToRecordId = new Map();
for (const r of bodiesQuery.records) {
  const id = r.getCellValue('BodyId');
  if (id !== null) bodyIdToRecordId.set(id, r.id);
}
output.text(`  Loaded ${personIdToRecordId.size} persons, ${bodyIdToRecordId.size} bodies.`);

output.text('Step 4/6 — Loading existing Office Record records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['OfficeRecordId'] });
const existingById = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('OfficeRecordId');
  if (id !== null) existingById[id] = record.id;
}
output.text(`  Found ${Object.keys(existingById).length} existing records.`);

output.text('Step 5/6 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];
let missingPersons = 0;
let missingBodies = 0;

for (const rec of legistarRecords) {
  const personRecordId = personIdToRecordId.get(rec.OfficeRecordPersonId);
  const bodyRecordId   = bodyIdToRecordId.get(rec.OfficeRecordBodyId);

  if (!personRecordId) missingPersons++;
  if (!bodyRecordId)   missingBodies++;

  const fields = {
    'OfficeRecordId':           rec.OfficeRecordId,
    'Person':                   personRecordId ? [{ id: personRecordId }] : null,
    'Body':                     bodyRecordId   ? [{ id: bodyRecordId   }] : null,
    'OfficeRecordTitle':        rec.OfficeRecordTitle       ? { name: rec.OfficeRecordTitle }       : null,
    'OfficeRecordStartDate':    toDateString(rec.OfficeRecordStartDate),
    'OfficeRecordEndDate':      toDateString(rec.OfficeRecordEndDate),
    'OfficeRecordMemberType':   rec.OfficeRecordMemberType  ? { name: rec.OfficeRecordMemberType  } : null,
    'OfficeRecordLastModified': toUtcString(rec.OfficeRecordLastModifiedUtc),
  };

  if (existingById[rec.OfficeRecordId]) {
    toUpdate.push({ id: existingById[rec.OfficeRecordId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);
if (missingPersons > 0) output.text(`  Note: ${missingPersons} record(s) had no matching Person.`);
if (missingBodies  > 0) output.text(`  Note: ${missingBodies} record(s) had no matching Body.`);

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
