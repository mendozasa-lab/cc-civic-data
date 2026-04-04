// =============================================================================
// Matters Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by MatterId).
// Prompts for a start date and filters to matters introduced on or after that date.
// Paginates Legistar in pages of 1000 until all records are fetched.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;

// Legistar UTC timestamps — append 'Z' for Airtable dateTime fields.
function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// Legistar date fields arrive as "2012-03-14T00:00:00" — strip the time
// component for Airtable date (not dateTime) fields.
function toDateString(ts) {
  if (!ts) return null;
  return ts.split('T')[0];
}

// ---------------------------------------------------------------------------
// Fetch all Matters from Legistar introduced on or after startDate (YYYY-MM-DD).
// ---------------------------------------------------------------------------
async function fetchLegistarMatters(startDate) {
  const all = [];
  let skip = 0;
  const top = 1000;
  const filter = `MatterIntroDate ge datetime'${startDate}T00:00:00'`;

  while (true) {
    const url = `${LEGISTAR_BASE}/Matters?$top=${top}&$skip=${skip}&$filter=${encodeURIComponent(filter)}`;
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
const table = base.getTable('Matters');

const startDate = await input.textAsync('Start date for sync (YYYY-MM-DD):');
if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate)) {
  throw new Error(`Invalid date format: "${startDate}". Expected YYYY-MM-DD (e.g. 2020-01-01).`);
}

output.text('Step 1/5 — Fetching matters from Legistar...');
const legistarMatters = await fetchLegistarMatters(startDate);
output.text(`  Found ${legistarMatters.length} matters (${startDate} onward).`);

output.text('Step 2/5 — Syncing select field choices...');
await syncSelectChoices('MatterType',   legistarMatters.map(m => m.MatterTypeName));
await syncSelectChoices('MatterStatus', legistarMatters.map(m => m.MatterStatusName));

output.text('Step 3/5 — Loading existing Airtable records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['MatterId'] });
const existingByMatterId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('MatterId');
  if (id !== null) existingByMatterId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByMatterId).length} existing records.`);

output.text('Step 4/5 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];

for (const matter of legistarMatters) {
  const fields = {
    'MatterId':            matter.MatterId,
    'MatterFile':          matter.MatterFile || '',
    'MatterName':          matter.MatterName || '',
    'MatterTitle':         matter.MatterTitle || '',
    'MatterType':          matter.MatterTypeName   ? { name: matter.MatterTypeName }   : null,
    'MatterStatus':        matter.MatterStatusName ? { name: matter.MatterStatusName } : null,
    'MatterBodyName':      matter.MatterBodyName || '',
    'MatterIntroDate':     toDateString(matter.MatterIntroDate),
    'MatterAgendaDate':    toDateString(matter.MatterAgendaDate),
    'MatterPassedDate':    toDateString(matter.MatterPassedDate),
    'MatterEnactmentNumber': matter.MatterEnactmentNumber || '',
    'MatterLastModified':  toUtcString(matter.MatterLastModifiedUtc),
  };

  if (existingByMatterId[matter.MatterId]) {
    toUpdate.push({ id: existingByMatterId[matter.MatterId], fields });
  } else {
    toCreate.push({ fields });
  }
}

output.text(`  ${toCreate.length} to create, ${toUpdate.length} to update.`);

output.text('Step 5/5 — Writing to Airtable...');

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
