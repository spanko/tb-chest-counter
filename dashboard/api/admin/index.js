const { getPool } = require("../shared/db");

// Simple admin endpoint that provides job status from database
module.exports = async function (context, req) {
  // Check admin authorization
  const adminCode = req.headers["x-admin-code"];
  if (adminCode !== "FOR2026-ADMIN") {
    context.res = {
      status: 403,
      body: JSON.stringify({ error: "Unauthorized" })
    };
    return;
  }

  const action = req.query.action || "status";

  try {
    const pool = getPool();

    switch (action) {
      case "status":
        // Get recent runs from database
        const runsQuery = `
          SELECT
            run_id,
            started_at,
            completed_at,
            status,
            pages_scanned,
            gifts_found,
            new_gifts,
            error_message,
            model_used,
            CASE
              WHEN completed_at IS NOT NULL
              THEN EXTRACT(EPOCH FROM (completed_at - started_at))::int
              ELSE NULL
            END as duration_seconds
          FROM runs
          WHERE clan_id = $1
          ORDER BY started_at DESC
          LIMIT 10
        `;

        const runs = await pool.query(runsQuery, ["FOR"]);

        // Get summary stats
        const statsQuery = `
          SELECT
            COUNT(DISTINCT player_name) as total_players,
            COUNT(*) as total_chests,
            SUM(points) as total_points,
            MAX(scanned_at) as last_scan
          FROM chests
          WHERE clan_id = $1
          AND scanned_at > NOW() - INTERVAL '7 days'
        `;

        const stats = await pool.query(statsQuery, ["FOR"]);

        context.res = {
          status: 200,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runs: runs.rows.map(r => ({
              id: r.run_id,
              startTime: r.started_at,
              endTime: r.completed_at,
              status: r.status,
              giftsFound: r.gifts_found,
              newGifts: r.new_gifts,
              duration: r.duration_seconds ? `${Math.round(r.duration_seconds / 60)}m ${r.duration_seconds % 60}s` : null,
              error: r.error_message
            })),
            stats: stats.rows[0],
            message: "To start a job, use Azure Portal or CLI. Dashboard provides read-only monitoring."
          })
        };
        break;

      case "logs":
        // Get recent log entries (simulated from runs table)
        const logsQuery = `
          SELECT
            started_at as timestamp,
            status,
            COALESCE(error_message,
              CASE
                WHEN status = 'completed' THEN 'Run completed: ' || gifts_found || ' gifts found, ' || new_gifts || ' new'
                WHEN status = 'running' THEN 'Run started'
                ELSE 'Run ' || status
              END
            ) as message
          FROM runs
          WHERE clan_id = $1
            AND started_at > NOW() - INTERVAL '1 hour'
          ORDER BY started_at DESC
          LIMIT 50
        `;

        const logs = await pool.query(logsQuery, ["FOR"]);

        context.res = {
          status: 200,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            logs: logs.rows.map(l => ({
              timestamp: l.timestamp,
              level: l.status === 'failed' ? 'ERROR' : 'INFO',
              message: l.message
            }))
          })
        };
        break;

      default:
        context.res = {
          status: 400,
          body: JSON.stringify({ error: "Invalid action" })
        };
    }
  } catch (err) {
    context.log.error("Admin API error:", err.message);
    context.res = {
      status: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Database query failed", detail: err.message })
    };
  }
};