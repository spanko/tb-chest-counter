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

      case "trigger":
        // Record a job trigger request in the database
        // The actual triggering needs to be done via Azure Portal, CLI, or a scheduled job
        const jobName = req.body?.jobName || "tbdev-scan-for-main";

        try {
          context.log(`Recording job trigger request: ${jobName}`);

          // Log the trigger request in database
          const logQuery = `
            INSERT INTO runs (clan_id, started_at, status, model_used)
            VALUES ($1, NOW(), 'requested', 'manual')
            RETURNING run_id
          `;
          const result = await pool.query(logQuery, ["FOR"]);

          context.res = {
            status: 200,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              success: true,
              message: `Job trigger request recorded. Use Azure CLI or Portal to start the job.`,
              runId: result.rows[0].run_id,
              jobName: jobName,
              cliCommand: `az containerapp job start --name ${jobName} --resource-group rg-tb-chest-counter-dev`
            })
          };
        } catch (triggerErr) {
          context.log.error("Job trigger error:", triggerErr);
          context.res = {
            status: 500,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              error: "Failed to record trigger request",
              detail: triggerErr.message
            })
          };
        }
        break;

      case "schedule":
        // Store schedule preferences in database
        const method = req.method?.toUpperCase();

        if (method === "GET") {
          // Get stored schedule preference
          try {
            const scheduleQuery = `
              SELECT
                cron_expression,
                updated_at
              FROM job_schedules
              WHERE job_name = $1
              ORDER BY updated_at DESC
              LIMIT 1
            `;

            const result = await pool.query(scheduleQuery, ["tbdev-scan-for-main"]);

            context.res = {
              status: 200,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                cronExpression: result.rows[0]?.cron_expression || "0 */30 * * * *",
                lastUpdated: result.rows[0]?.updated_at,
                info: "Schedule is stored as preference. Update via Azure CLI to apply."
              })
            };
          } catch (scheduleErr) {
            context.res = {
              status: 500,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                error: "Failed to get schedule",
                detail: scheduleErr.message
              })
            };
          }
        } else if (method === "POST") {
          // Store schedule preference
          try {
            const jobName = req.body?.jobName || "tbdev-scan-for-main";
            const cronExpression = req.body?.cronExpression || "0 */30 * * * *";

            // Store the schedule preference
            const upsertQuery = `
              INSERT INTO job_schedules (job_name, cron_expression, updated_at)
              VALUES ($1, $2, NOW())
              ON CONFLICT (job_name)
              DO UPDATE SET cron_expression = $2, updated_at = NOW()
            `;

            await pool.query(upsertQuery, [jobName, cronExpression]);

            context.res = {
              status: 200,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                success: true,
                message: "Schedule preference saved",
                cronExpression: cronExpression,
                cliCommand: `az containerapp job update --name ${jobName} --resource-group rg-tb-chest-counter-dev --cron-expression "${cronExpression}"`
              })
            };
          } catch (updateErr) {
            context.res = {
              status: 500,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                error: "Failed to save schedule",
                detail: updateErr.message
              })
            };
          }
        } else {
          context.res = {
            status: 405,
            body: JSON.stringify({ error: "Method not allowed" })
          };
        }
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