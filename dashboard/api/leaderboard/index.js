const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const hours = parseInt(req.query.hours) || 168; // default 7 days
  const clanId = req.query.clan_id || null;

  // Clamp to reasonable range
  const clampedHours = Math.min(Math.max(hours, 1), 8760); // 1 hour to 365 days

  try {
    const pool = getPool();

    let query = `
      SELECT
        c.player_name,
        COUNT(*)::int            AS chest_count,
        COALESCE(SUM(c.points), 0)::int AS total_points,
        MAX(c.scanned_at)        AS last_seen
      FROM chests c
      WHERE c.scanned_at > NOW() - make_interval(hours => $1)
    `;
    const params = [clampedHours];

    if (clanId) {
      query += ` AND c.clan_id = $2`;
      params.push(clanId);
    }

    query += `
      GROUP BY c.player_name
      ORDER BY total_points DESC
    `;

    const result = await pool.query(query, params);

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        players: result.rows,
        hours: clampedHours,
        count: result.rowCount,
      }),
    };
  } catch (err) {
    context.log.error("Leaderboard query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
