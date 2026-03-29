const { getPool } = require("../shared/db");

module.exports = async function (context, req) {
  const clanId = req.query.clan_id || "for-main";

  try {
    const pool = getPool();

    // Get last scan run info
    const lastRunQuery = `
      SELECT
        run_id,
        started_at,
        completed_at,
        status,
        chests_found,
        chests_new,
        error_message,
        EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at))::int AS duration_seconds
      FROM scan_runs
      WHERE clan_id = $1
      ORDER BY started_at DESC
      LIMIT 1
    `;

    const lastRun = await pool.query(lastRunQuery, [clanId]);

    // Get recent run stats (last 24 hours)
    const recentStatsQuery = `
      SELECT
        COUNT(*) FILTER (WHERE status = 'completed')::int AS successful_runs,
        COUNT(*) FILTER (WHERE status = 'failed')::int AS failed_runs,
        AVG(chests_found) FILTER (WHERE status = 'completed')::int AS avg_chests,
        MAX(completed_at) AS last_success
      FROM scan_runs
      WHERE clan_id = $1
        AND started_at > NOW() - INTERVAL '24 hours'
    `;

    const recentStats = await pool.query(recentStatsQuery, [clanId]);

    // Get total chest count in last 24h
    const chestCountQuery = `
      SELECT COUNT(*)::int AS count_24h
      FROM chests
      WHERE clan_id = $1
        AND scanned_at > NOW() - INTERVAL '24 hours'
    `;

    const chestCount = await pool.query(chestCountQuery, [clanId]);

    const run = lastRun.rows[0] || null;
    const stats = recentStats.rows[0] || {};
    const chests = chestCount.rows[0] || {};

    // Determine overall health status
    let healthStatus = "healthy";
    let healthMessage = "Scanner operating normally";

    if (!run) {
      healthStatus = "unknown";
      healthMessage = "No scan runs found";
    } else if (run.status === "failed") {
      healthStatus = "warning";
      healthMessage = `Last run failed: ${run.error_message || "Unknown error"}`;
    } else if (run.status === "running") {
      healthStatus = "running";
      healthMessage = "Scan in progress";
    } else {
      // Check if last successful scan was too long ago (> 2 hours)
      const lastScanAge = run.completed_at
        ? (Date.now() - new Date(run.completed_at).getTime()) / 1000 / 60
        : null;

      if (lastScanAge && lastScanAge > 120) {
        healthStatus = "stale";
        healthMessage = `Last scan was ${Math.round(lastScanAge)} minutes ago`;
      }
    }

    context.res = {
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: healthStatus,
        message: healthMessage,
        lastRun: run
          ? {
              id: run.run_id,
              startedAt: run.started_at,
              completedAt: run.completed_at,
              status: run.status,
              chestsFound: run.chests_found,
              chestsNew: run.chests_new,
              durationSeconds: run.duration_seconds,
              error: run.error_message,
            }
          : null,
        stats24h: {
          successfulRuns: stats.successful_runs || 0,
          failedRuns: stats.failed_runs || 0,
          avgChestsPerRun: stats.avg_chests || 0,
          lastSuccess: stats.last_success,
          totalChests: chests.count_24h || 0,
        },
        timestamp: new Date().toISOString(),
      }),
    };
  } catch (err) {
    context.log.error("Health check failed:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "error",
        message: "Health check failed",
        error: err.message,
        timestamp: new Date().toISOString(),
      }),
    };
  }
};
