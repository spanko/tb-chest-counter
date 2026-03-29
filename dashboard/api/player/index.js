const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const playerName = req.query.name || req.params.name;
  const hours = parseInt(req.query.hours) || 168;
  const clanId = req.query.clan_id || "for-main";

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

    // Category breakdown with same logic as leaderboard
    const categoryQuery = `
      SELECT
        CASE
          WHEN c.source ILIKE '%Citadel%' OR c.chest_type ILIKE '%Citadel%' OR c.chest_type ILIKE '%Gnome Workshop%' THEN 'ci'
          WHEN c.source ILIKE ANY(ARRAY['%Ancient%', '%Ragnarok%', '%Olympus%', '%Dark Omen%', '%Halloween%', '%Wreath%', '%Doomsday%', '%Arachne%'])
            OR c.chest_type ILIKE ANY(ARRAY['%Union Chest%', '%Triumphal%', '%Mimic%', '%Golden Guardian%', '%Ancients%', '%Ancient Warrior%', '%Ancient Bastion%', '%Gladiator%', '%Quick March%', '%House of Horrors%']) THEN 'ev'
          WHEN c.source ILIKE ANY(ARRAY['%Heroic%', '%Epic Squad%', '%Monster%'])
            OR c.chest_type ILIKE ANY(ARRAY['%Heroic%', '%Barbarian%', '%Undead%', '%Dragon%', '%Demon%', '%Chimera%', '%Minotaur%', '%Harpy%', '%Griffin%', '%Hydra%', '%Cerberus%', '%Phoenix%', '%Cyclops%', '%Medusa%', '%Kraken%']) THEN 'he'
          WHEN c.source ILIKE '%Crypt%' OR c.chest_type ILIKE '%Crypt%'
            OR c.chest_type ILIKE ANY(ARRAY['%Fire Chest%', '%Sand Chest%', '%Orc Chest%', '%Orc Temple%', '%Cobra Chest%', '%Stone Chest%', '%Mayan Chest%', '%Bone Chest%', '%Trillium Chest%', '%Infernal Chest%', '%Elegant Chest%', '%Serpent Sanctuary%', '%Black Mountain%', '%Departed%', '%Fiery Depths%', '%Old Engineer%', '%Forgotten Chest%', '%Titansteel%', '%Braided Chest%', '%Turtle Chest%', '%White Wood%', '%Abandoned Chest%', '%Merchant%s Chest%']) THEN 'cr'
          ELSE 'cl'
        END AS category,
        COUNT(*)::int AS count,
        COALESCE(SUM(c.points), 0)::int AS points
      FROM chests c
      WHERE c.player_name = $1
        AND c.clan_id = $2
        AND c.scanned_at > NOW() - make_interval(hours => $3)
      GROUP BY 1
      ORDER BY points DESC
    `;
    const categoryResult = await pool.query(categoryQuery, [playerName, clanId, clampedHours]);

    // Summary stats
    const summaryQuery = `
      SELECT
        COUNT(*)::int AS chest_count,
        COALESCE(SUM(c.points), 0)::int AS total_points,
        MIN(c.scanned_at) AS first_seen,
        MAX(c.scanned_at) AS last_seen
      FROM chests c
      WHERE c.player_name = $1
        AND c.clan_id = $2
        AND c.scanned_at > NOW() - make_interval(hours => $3)
    `;
    const summary = await pool.query(summaryQuery, [playerName, clanId, clampedHours]);

    // Daily activity for chart (last 30 days max)
    const chartDays = Math.min(Math.ceil(clampedHours / 24), 30);
    const dailyQuery = `
      SELECT
        DATE(c.scanned_at) AS date,
        COUNT(*)::int AS chests,
        COALESCE(SUM(c.points), 0)::int AS points
      FROM chests c
      WHERE c.player_name = $1
        AND c.clan_id = $2
        AND c.scanned_at > NOW() - make_interval(days => $3)
      GROUP BY DATE(c.scanned_at)
      ORDER BY date ASC
    `;
    const dailyResult = await pool.query(dailyQuery, [playerName, clanId, chartDays]);

    // Recent chests (last 20)
    const recentQuery = `
      SELECT
        c.chest_type,
        c.source,
        c.points,
        c.scanned_at
      FROM chests c
      WHERE c.player_name = $1
        AND c.clan_id = $2
      ORDER BY c.scanned_at DESC
      LIMIT 20
    `;
    const recentResult = await pool.query(recentQuery, [playerName, clanId]);

    // Build category summary object
    const categories = { cr: 0, ev: 0, ci: 0, he: 0, cl: 0 };
    categoryResult.rows.forEach(r => {
      if (categories.hasOwnProperty(r.category)) {
        categories[r.category] = r.count;
      }
    });

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player_name: playerName,
        hours: clampedHours,
        summary: summary.rows[0] || {},
        categories,
        daily: dailyResult.rows.map(r => ({
          date: r.date,
          chests: r.chests,
          points: r.points
        })),
        recent: recentResult.rows.map(r => ({
          chestType: r.chest_type,
          source: r.source,
          points: r.points,
          scannedAt: r.scanned_at
        }))
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
