const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const hours = parseInt(req.query.hours) || 168; // default 7 days
  const clanId = req.query.clan_id || null;

  const clampedHours = Math.min(Math.max(hours, 1), 8760);

  try {
    const pool = getPool();

    // Get chest type breakdown with category grouping
    let query = `
      SELECT
        COALESCE(ct.category, 'Other') AS category,
        c.chest_type,
        COUNT(*)::int AS count,
        COALESCE(SUM(c.points), 0)::int AS points
      FROM chests c
      LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
      WHERE c.scanned_at > NOW() - make_interval(hours => $1)
    `;
    const params = [clampedHours];

    if (clanId) {
      query += ` AND c.clan_id = $2`;
      params.push(clanId);
    }

    query += `
      GROUP BY ct.category, c.chest_type
      ORDER BY points DESC
    `;

    const result = await pool.query(query, params);

    // Aggregate by category for donut chart
    const categoryMap = {};
    for (const row of result.rows) {
      const cat = row.category;
      if (!categoryMap[cat]) {
        categoryMap[cat] = { category: cat, count: 0, points: 0, types: [] };
      }
      categoryMap[cat].count += row.count;
      categoryMap[cat].points += row.points;
      categoryMap[cat].types.push({
        chest_type: row.chest_type,
        count: row.count,
        points: row.points,
      });
    }

    const categories = Object.values(categoryMap).sort((a, b) => b.points - a.points);

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hours: clampedHours,
        categories,
        breakdown: result.rows,
      }),
    };
  } catch (err) {
    context.log.error("Sources query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
