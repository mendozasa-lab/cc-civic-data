// =============================================================================
// Matter Attachments Sync — Legistar → Airtable
// =============================================================================
// Run as a Scripting Extension (manual).
// Safe to run repeatedly — uses upsert logic (create or update by AttachmentId).
// Fetches attachments for every Matter already in Airtable. No date prompt —
// scope is determined by which matters are present in the Matters table.
//
// Attachments are a sub-resource: /Matters/{MatterId}/Attachments
// There is no top-level /Attachments endpoint, so one Legistar call is made
// per matter. With ~10k matters this run will take several minutes.
// =============================================================================

const LEGISTAR_BASE = 'https://webapi.legistar.com/v1/corpuschristi';
const BATCH_SIZE = 50;
const PROGRESS_INTERVAL = 500; // log progress every N matters

// Legistar UTC timestamps — append 'Z' for Airtable dateTime fields.
function toUtcString(ts) {
  if (!ts) return null;
  return ts.endsWith('Z') ? ts : ts + 'Z';
}

// URL fields reject empty strings — return null instead.
function emptyToNull(val) {
  return val && val.trim() !== '' ? val.trim() : null;
}

// ---------------------------------------------------------------------------
// Fetch all attachments for a single matter. Returns [] on 404 or error.
// ---------------------------------------------------------------------------
async function fetchAttachmentsForMatter(matterId) {
  const url = `${LEGISTAR_BASE}/Matters/${matterId}/Attachments`;
  const response = await remoteFetchAsync(url);
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`Legistar error ${response.status}: ${url}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const table = base.getTable('Matter Attachments');
const mattersTable = base.getTable('Matters');

output.text('Step 1/5 — Loading Matters from Airtable...');
const mattersQuery = await mattersTable.selectRecordsAsync({ fields: ['MatterId'] });
const matters = mattersQuery.records
  .map(r => ({ airtableId: r.id, matterId: r.getCellValue('MatterId') }))
  .filter(m => m.matterId !== null);
output.text(`  Loaded ${matters.length} matter records.`);

output.text('Step 2/5 — Fetching attachments from Legistar (one call per matter)...');
const allAttachments = []; // [{ matterId, matterAirtableId, ...attachment }]
let fetchErrors = 0;

for (let i = 0; i < matters.length; i++) {
  const { airtableId, matterId } = matters[i];

  try {
    const attachments = await fetchAttachmentsForMatter(matterId);
    for (const att of attachments) {
      allAttachments.push({ matterId, matterAirtableId: airtableId, ...att });
    }
  } catch (err) {
    fetchErrors++;
    output.text(`  Error fetching matter ${matterId}: ${err.message}`);
  }

  if ((i + 1) % PROGRESS_INTERVAL === 0 || i + 1 === matters.length) {
    output.text(`  Processed ${i + 1} / ${matters.length} matters — ${allAttachments.length} attachments so far.`);
  }
}

output.text(`  Done. ${allAttachments.length} total attachments found.`);
if (fetchErrors > 0) {
  output.text(`  Warning: ${fetchErrors} matter(s) had fetch errors and were skipped.`);
}

output.text('Step 3/5 — Loading existing Attachment records...');
const existingQuery = await table.selectRecordsAsync({ fields: ['AttachmentId'] });
const existingByAttachmentId = {};
for (const record of existingQuery.records) {
  const id = record.getCellValue('AttachmentId');
  if (id !== null) existingByAttachmentId[id] = record.id;
}
output.text(`  Found ${Object.keys(existingByAttachmentId).length} existing records.`);

output.text('Step 4/5 — Building creates and updates...');
const toCreate = [];
const toUpdate = [];

for (const att of allAttachments) {
  const fields = {
    'AttachmentId':         att.MatterAttachmentId,
    'Matter':               [{ id: att.matterAirtableId }],
    'AttachmentName':       att.MatterAttachmentName || '',
    'AttachmentHyperlink':  emptyToNull(att.MatterAttachmentHyperlink),
    'AttachmentIsSupporting': att.MatterAttachmentIsSupportingDocument === true,
    'AttachmentLastModified': toUtcString(att.MatterAttachmentLastModifiedUtc),
  };

  if (existingByAttachmentId[att.MatterAttachmentId]) {
    toUpdate.push({ id: existingByAttachmentId[att.MatterAttachmentId], fields });
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
