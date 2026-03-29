const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const hours = parseInt(req.query.hours) || 168; // default 7 days
  const clanId = req.query.clan_id || null;

  // Clamp to reasonable range
  const clampedHours = Math.min(Math.max(hours, 1), 8760); // 1 hour to 365 days

  try {
    const pool = getPool();

    // Category breakdown query with conditional aggregation
    // Categories:
    //   cr (Crypts):   chest_type ILIKE '%Crypt%'
    //   ev (Events):   Ancient, Ragnarok, Olympus, Dark Omen, Halloween, Wreath, Doomsday, Arachne, Triumphal
    //   ci (Citadels): chest_type ILIKE '%Citadel%'
    //   he (Heroic):   Heroic, Epic Squad, Monster, Barbarian, Undead, Dragon, Demon
    //   cl (Clan):     everything else (default bucket)
    let query = `
      SELECT
        c.player_name AS name,
        COALESCE(SUM(c.points), 0)::int AS pts,

        -- Category counts
        SUM(CASE WHEN c.chest_type ILIKE '%Crypt%' THEN 1 ELSE 0 END)::int AS cr,
        SUM(CASE WHEN c.chest_type ILIKE ANY(ARRAY[
          '%Ancient%', '%Ragnarok%', '%Olympus%', '%Dark Omen%',
          '%Halloween%', '%Wreath%', '%Doomsday%', '%Arachne%', '%Triumphal%'
        ]) THEN 1 ELSE 0 END)::int AS ev,
        SUM(CASE WHEN c.chest_type ILIKE '%Citadel%' THEN 1 ELSE 0 END)::int AS ci,
        SUM(CASE WHEN c.chest_type ILIKE ANY(ARRAY[
          '%Heroic%', '%Epic Squad%', '%Monster%', '%Barbarian%',
          '%Undead%', '%Dragon%', '%Demon%'
        ]) THEN 1 ELSE 0 END)::int AS he,
        SUM(CASE
          WHEN c.chest_type ILIKE '%Crypt%' THEN 0
          WHEN c.chest_type ILIKE ANY(ARRAY[
            '%Ancient%', '%Ragnarok%', '%Olympus%', '%Dark Omen%',
            '%Halloween%', '%Wreath%', '%Doomsday%', '%Arachne%', '%Triumphal%'
          ]) THEN 0
          WHEN c.chest_type ILIKE '%Citadel%' THEN 0
          WHEN c.chest_type ILIKE ANY(ARRAY[
            '%Heroic%', '%Epic Squad%', '%Monster%', '%Barbarian%',
            '%Undead%', '%Dragon%', '%Demon%'
          ]) THEN 0
          ELSE 1
        END)::int AS cl,

        -- Average levels per category (extract number from chest_type)
        ROUND(AVG(CASE
          WHEN c.chest_type ILIKE '%Crypt%'
          THEN (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          ELSE NULL
        END), 1) AS "crAvg",
        ROUND(AVG(CASE
          WHEN c.chest_type ILIKE '%Citadel%'
          THEN (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          ELSE NULL
        END), 1) AS "ciAvg",
        ROUND(AVG(CASE
          WHEN c.chest_type ILIKE ANY(ARRAY[
            '%Heroic%', '%Epic Squad%', '%Monster%', '%Barbarian%',
            '%Undead%', '%Dragon%', '%Demon%'
          ])
          THEN (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          ELSE NULL
        END), 1) AS "heAvg",

        MAX(c.scanned_at) AS last_seen
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
      ORDER BY pts DESC
    `;

    const result = await pool.query(query, params);

    // Convert numeric averages to floats and handle nulls
    const players = result.rows.map((p) => ({
      ...p,
      crAvg: p.crAvg ? parseFloat(p.crAvg) : null,
      ciAvg: p.ciAvg ? parseFloat(p.ciAvg) : null,
      heAvg: p.heAvg ? parseFloat(p.heAvg) : null,
    }));

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        players,
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
