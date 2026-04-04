// =============================================================================
// Persons Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by PersonId).
// No date filter — Persons is a lookup table; we want everyone.
// Paginates Legistar in pages of 1000 until all records are fetched.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;

function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// Email and phone fields reject empty strings — return null instead.
function emptyToNull(val) {
  return val && val.trim() !== '' ? val.trim() : null;
}

async function fetchLegistarPersons() {
  const all = [];
  let skip = 0;
  const top = 1000;

  while (true) {
    const url = `${LEGISTAR_BASE}/Persons?$top=${top}&$skip=${skip}`;
    const response = await remoteFetchAsync(url);
    if (!response.ok) throw new Error(`Legistar error ${response.status}: ${url}`);
    const page = await response.json();
    all.push(...page);
    if (page.length < top) break; // last page
    skip += top;
  }

  return all;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const table = base.getTable('Persons');

const startDate = await input.textAsync('Start date for sync (YYYY-MM-DD):');
if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate)) {
  throw new Error(`Invalid date format: "${startDate}". Expected YYYY-MM-DD (e.g. 2020-01-01).`);
}

output.text('Step 1/4 — Fetching persons from Legistar...');
output.text(`  Note: Persons is a full sync — start date (${startDate}) is not applied.`);
const legistarPersons = await fetchLegistarPersons();
output.text(`  Found ${legistarPersons.length} persons.`);

output.text('Step 2/4 — Loading existing Airtable records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['PersonId'] });
const existingByPersonId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('PersonId');
  if (id !== null) existingByPersonId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByPersonId).length} existing records.`);

output.text('Step 3/4 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];

for (const person of legistarPersons) {
  const fields = {
    'PersonId':           person.PersonId,
    'PersonFullName':     person.PersonFullName || '',
    'PersonFirstName':    person.PersonFirstName || '',
    'PersonLastName':     person.PersonLastName || '',
    'PersonEmail':        emptyToNull(person.PersonEmail),
    'PersonPhone':        emptyToNull(person.PersonPhone),
    'PersonActiveFlag':   person.PersonActiveFlag === 1,
    'PersonLastModified': toUtcString(person.PersonLastModifiedUtc),
  };

  if (existingByPersonId[person.PersonId]) {
    toUpdate.push({ id: existingByPersonId[person.PersonId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);

output.text('Step 4/4 — Writing to Airtable...');

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
