// =============================================================================
// Clear Table — delete all records from a selected table or all tables
// =============================================================================
// Run as a Scripting Extension (manual).
// Use this before re-running a sync script when you need a clean slate.
// Deletes records in batches of 50. Prompts for confirmation before proceeding.
// =============================================================================

const BATCH_SIZE = 50;

async function clearTable(table) {
  const query = await table.selectRecordsAsync({ fields: [] });
  const ids = query.records.map(r => r.id);
  if (ids.length === 0) {
    output.text(`  "${table.name}": already empty.`);
    return 0;
  }
  for (let i = 0; i < ids.length; i += BATCH_SIZE) {
    await table.deleteRecordsAsync(ids.slice(i, i + BATCH_SIZE));
  }
  output.text(`  "${table.name}": deleted ${ids.length} records.`);
  return ids.length;
}

// ---------------------------------------------------------------------------
// Mode selection
// ---------------------------------------------------------------------------
const mode = await input.buttonsAsync(
  'What would you like to clear?',
  [
    { label: 'One table',   variant: 'default' },
    { label: 'All tables',  variant: 'danger'  },
    { label: 'Cancel',      variant: 'secondary' },
  ]
);

if (mode === 'Cancel') {
  output.text('Cancelled.');

} else if (mode === 'One table') {
  const table = await input.tableAsync('Select a table to clear:');
  const query = await table.selectRecordsAsync({ fields: [] });
  const total = query.records.length;

  if (total === 0) {
    output.text(`"${table.name}" is already empty. Nothing to do.`);
  } else {
    const confirm = await input.buttonsAsync(
      `Delete all ${total} records from "${table.name}"?`,
      [{ label: 'Delete all', variant: 'danger' }, { label: 'Cancel', variant: 'secondary' }]
    );
    if (confirm !== 'Delete all') {
      output.text('Cancelled.');
    } else {
      await clearTable(table);
      output.text(`\n✓ Done.`);
    }
  }

} else if (mode === 'All tables') {
  // Load record counts for all tables before confirming.
  const tables = base.tables;
  const counts = await Promise.all(
    tables.map(async t => {
      const q = await t.selectRecordsAsync({ fields: [] });
      return { table: t, count: q.records.length };
    })
  );

  const summary = counts.map(c => `  ${c.table.name}: ${c.count} records`).join('\n');
  const grandTotal = counts.reduce((sum, c) => sum + c.count, 0);

  const confirm = await input.buttonsAsync(
    `Delete all ${grandTotal} records across ${tables.length} tables?\n\n${summary}`,
    [{ label: 'Delete all', variant: 'danger' }, { label: 'Cancel', variant: 'secondary' }]
  );

  if (confirm !== 'Delete all') {
    output.text('Cancelled.');
  } else {
    let totalDeleted = 0;
    for (const { table } of counts) {
      totalDeleted += await clearTable(table);
    }
    output.text(`\n✓ Done. ${totalDeleted} records deleted across ${tables.length} tables.`);
  }
}
