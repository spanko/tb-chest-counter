const { Pool } = require("pg");

let pool;

function getPool() {
  if (!pool) {
    pool = new Pool({
      host: process.env.PG_HOST,
      database: process.env.PG_DATABASE || "tbchests",
      user: process.env.PG_USER || "tbadmin",
      password: process.env.PG_PASSWORD,
      port: 5432,
      ssl: { rejectUnauthorized: false },
      max: 3,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 5000,
    });
  }
  return pool;
}

module.exports = { getPool };
