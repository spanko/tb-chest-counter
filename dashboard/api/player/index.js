const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const playerName = req.params.name;
  const hours = parseInt(req.query.hours) || 168;
  const clanId = req.query.clan_id || null;

  if (!playerName) {
    context.res = {
      status: 400,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Player name is required" }),
    };
    return;
  }

  const clampedHours = Math.min(Math.max(hours, 1), 8760);

  try {
    const pool = getPool();

    let query = `
      SELECT
        c.chest_type,
        ct.category,
        COUNT(*)::int        AS count,
        COALESCE(SUM(c.points), 0)::int AS points
      FROM chests c
      LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
      WHERE c.player_name = $1
        AND c.scanned_at > NOW() - make_interval(hours => $2)
    `;
    const params = [playerName, clampedHours];

    if (clanId) {
      query += ` AND c.clan_id = $3`;
      params.push(clanId);
    }

    query += `
      GROUP BY c.chest_type, ct.category
      ORDER BY points DESC
    `;

    const result = await pool.query(query, params);

    // Also get summary stats
    let summaryQuery = `
      SELECT
        COUNT(*)::int AS chest_count,
        COALESCE(SUM(c.points), 0)::int AS total_points,
        MIN(c.scanned_at) AS first_seen,
        MAX(c.scanned_at) AS last_seen
      FROM chests c
      WHERE c.player_name = $1
        AND c.scanned_at > NOW() - make_interval(hours => $2)
    `;
    const summaryParams = [playerName, clampedHours];

    if (clanId) {
      summaryQuery += ` AND c.clan_id = $3`;
      summaryParams.push(clanId);
    }

    const summary = await pool.query(summaryQuery, summaryParams);

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player_name: playerName,
        hours: clampedHours,
        summary: summary.rows[0] || {},
        breakdown: result.rows,
      }),
    };
  } catch (err) {
    context.log.error("Player query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
