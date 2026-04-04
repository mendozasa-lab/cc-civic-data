require('dotenv').config();

module.exports = {
  client: process.env.LEGISTAR_CLIENT,
  baseUrl: process.env.LEGISTAR_API_BASE,
};
