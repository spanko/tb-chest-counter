const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const clanId = req.query.clan_id || "for-main";
  const method = req.method?.toUpperCase();

  try {
    const pool = getPool();

    if (method === "POST") {
      // Update target settings (requires admin)
      const adminCode = req.headers["x-admin-code"];
      if (adminCode !== "FOR2026-ADMIN") {
        context.res = {
          status: 403,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ error: "Unauthorized" }),
        };
        return;
      }

      const body = req.body || {};
      const weeklyChestTarget = body.weekly_chest_target || 30;
      const weeklyPointTarget = body.weekly_point_target || 100;
      const targetType = body.target_type || "chests";

      // Ensure table exists
      await pool.query(`
        CREATE TABLE IF NOT EXISTS clan_settings (
          clan_id TEXT PRIMARY KEY,
          weekly_chest_target INTEGER DEFAULT 30,
          weekly_point_target INTEGER DEFAULT 100,
          target_type TEXT DEFAULT 'chests',
          week_start_day INTEGER DEFAULT 1,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
      `);

      // Upsert settings
      await pool.query(`
        INSERT INTO clan_settings (clan_id, weekly_chest_target, weekly_point_target, target_type, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (clan_id) DO UPDATE SET
          weekly_chest_target = $2,
          weekly_point_target = $3,
          target_type = $4,
          updated_at = NOW()
      `, [clanId, weeklyChestTarget, weeklyPointTarget, targetType]);

      context.res = {
        status: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          success: true,
          settings: { weekly_chest_target: weeklyChestTarget, weekly_point_target: weeklyPointTarget, target_type: targetType },
        }),
      };
      return;
    }

    // GET: Fetch current settings and player progress
    // Get settings (with defaults if not set)
    const settingsResult = await pool.query(`
      SELECT
        COALESCE(weekly_chest_target, 30) AS weekly_chest_target,
        COALESCE(weekly_point_target, 100) AS weekly_point_target,
        COALESCE(target_type, 'chests') AS target_type,
        COALESCE(week_start_day, 1) AS week_start_day
      FROM clan_settings
      WHERE clan_id = $1
    `, [clanId]);

    const settings = settingsResult.rows[0] || {
      weekly_chest_target: 30,
      weekly_point_target: 100,
      target_type: "chests",
      week_start_day: 1,
    };

    // Calculate current week boundaries
    // week_start_day: 1=Monday, 0=Sunday
    const weekStartDay = settings.week_start_day;

    // Get player progress for current week
    const progressQuery = `
      WITH week_bounds AS (
        SELECT
          DATE_TRUNC('week', NOW()) + make_interval(days => $2) AS week_start,
          DATE_TRUNC('week', NOW()) + make_interval(days => $2 + 7) AS week_end
      )
      SELECT
        c.player_name,
        COUNT(*)::int AS chest_count,
        COALESCE(SUM(c.points), 0)::int AS total_points,
        MAX(c.scanned_at) AS last_seen,
        MIN(c.scanned_at) AS first_seen
      FROM chests c, week_bounds wb
      WHERE c.clan_id = $1
        AND c.scanned_at >= wb.week_start
        AND c.scanned_at < wb.week_end
      GROUP BY c.player_name
      ORDER BY total_points DESC
    `;

    const progressResult = await pool.query(progressQuery, [clanId, weekStartDay - 1]);

    // Calculate status for each player
    const target = settings.target_type === "points" ? settings.weekly_point_target : settings.weekly_chest_target;
    const targetField = settings.target_type === "points" ? "total_points" : "chest_count";

    // Calculate days into week and expected pace
    const now = new Date();
    const dayOfWeek = now.getUTCDay(); // 0=Sun, 1=Mon, ...
    const adjustedDay = (dayOfWeek - weekStartDay + 7) % 7;
    const daysIntoWeek = adjustedDay + (now.getUTCHours() / 24);
    const weekProgress = daysIntoWeek / 7;
    const expectedPace = target * weekProgress;

    const players = progressResult.rows.map((p) => {
      const current = p[targetField];
      const progress = Math.round((current / target) * 100);
      const pace = current / weekProgress; // Projected weekly total

      let status;
      if (current >= target) {
        status = "completed";
      } else if (current >= expectedPace * 0.8) {
        status = "on_track";
      } else if (current >= expectedPace * 0.5) {
        status = "at_risk";
      } else if (current > 0) {
        status = "behind";
      } else {
        status = "inactive";
      }

      return {
        player_name: p.player_name,
        chest_count: p.chest_count,
        total_points: p.total_points,
        progress,
        projected: Math.round(pace),
        status,
        last_seen: p.last_seen,
      };
    });

    // Get at-risk members (behind + at_risk)
    const atRisk = players.filter((p) => p.status === "at_risk" || p.status === "behind");

    // Summary stats
    const completed = players.filter((p) => p.status === "completed").length;
    const onTrack = players.filter((p) => p.status === "on_track").length;
    const atRiskCount = atRisk.length;
    const inactive = players.filter((p) => p.status === "inactive").length;

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        settings,
        week: {
          progress: Math.round(weekProgress * 100),
          days_into_week: Math.round(daysIntoWeek * 10) / 10,
          expected_pace: Math.round(expectedPace),
        },
        summary: {
          total_players: players.length,
          completed,
          on_track: onTrack,
          at_risk: atRiskCount,
          inactive,
        },
        players,
        at_risk: atRisk.slice(0, 10), // Top 10 at-risk
      }),
    };
  } catch (err) {
    context.log.error("Targets query failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message }),
    };
  }
};
