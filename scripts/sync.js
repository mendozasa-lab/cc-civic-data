require('dotenv').config();
const legistarConfig = require('../config/legistar');
const airtableConfig = require('../config/airtable');

async function main() {
  console.log('Starting Legistar -> Airtable sync...');
  console.log(`Legistar client: ${legistarConfig.client}`);
  console.log(`Airtable base: ${airtableConfig.baseId}`);
  // TODO: implement sync logic
}

main().catch(console.error);
