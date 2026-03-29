const { getPool } = require("../shared/db");

// Simple admin endpoint that provides job status from database
module.exports = async function (context, req) {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    context.res = {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Admin-Code"
      },
      body: ""
    };
    return;
  }

  // Check admin authorization
  const adminCode = req.headers["x-admin-code"];
  if (adminCode !== "FOR2026-ADMIN") {
    context.res = {
      status: 403,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({ error: "Unauthorized" })
    };
    return;
  }

  const action = req.query.action || "status";

  // Log the request for debugging
  context.log(`Admin API - Action: ${action}, Method: ${req.method}`);

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
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
          },
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
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
          },
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
        let triggerBody = {};
        try {
          // Azure Functions might pass body as string or object
          triggerBody = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
        } catch (parseErr) {
          context.log.warn("Failed to parse trigger body:", parseErr);
        }
        const jobName = triggerBody.jobName || "tbdev-scan-for-main";

        try {
          context.log(`Recording job trigger request: ${jobName}`);

          // First try to create the table if it doesn't exist
          await pool.query(`
            CREATE TABLE IF NOT EXISTS runs (
              run_id SERIAL PRIMARY KEY,
              clan_id VARCHAR(50) NOT NULL,
              started_at TIMESTAMP DEFAULT NOW(),
              completed_at TIMESTAMP,
              status VARCHAR(50) DEFAULT 'requested',
              pages_scanned INTEGER DEFAULT 0,
              gifts_found INTEGER DEFAULT 0,
              new_gifts INTEGER DEFAULT 0,
              error_message TEXT,
              model_used VARCHAR(100)
            )
          `);

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

      case "health":
        // Health check and diagnostic endpoint
        try {
          const diagnostics = {
            connection: false,
            tables: {
              runs: false,
              job_schedules: false,
              chests: false
            },
            errors: []
          };

          // Test database connection
          try {
            await pool.query("SELECT 1");
            diagnostics.connection = true;
          } catch (connErr) {
            diagnostics.errors.push(`Connection failed: ${connErr.message}`);
          }

          // Check if tables exist and have data
          if (diagnostics.connection) {
            // Check runs table
            try {
              const runsCheck = await pool.query(`
                SELECT COUNT(*) as count,
                       MAX(started_at) as last_run
                FROM runs
                WHERE clan_id = $1
              `, ["FOR"]);
              diagnostics.tables.runs = {
                exists: true,
                count: parseInt(runsCheck.rows[0].count),
                lastRun: runsCheck.rows[0].last_run
              };
            } catch (err) {
              diagnostics.tables.runs = { exists: false, error: err.message };
            }

            // Check job_schedules table
            try {
              const schedCheck = await pool.query(`
                SELECT COUNT(*) as count,
                       MAX(updated_at) as last_update
                FROM job_schedules
              `);
              diagnostics.tables.job_schedules = {
                exists: true,
                count: parseInt(schedCheck.rows[0].count),
                lastUpdate: schedCheck.rows[0].last_update
              };
            } catch (err) {
              diagnostics.tables.job_schedules = { exists: false, error: err.message };
            }

            // Check chests table
            try {
              const chestsCheck = await pool.query(`
                SELECT COUNT(*) as count,
                       COUNT(DISTINCT player_name) as players,
                       MAX(scanned_at) as last_scan
                FROM chests
                WHERE clan_id = $1
              `, ["FOR"]);
              diagnostics.tables.chests = {
                exists: true,
                count: parseInt(chestsCheck.rows[0].count),
                players: parseInt(chestsCheck.rows[0].players),
                lastScan: chestsCheck.rows[0].last_scan
              };
            } catch (err) {
              diagnostics.tables.chests = { exists: false, error: err.message };
            }
          }

          // Add timestamp and status
          diagnostics.timestamp = new Date().toISOString();
          diagnostics.status = diagnostics.connection ? "healthy" : "unhealthy";

          context.res = {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify(diagnostics)
          };
        } catch (healthErr) {
          context.res = {
            status: 500,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({
              error: "Health check failed",
              detail: healthErr.message,
              timestamp: new Date().toISOString()
            })
          };
        }
        break;

      case "schedule":
        // Store schedule preferences in database
        const method = req.method?.toUpperCase();

        let scheduleBody = {};
        try {
          // Azure Functions might pass body as string or object
          scheduleBody = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
        } catch (parseErr) {
          context.log.warn("Failed to parse schedule body:", parseErr);
        }

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
              headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
              },
              body: JSON.stringify({
                error: "Failed to get schedule",
                detail: scheduleErr.message
              })
            };
          }
        } else if (method === "POST") {
          // Store schedule preference
          try {
            const jobName = scheduleBody.jobName || "tbdev-scan-for-main";
            const cronExpression = scheduleBody.cronExpression || "0 */30 * * * *";

            // First create the table if it doesn't exist
            await pool.query(`
              CREATE TABLE IF NOT EXISTS job_schedules (
                job_name VARCHAR(100) PRIMARY KEY,
                cron_expression VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
              )
            `);

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
              headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
              },
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

      case "members":
        // Member management - list all unique players with aliases and status
        try {
          // Ensure member_aliases table exists
          await pool.query(`
            CREATE TABLE IF NOT EXISTS member_aliases (
              id SERIAL PRIMARY KEY,
              raw_name VARCHAR(255) NOT NULL,
              canonical_name VARCHAR(255) NOT NULL,
              clan_id VARCHAR(50) NOT NULL,
              created_at TIMESTAMP DEFAULT NOW(),
              UNIQUE(raw_name, clan_id)
            )
          `);

          // Ensure member_status table exists
          await pool.query(`
            CREATE TABLE IF NOT EXISTS member_status (
              id SERIAL PRIMARY KEY,
              player_name VARCHAR(255) NOT NULL,
              clan_id VARCHAR(50) NOT NULL,
              status VARCHAR(50) DEFAULT 'active',
              left_at TIMESTAMP,
              notes TEXT,
              updated_at TIMESTAMP DEFAULT NOW(),
              UNIQUE(player_name, clan_id)
            )
          `);

          // Get all unique player names with their stats and alias/status info
          const membersQuery = `
            WITH player_stats AS (
              SELECT
                player_name,
                COUNT(*) as chest_count,
                SUM(points) as total_points,
                MIN(scanned_at) as first_seen,
                MAX(scanned_at) as last_seen
              FROM chests
              WHERE clan_id = $1
              GROUP BY player_name
            )
            SELECT
              ps.player_name,
              ps.chest_count,
              ps.total_points,
              ps.first_seen,
              ps.last_seen,
              ma.canonical_name,
              ms.status,
              ms.left_at,
              ms.notes
            FROM player_stats ps
            LEFT JOIN member_aliases ma ON ps.player_name = ma.raw_name AND ma.clan_id = $1
            LEFT JOIN member_status ms ON COALESCE(ma.canonical_name, ps.player_name) = ms.player_name AND ms.clan_id = $1
            ORDER BY ps.last_seen DESC
          `;

          const members = await pool.query(membersQuery, ["FOR"]);

          // Also get the list of canonical names (for alias target dropdown)
          const canonicalQuery = `
            SELECT DISTINCT COALESCE(ma.canonical_name, c.player_name) as name
            FROM chests c
            LEFT JOIN member_aliases ma ON c.player_name = ma.raw_name AND ma.clan_id = c.clan_id
            WHERE c.clan_id = $1
            ORDER BY name
          `;
          const canonicals = await pool.query(canonicalQuery, ["FOR"]);

          context.res = {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({
              members: members.rows.map(m => ({
                name: m.player_name,
                canonicalName: m.canonical_name || null,
                chestCount: parseInt(m.chest_count),
                totalPoints: parseInt(m.total_points),
                firstSeen: m.first_seen,
                lastSeen: m.last_seen,
                status: m.status || 'active',
                leftAt: m.left_at,
                notes: m.notes
              })),
              canonicalNames: canonicals.rows.map(c => c.name)
            })
          };
        } catch (membersErr) {
          context.log.error("Members query error:", membersErr);
          context.res = {
            status: 500,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({
              error: "Failed to fetch members",
              detail: membersErr.message
            })
          };
        }
        break;

      case "alias":
        // Add or remove an alias
        if (req.method !== "POST") {
          context.res = { status: 405, body: JSON.stringify({ error: "Method not allowed" }) };
          break;
        }

        try {
          let aliasBody = {};
          try {
            aliasBody = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
          } catch (parseErr) {
            context.log.warn("Failed to parse alias body:", parseErr);
          }

          const { rawName, canonicalName, remove } = aliasBody;

          if (!rawName) {
            context.res = {
              status: 400,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ error: "rawName is required" })
            };
            break;
          }

          if (remove) {
            // Remove alias
            await pool.query(
              `DELETE FROM member_aliases WHERE raw_name = $1 AND clan_id = $2`,
              [rawName, "FOR"]
            );
            context.res = {
              status: 200,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ success: true, message: `Alias removed for ${rawName}` })
            };
          } else {
            // Add/update alias
            if (!canonicalName) {
              context.res = {
                status: 400,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ error: "canonicalName is required when adding alias" })
              };
              break;
            }

            await pool.query(`
              INSERT INTO member_aliases (raw_name, canonical_name, clan_id)
              VALUES ($1, $2, $3)
              ON CONFLICT (raw_name, clan_id)
              DO UPDATE SET canonical_name = $2
            `, [rawName, canonicalName, "FOR"]);

            context.res = {
              status: 200,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                success: true,
                message: `${rawName} is now aliased to ${canonicalName}`
              })
            };
          }
        } catch (aliasErr) {
          context.log.error("Alias error:", aliasErr);
          context.res = {
            status: 500,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error: "Failed to update alias", detail: aliasErr.message })
          };
        }
        break;

      case "suggest-aliases":
        // Use Claude to match detected names to authoritative roster
        if (req.method !== "POST") {
          context.res = { status: 405, body: JSON.stringify({ error: "Method not allowed" }) };
          break;
        }

        try {
          let suggestBody = {};
          try {
            suggestBody = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
          } catch (parseErr) {
            context.log.warn("Failed to parse suggest-aliases body:", parseErr);
          }

          // Get authoritative roster from request body
          const authoritativeRoster = suggestBody.roster || [];
          if (!authoritativeRoster.length) {
            context.res = {
              status: 400,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ error: "roster array is required (list of authoritative player names)" })
            };
            break;
          }

          // Get all detected names from chests that aren't already aliased
          const detectedQuery = `
            SELECT DISTINCT c.player_name, COUNT(*) as chest_count
            FROM chests c
            LEFT JOIN member_aliases ma ON c.player_name = ma.raw_name AND ma.clan_id = c.clan_id
            WHERE c.clan_id = $1 AND ma.id IS NULL
            GROUP BY c.player_name
            ORDER BY c.player_name
          `;
          const detected = await pool.query(detectedQuery, ["FOR"]);
          const detectedNames = detected.rows.map(r => ({ name: r.player_name, chests: parseInt(r.chest_count) }));

          // Call Claude API to suggest matches
          const Anthropic = require("@anthropic-ai/sdk");
          const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

          const prompt = `You are analyzing player names from a game clan. I have two lists:

1. AUTHORITATIVE ROSTER (correct names):
${authoritativeRoster.map(n => `- ${n}`).join('\n')}

2. DETECTED NAMES (from OCR, may have typos):
${detectedNames.map(d => `- "${d.name}" (${d.chests} chests)`).join('\n')}

For each detected name, determine if it:
- Exactly matches a roster name (status: "exact")
- Is a typo/OCR error of a roster name (status: "alias", suggest the correct name)
- Is not in the roster - probably left the clan (status: "not_found")

Return JSON only:
{
  "suggestions": [
    {"detected": "SedtisSharpston", "status": "alias", "canonical": "Sedtis Sharpstone", "confidence": 0.95},
    {"detected": "Sedtis Sharpstone", "status": "exact", "canonical": "Sedtis Sharpstone", "confidence": 1.0},
    {"detected": "OldPlayer123", "status": "not_found", "canonical": null, "confidence": 0.9}
  ]
}

Be generous with matching - OCR often misses spaces, confuses similar characters (l/I/1, 0/O), or truncates names.`;

          const response = await anthropic.messages.create({
            model: "claude-sonnet-4-20250514",
            max_tokens: 4096,
            messages: [{ role: "user", content: prompt }]
          });

          let suggestions = [];
          try {
            let text = response.content[0].text;
            // Extract JSON from response
            const jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
              const data = JSON.parse(jsonMatch[0]);
              suggestions = data.suggestions || [];
            }
          } catch (parseErr) {
            context.log.warn("Failed to parse Claude response:", parseErr);
          }

          context.res = {
            status: 200,
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
            body: JSON.stringify({
              suggestions,
              detectedCount: detectedNames.length,
              rosterCount: authoritativeRoster.length
            })
          };
        } catch (suggestErr) {
          context.log.error("Suggest aliases error:", suggestErr);
          context.res = {
            status: 500,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error: "Failed to suggest aliases", detail: suggestErr.message })
          };
        }
        break;

      case "member-status":
        // Update member status (active, left, etc.)
        if (req.method !== "POST") {
          context.res = { status: 405, body: JSON.stringify({ error: "Method not allowed" }) };
          break;
        }

        try {
          let statusBody = {};
          try {
            statusBody = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
          } catch (parseErr) {
            context.log.warn("Failed to parse status body:", parseErr);
          }

          const { playerName, status, notes } = statusBody;

          if (!playerName || !status) {
            context.res = {
              status: 400,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ error: "playerName and status are required" })
            };
            break;
          }

          const leftAt = status === 'left' ? 'NOW()' : 'NULL';

          await pool.query(`
            INSERT INTO member_status (player_name, clan_id, status, left_at, notes, updated_at)
            VALUES ($1, $2, $3, ${status === 'left' ? 'NOW()' : 'NULL'}, $4, NOW())
            ON CONFLICT (player_name, clan_id)
            DO UPDATE SET status = $3, left_at = ${status === 'left' ? 'NOW()' : 'NULL'}, notes = $4, updated_at = NOW()
          `, [playerName, "FOR", status, notes || null]);

          context.res = {
            status: 200,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              success: true,
              message: `${playerName} status updated to ${status}`
            })
          };
        } catch (statusErr) {
          context.log.error("Member status error:", statusErr);
          context.res = {
            status: 500,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error: "Failed to update member status", detail: statusErr.message })
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
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({ error: "Database query failed", detail: err.message })
    };
  }
};