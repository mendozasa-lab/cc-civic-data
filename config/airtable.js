require('dotenv').config();

module.exports = {
  apiKey: process.env.AIRTABLE_API_KEY,
  baseId: process.env.AIRTABLE_BASE_ID,
};
