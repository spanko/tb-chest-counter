const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const hours = parseInt(req.query.hours) || 168; // default 7 days
  const clanId = req.query.clan_id || "for-main"; // default to for-main

  // Clamp to reasonable range
  const clampedHours = Math.min(Math.max(hours, 1), 8760); // 1 hour to 365 days

  try {
    const pool = getPool();

    // Category breakdown query with conditional aggregation
    // Uses CASE WHEN chain - first match wins. Handles both source field
    // (new scans) and chest_type patterns (legacy data with NULL source).
    //
    // Aliases: OCR-detected names (raw_name) are mapped to canonical names
    // via the member_aliases table. The leaderboard aggregates by canonical name.
    //
    // Roster filter: Only players in clan_roster (or aliased to roster names)
    // are shown on the leaderboard.
    //
    // Categories (in priority order):
    //   ci (Citadels): Citadel in source/chest_type, or Gnome Workshop
    //   ev (Events):   Event sources, Golden Guardian, Ancients, Gladiator, etc.
    //   he (Heroic):   Monster sources or monster-named chests
    //   cr (Crypts):   Crypt in source, or known crypt-themed chest names
    //   cl (Clan):     Wealth chests, or catch-all default
    let query = `
      SELECT
        COALESCE(ma.canonical_name, c.player_name) AS name,
        COALESCE(SUM(c.points), 0)::int AS pts,

        -- CITADELS: source field or chest_type name
        SUM(CASE
          WHEN c.source ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Gnome Workshop%'
          THEN 1 ELSE 0
        END)::int AS ci,

        -- EVENTS: source field or known event chest names
        SUM(CASE
          WHEN c.source ILIKE ANY(ARRAY[
            '%Ancient%', '%Ragnarok%', '%Olympus%', '%Dark Omen%',
            '%Halloween%', '%Wreath%', '%Doomsday%', '%Arachne%'])
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Union Chest%', '%Triumphal%', '%Mimic%',
              '%Golden Guardian%', '%Ancients%', '%Ancient Warrior%',
              '%Ancient Bastion%', '%Gladiator%', '%Quick March%',
              '%House of Horrors%'])
          THEN 1 ELSE 0
        END)::int AS ev,

        -- HEROIC: source field or monster-related chests
        SUM(CASE
          WHEN c.source ILIKE ANY(ARRAY['%Heroic%', '%Epic Squad%', '%Monster%'])
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Heroic%', '%Barbarian%', '%Undead%', '%Dragon%', '%Demon%',
              '%Chimera%', '%Minotaur%', '%Harpy%', '%Griffin%', '%Hydra%',
              '%Cerberus%', '%Phoenix%', '%Cyclops%', '%Medusa%', '%Kraken%'])
          THEN 1 ELSE 0
        END)::int AS he,

        -- CRYPTS: source field OR known crypt-themed chest names
        SUM(CASE
          WHEN c.source ILIKE '%Crypt%'
            OR c.chest_type ILIKE '%Crypt%'
            OR c.chest_type ILIKE ANY(ARRAY[
              -- Common crypt themes
              '%Fire Chest%', '%Sand Chest%', '%Orc Chest%', '%Orc Temple%',
              '%Cobra Chest%', '%Stone Chest%', '%Mayan Chest%',
              '%Bone Chest%', '%Trillium Chest%', '%Infernal Chest%',
              '%Elegant Chest%', '%Serpent Sanctuary%', '%Black Mountain%',
              '%Departed%', '%Fiery Depths%', '%Old Engineer%',
              -- Additional crypt themes found in data
              '%Forgotten Chest%', '%Titansteel%', '%Braided Chest%',
              '%Turtle Chest%', '%White Wood%', '%Abandoned Chest%',
              '%Merchant%s Chest%'])
          THEN 1 ELSE 0
        END)::int AS cr,

        -- CLAN: everything else (calculated as total minus other categories)
        -- We compute this separately to avoid double-counting
        COUNT(*)::int - (
          -- Subtract citadels
          SUM(CASE WHEN c.source ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Gnome Workshop%' THEN 1 ELSE 0 END) +
          -- Subtract events
          SUM(CASE WHEN c.source ILIKE ANY(ARRAY[
            '%Ancient%', '%Ragnarok%', '%Olympus%', '%Dark Omen%',
            '%Halloween%', '%Wreath%', '%Doomsday%', '%Arachne%'])
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Union Chest%', '%Triumphal%', '%Mimic%',
              '%Golden Guardian%', '%Ancients%', '%Ancient Warrior%',
              '%Ancient Bastion%', '%Gladiator%', '%Quick March%',
              '%House of Horrors%']) THEN 1 ELSE 0 END) +
          -- Subtract heroic
          SUM(CASE WHEN c.source ILIKE ANY(ARRAY['%Heroic%', '%Epic Squad%', '%Monster%'])
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Heroic%', '%Barbarian%', '%Undead%', '%Dragon%', '%Demon%',
              '%Chimera%', '%Minotaur%', '%Harpy%', '%Griffin%', '%Hydra%',
              '%Cerberus%', '%Phoenix%', '%Cyclops%', '%Medusa%', '%Kraken%']) THEN 1 ELSE 0 END) +
          -- Subtract crypts
          SUM(CASE WHEN c.source ILIKE '%Crypt%'
            OR c.chest_type ILIKE '%Crypt%'
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Fire Chest%', '%Sand Chest%', '%Orc Chest%', '%Orc Temple%',
              '%Cobra Chest%', '%Stone Chest%', '%Mayan Chest%',
              '%Bone Chest%', '%Trillium Chest%', '%Infernal Chest%',
              '%Elegant Chest%', '%Serpent Sanctuary%', '%Black Mountain%',
              '%Departed%', '%Fiery Depths%', '%Old Engineer%',
              '%Forgotten Chest%', '%Titansteel%', '%Braided Chest%',
              '%Turtle Chest%', '%White Wood%', '%Abandoned Chest%',
              '%Merchant%s Chest%']) THEN 1 ELSE 0 END)
        )::int AS cl,

        -- Average levels per category (extract "level N" from source field)
        -- Prefer source, fall back to chest_type for legacy data
        ROUND(AVG(CASE
          WHEN c.source ILIKE '%Crypt%'
            OR c.chest_type ILIKE '%Crypt%'
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Fire Chest%', '%Sand Chest%', '%Orc Chest%', '%Orc Temple%',
              '%Cobra Chest%', '%Stone Chest%', '%Mayan Chest%',
              '%Bone Chest%', '%Trillium Chest%', '%Infernal Chest%',
              '%Elegant Chest%', '%Serpent Sanctuary%', '%Black Mountain%',
              '%Departed%', '%Fiery Depths%', '%Old Engineer%',
              '%Forgotten Chest%', '%Titansteel%', '%Braided Chest%',
              '%Turtle Chest%', '%White Wood%', '%Abandoned Chest%',
              '%Merchant%s Chest%'])
          THEN COALESCE(
            (regexp_match(c.source, '(\\d+)'))[1]::numeric,
            (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          )
          ELSE NULL
        END), 1) AS "crAvg",

        ROUND(AVG(CASE
          WHEN c.source ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Citadel%'
            OR c.chest_type ILIKE '%Gnome Workshop%'
          THEN COALESCE(
            (regexp_match(c.source, '(\\d+)'))[1]::numeric,
            (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          )
          ELSE NULL
        END), 1) AS "ciAvg",

        ROUND(AVG(CASE
          WHEN c.source ILIKE ANY(ARRAY['%Heroic%', '%Epic Squad%', '%Monster%'])
            OR c.chest_type ILIKE ANY(ARRAY[
              '%Heroic%', '%Barbarian%', '%Undead%', '%Dragon%', '%Demon%',
              '%Chimera%', '%Minotaur%', '%Harpy%', '%Griffin%', '%Hydra%',
              '%Cerberus%', '%Phoenix%', '%Cyclops%', '%Medusa%', '%Kraken%'])
          THEN COALESCE(
            (regexp_match(c.source, '(\\d+)'))[1]::numeric,
            (regexp_match(c.chest_type, '(\\d+)'))[1]::numeric
          )
          ELSE NULL
        END), 1) AS "heAvg",

        MAX(c.scanned_at) AS last_seen
      FROM chests c
      -- Join to resolve aliases: raw_name -> canonical_name
      LEFT JOIN member_aliases ma ON c.player_name = ma.raw_name AND ma.clan_id = $2
      -- Join to roster to filter only roster members (by canonical name)
      INNER JOIN clan_roster cr ON COALESCE(ma.canonical_name, c.player_name) = cr.player_name AND cr.clan_id = $2
      WHERE c.scanned_at > NOW() - make_interval(hours => $1)
        AND c.clan_id = $2
    `;
    const params = [clampedHours, clanId];

    query += `
      GROUP BY COALESCE(ma.canonical_name, c.player_name)
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
