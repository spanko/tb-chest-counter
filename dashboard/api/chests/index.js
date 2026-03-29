const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const clanId = req.query.clan_id || null;
  const page = parseInt(req.query.page) || 1;
  const limit = Math.min(parseInt(req.query.limit) || 50, 200);
  const offset = (page - 1) * limit;

  // Filters
  const playerName = req.query.player || null;
  const chestType = req.query.chest_type || null;
  const category = req.query.category || null;
  const fromDate = req.query.from || null;
  const toDate = req.query.to || null;
  const hours = parseInt(req.query.hours) || null;

  // Export mode
  const exportCsv = req.query.export === "csv";

  try {
    const pool = getPool();

    // Build dynamic query
    let whereConditions = [];
    let params = [];
    let paramIndex = 1;

    if (clanId) {
      whereConditions.push(`c.clan_id = $${paramIndex++}`);
      params.push(clanId);
    }

    if (playerName) {
      whereConditions.push(`c.player_name ILIKE $${paramIndex++}`);
      params.push(`%${playerName}%`);
    }

    if (chestType) {
      whereConditions.push(`c.chest_type ILIKE $${paramIndex++}`);
      params.push(`%${chestType}%`);
    }

    if (category) {
      whereConditions.push(`ct.category = $${paramIndex++}`);
      params.push(category);
    }

    if (hours) {
      whereConditions.push(`c.scanned_at > NOW() - make_interval(hours => $${paramIndex++})`);
      params.push(hours);
    } else {
      if (fromDate) {
        whereConditions.push(`c.scanned_at >= $${paramIndex++}::timestamptz`);
        params.push(fromDate);
      }
      if (toDate) {
        whereConditions.push(`c.scanned_at <= $${paramIndex++}::timestamptz`);
        params.push(toDate);
      }
    }

    const whereClause = whereConditions.length > 0
      ? `WHERE ${whereConditions.join(" AND ")}`
      : "";

    // Get total count
    const countQuery = `
      SELECT COUNT(*)::int AS total
      FROM chests c
      LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
      ${whereClause}
    `;

    const countResult = await pool.query(countQuery, params);
    const total = countResult.rows[0]?.total || 0;

    // Get data
    const dataQuery = `
      SELECT
        c.id,
        c.clan_id,
        c.player_name,
        c.chest_type,
        ct.category,
        c.points,
        c.source,
        c.time_remaining,
        c.scanned_at,
        c.run_id
      FROM chests c
      LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
      ${whereClause}
      ORDER BY c.scanned_at DESC
      ${exportCsv ? "" : `LIMIT $${paramIndex++} OFFSET $${paramIndex++}`}
    `;

    const dataParams = exportCsv ? params : [...params, limit, offset];
    const dataResult = await pool.query(dataQuery, dataParams);

    // CSV export
    if (exportCsv) {
      const csvHeader = "id,clan_id,player_name,chest_type,category,points,source,time_remaining,scanned_at\n";
      const csvRows = dataResult.rows.map((r) =>
        `${r.id},"${r.clan_id || ""}","${r.player_name}","${r.chest_type}","${r.category || ""}",${r.points},"${r.source || ""}","${r.time_remaining || ""}",${r.scanned_at?.toISOString() || ""}`
      ).join("\n");

      context.res = {
        status: 200,
        headers: {
          "Content-Type": "text/csv",
          "Content-Disposition": `attachment; filename="chests_export_${new Date().toISOString().split("T")[0]}.csv"`,
        },
        body: csvHeader + csvRows,
      };
      return;
    }

    // Get available categories for filter dropdown
    const categoriesResult = await pool.query(`
      SELECT DISTINCT ct.category
      FROM chests c
      LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
      WHERE ct.category IS NOT NULL
      ${clanId ? "AND c.clan_id = $1" : ""}
      ORDER BY ct.category
    `, clanId ? [clanId] : []);

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chests: dataResult.rows,
        pagination: {
          page,
          limit,
          total,
          total_pages: Math.ceil(total / limit),
        },
        filters: {
          categories: categoriesResult.rows.map((r) => r.category),
        },
      }),
    };
  } catch (err) {
    context.log.error("Chests query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
