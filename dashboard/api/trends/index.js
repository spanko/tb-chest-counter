const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const hours = parseInt(req.query.hours) || 168; // default 7 days
  const clanId = req.query.clan_id || null;
  const granularity = req.query.granularity || "daily"; // daily or hourly
  const group = req.query.group || null; // "dow" for day-of-week

  const clampedHours = Math.min(Math.max(hours, 1), 8760);

  try {
    const pool = getPool();

    // Day-of-week aggregation
    if (group === "dow") {
      let dowQuery = `
        SELECT
          EXTRACT(DOW FROM c.scanned_at)::int AS day_of_week,
          COUNT(*)::int AS chest_count,
          COALESCE(SUM(c.points), 0)::int AS total_points,
          COUNT(DISTINCT c.player_name)::int AS active_players
        FROM chests c
        WHERE c.scanned_at > NOW() - make_interval(hours => $1)
      `;
      const dowParams = [clampedHours];

      if (clanId) {
        dowQuery += ` AND c.clan_id = $2`;
        dowParams.push(clanId);
      }

      dowQuery += ` GROUP BY day_of_week ORDER BY day_of_week ASC`;

      const dowResult = await pool.query(dowQuery, dowParams);

      context.res = {
        status: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hours: clampedHours,
          group: "dow",
          data: dowResult.rows.map((r) => ({
            day_of_week: r.day_of_week,
            chests: r.chest_count,
            points: r.total_points,
            players: r.active_players,
          })),
        }),
      };
      return;
    }

    // Daily aggregation for trend chart
    let query;
    const params = [clampedHours];

    if (granularity === "hourly") {
      query = `
        SELECT
          DATE_TRUNC('hour', c.scanned_at) AS period,
          COUNT(*)::int AS chest_count,
          COALESCE(SUM(c.points), 0)::int AS total_points,
          COUNT(DISTINCT c.player_name)::int AS active_players
        FROM chests c
        WHERE c.scanned_at > NOW() - make_interval(hours => $1)
      `;
    } else {
      query = `
        SELECT
          DATE_TRUNC('day', c.scanned_at) AS period,
          COUNT(*)::int AS chest_count,
          COALESCE(SUM(c.points), 0)::int AS total_points,
          COUNT(DISTINCT c.player_name)::int AS active_players
        FROM chests c
        WHERE c.scanned_at > NOW() - make_interval(hours => $1)
      `;
    }

    if (clanId) {
      query += ` AND c.clan_id = $2`;
      params.push(clanId);
    }

    query += `
      GROUP BY period
      ORDER BY period ASC
    `;

    const result = await pool.query(query, params);

    // Also get comparison stats for trend arrows
    // Current period vs previous same-length period
    let comparisonQuery = `
      WITH current_period AS (
        SELECT
          COUNT(*)::int AS chest_count,
          COALESCE(SUM(points), 0)::int AS total_points,
          COUNT(DISTINCT player_name)::int AS active_players
        FROM chests
        WHERE scanned_at > NOW() - make_interval(hours => $1)
        ${clanId ? "AND clan_id = $2" : ""}
      ),
      previous_period AS (
        SELECT
          COUNT(*)::int AS chest_count,
          COALESCE(SUM(points), 0)::int AS total_points,
          COUNT(DISTINCT player_name)::int AS active_players
        FROM chests
        WHERE scanned_at > NOW() - make_interval(hours => $1 * 2)
          AND scanned_at <= NOW() - make_interval(hours => $1)
        ${clanId ? "AND clan_id = $2" : ""}
      )
      SELECT
        c.chest_count AS current_chests,
        c.total_points AS current_points,
        c.active_players AS current_players,
        p.chest_count AS previous_chests,
        p.total_points AS previous_points,
        p.active_players AS previous_players
      FROM current_period c, previous_period p
    `;

    const comparisonResult = await pool.query(comparisonQuery, params);
    const comparison = comparisonResult.rows[0] || {};

    // Calculate deltas
    const deltas = {
      chests: comparison.current_chests - (comparison.previous_chests || 0),
      points: comparison.current_points - (comparison.previous_points || 0),
      players: comparison.current_players - (comparison.previous_players || 0),
      chests_pct: comparison.previous_chests > 0
        ? Math.round(((comparison.current_chests - comparison.previous_chests) / comparison.previous_chests) * 100)
        : null,
      points_pct: comparison.previous_points > 0
        ? Math.round(((comparison.current_points - comparison.previous_points) / comparison.previous_points) * 100)
        : null,
    };

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hours: clampedHours,
        granularity,
        data: result.rows.map((r) => ({
          period: r.period,
          chests: r.chest_count,
          points: r.total_points,
          players: r.active_players,
        })),
        comparison: {
          current: {
            chests: comparison.current_chests || 0,
            points: comparison.current_points || 0,
            players: comparison.current_players || 0,
          },
          previous: {
            chests: comparison.previous_chests || 0,
            points: comparison.previous_points || 0,
            players: comparison.previous_players || 0,
          },
          deltas,
        },
      }),
    };
  } catch (err) {
    context.log.error("Trends query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
