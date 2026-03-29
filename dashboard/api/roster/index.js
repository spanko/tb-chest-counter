const { getPool } = require("../shared/db");

// Public roster endpoint for scanner to fetch member names
// No authentication required - just returns the list of names
module.exports = async function (context, req) {
  const clanId = req.query.clan_id || "for-main";

  try {
    const pool = getPool();

    // Check if table exists first
    const tableCheck = await pool.query(`
      SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'clan_roster'
      )
    `);

    if (!tableCheck.rows[0].exists) {
      // Table doesn't exist yet, return empty roster
      context.res = {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        },
        body: JSON.stringify({
          names: [],
          count: 0,
          message: "Roster not configured yet"
        })
      };
      return;
    }

    const rosterQuery = `
      SELECT player_name
      FROM clan_roster
      WHERE clan_id = $1
      ORDER BY player_name ASC
    `;
    const roster = await pool.query(rosterQuery, [clanId]);

    context.res = {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({
        names: roster.rows.map(r => r.player_name),
        count: roster.rows.length
      })
    };
  } catch (err) {
    context.log.error("Roster query failed:", err.message);
    context.res = {
      status: 500,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({ error: "Failed to fetch roster", detail: err.message })
    };
  }
};
