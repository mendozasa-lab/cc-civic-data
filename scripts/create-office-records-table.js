// =============================================================================
// Create Office Records Table — one-time setup
// =============================================================================
// Run once in a Scripting Extension to add the Office Records table.
// Safe to run only if the table does not already exist.
// =============================================================================

const int      = (name) => ({ name, type: 'number',         options: { precision: 0 } });
const text     = (name) => ({ name, type: 'singleLineText' });
const date     = (name) => ({ name, type: 'date',            options: { dateFormat: { name: 'iso' } } });
const dateTime = (name) => ({ name, type: 'dateTime',        options: { dateFormat: { name: 'iso' }, timeFormat: { name: '12hour' }, timeZone: 'America/Chicago' } });
const select   = (name, choices) => ({ name, type: 'singleSelect', options: { choices: choices.map(c => ({ name: c })) } });
const link     = (name, linkedTableId) => ({ name, type: 'multipleRecordLinks', options: { linkedTableId } });

const existing = base.tables.find(t => t.name === 'Office Records');
if (existing) {
  output.text('Office Records table already exists. Nothing to do.');
} else {
  const personsId = base.getTable('Persons').id;
  const bodiesId  = base.getTable('Bodies').id;

  await base.createTableAsync('Office Records', [
    int('OfficeRecordId'),
    link('Person', personsId),
    link('Body',   bodiesId),
    select('OfficeRecordTitle', ['Council Member', 'Mayor', 'City Manager', 'Mayor Pro Tem', 'Other']),
    date('OfficeRecordStartDate'),
    date('OfficeRecordEndDate'),
    select('OfficeRecordMemberType', ['Member']),
    dateTime('OfficeRecordLastModified'),
  ]);

  output.text('✓ Office Records table created.');
}
