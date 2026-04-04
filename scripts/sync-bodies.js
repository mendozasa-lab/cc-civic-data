// =============================================================================
// Bodies Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by BodyId).
// Bodies is a small lookup table (~50 records) so no pagination needed,
// but the fetch function is written to handle it for consistency.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;

// ---------------------------------------------------------------------------
// Legistar timestamps are UTC but arrive without a 'Z' suffix.
// Append it so Airtable interprets them correctly.
// ---------------------------------------------------------------------------
function toUtcString(legistarTimestamp) {
  if (!legistarTimestamp) return null;
  return legistarTimestamp.endsWith('Z')
    ? legistarTimestamp
    : legistarTimestamp + 'Z';
}

// ---------------------------------------------------------------------------
// Fetch all Bodies from Legistar.
// No date filter — this is a lookup table; we want everything.
// ---------------------------------------------------------------------------
async function fetchLegistarBodies() {
  const url = `${LEGISTAR_BASE}/Bodies`;
  const response = await remoteFetchAsync(url);
  if (!response.ok) throw new Error(`Legistar error ${response.status}: ${url}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Ensure all BodyTypeName values from Legistar exist as choices on the
// BodyType field. Adds any missing ones before records are written.
// ---------------------------------------------------------------------------
async function syncBodyTypeChoices(legistarBodies) {
  const field = table.getField('BodyType');
  const existingNames = new Set(field.options.choices.map(c => c.name));

  const newChoices = [...new Set(
    legistarBodies
      .map(b => b.BodyTypeName)
      .filter(name => name && !existingNames.has(name))
  )].map(name => ({ name }));

  if (newChoices.length === 0) {
    output.text('  No new BodyType choices to add.');
    return;
  }

  await field.updateOptionsAsync({
    choices: [...field.options.choices, ...newChoices],
  });
  output.text(`  Added ${newChoices.length} new BodyType choice(s): ${newChoices.map(c => c.name).join(', ')}`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const table = base.getTable('Bodies');

output.text('Step 1/5 — Fetching bodies from Legistar...');
const legistarBodies = await fetchLegistarBodies();
output.text(`  Found ${legistarBodies.length} bodies.`);

output.text('Step 2/5 — Syncing BodyType choices...');
await syncBodyTypeChoices(legistarBodies);

output.text('Step 3/5 — Loading existing Airtable records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['BodyId'] });
const existingByBodyId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('BodyId');
  if (id !== null) existingByBodyId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByBodyId).length} existing records.`);

output.text('Step 4/5 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];

for (const body of legistarBodies) {
  const fields = {
    'BodyId':           body.BodyId,
    'BodyName':         body.BodyName || '',
    'BodyType':         body.BodyTypeName ? { name: body.BodyTypeName } : null,
    'BodyDescription':  body.BodyDescription || '',
    'BodyActiveFlag':   body.BodyActiveFlag === 1,
    'BodyLastModified': toUtcString(body.BodyLastModifiedUtc),
  };
  // Note: BodyMeetDay, BodyMeetTime, BodyMeetLocation are not in the Legistar
  // API — those fields are populated manually in Airtable.

  if (existingByBodyId[body.BodyId]) {
    toUpdate.push({ id: existingByBodyId[body.BodyId], fields });
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
