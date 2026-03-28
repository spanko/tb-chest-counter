const express = require('express');
const cors = require('cors');
const { Pool } = require('pg');
require('dotenv').config();

const app = express();
const port = process.env.PORT || 8080;

// Enable CORS for all origins
app.use(cors());
app.use(express.json());

// PostgreSQL connection pool
const pool = new Pool({
  connectionString: process.env.POSTGRES_CONNECTION_STRING,
  ssl: {
    rejectUnauthorized: false
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// Admin API endpoint
app.all('/api/admin', async (req, res) => {
  // Handle OPTIONS for CORS
  if (req.method === 'OPTIONS') {
    return res.status(200).send();
  }

  // Check admin authorization
  const adminCode = req.headers['x-admin-code'];
  if (adminCode !== 'FOR2026-ADMIN') {
    return res.status(403).json({ error: 'Unauthorized' });
  }

  const action = req.query.action || 'status';
  console.log(`Admin API - Action: ${action}, Method: ${req.method}`);

  try {
    switch (action) {
      case 'status':
        // Get recent runs from database
        const runsQuery = `
          SELECT
            run_id,
            started_at,
            completed_at,
            status,
            pages_scanned,
            chests_found as gifts_found,
            chests_new as new_gifts,
            error_message,
            vision_model as model_used,
            CASE
              WHEN completed_at IS NOT NULL
              THEN EXTRACT(EPOCH FROM (completed_at - started_at))::int
              ELSE NULL
            END as duration_seconds
          FROM scan_runs
          WHERE clan_id = $1
          ORDER BY started_at DESC
          LIMIT 10
        `;

        const runs = await pool.query(runsQuery, ['for-main']);

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

        const stats = await pool.query(statsQuery, ['for-main']);

        res.json({
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
          message: 'To start a job, use Azure Portal or CLI. Dashboard provides read-only monitoring.'
        });
        break;

      case 'logs':
        // Get recent log entries
        const logsQuery = `
          SELECT
            started_at as timestamp,
            status,
            COALESCE(error_message,
              CASE
                WHEN status = 'completed' THEN 'Run completed: ' || chests_found || ' chests found, ' || chests_new || ' new'
                WHEN status = 'running' THEN 'Run started'
                ELSE 'Run ' || status
              END
            ) as message
          FROM scan_runs
          WHERE clan_id = $1
            AND started_at > NOW() - INTERVAL '1 hour'
          ORDER BY started_at DESC
          LIMIT 50
        `;

        const logs = await pool.query(logsQuery, ['for-main']);

        res.json({
          logs: logs.rows.map(l => ({
            timestamp: l.timestamp,
            level: l.status === 'failed' ? 'ERROR' : 'INFO',
            message: l.message
          }))
        });
        break;

      case 'trigger':
        // Record a job trigger request
        const triggerBody = req.body || {};
        const jobName = triggerBody.jobName || 'tbdev-scan-for-main';

        try {
          // First try to create the table if it doesn't exist (use scan_runs schema)
          await pool.query(`
            CREATE TABLE IF NOT EXISTS scan_runs (
              run_id SERIAL PRIMARY KEY,
              clan_id VARCHAR(50) NOT NULL,
              started_at TIMESTAMP DEFAULT NOW(),
              completed_at TIMESTAMP,
              status VARCHAR(50) DEFAULT 'requested',
              pages_scanned INTEGER DEFAULT 0,
              chests_found INTEGER DEFAULT 0,
              chests_new INTEGER DEFAULT 0,
              error_message TEXT,
              vision_model VARCHAR(100),
              vision_cost_usd NUMERIC(10,4) DEFAULT 0
            )
          `);

          // Log the trigger request in database
          const logQuery = `
            INSERT INTO scan_runs (clan_id, started_at, status, vision_model)
            VALUES ($1, NOW(), 'requested', 'manual')
            RETURNING run_id
          `;
          const result = await pool.query(logQuery, ['for-main']);

          res.json({
            success: true,
            message: `Job trigger request recorded. Use Azure CLI or Portal to start the job.`,
            runId: result.rows[0].run_id,
            jobName: jobName,
            cliCommand: `az containerapp job start --name ${jobName} --resource-group rg-tb-chest-counter-dev`
          });
        } catch (triggerErr) {
          console.error('Job trigger error:', triggerErr);
          res.status(500).json({
            error: 'Failed to record trigger request',
            detail: triggerErr.message
          });
        }
        break;

      case 'health':
        // Health check and diagnostic endpoint
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
          await pool.query('SELECT 1');
          diagnostics.connection = true;
        } catch (connErr) {
          diagnostics.errors.push(`Connection failed: ${connErr.message}`);
        }

        // Check if tables exist and have data
        if (diagnostics.connection) {
          // Check scan_runs table
          try {
            const runsCheck = await pool.query(`
              SELECT COUNT(*) as count,
                     MAX(started_at) as last_run
              FROM scan_runs
              WHERE clan_id = $1
            `, ['for-main']);
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
            `, ['for-main']);
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
        diagnostics.status = diagnostics.connection ? 'healthy' : 'unhealthy';

        res.json(diagnostics);
        break;

      case 'schedule':
        // Store schedule preferences in database
        const method = req.method?.toUpperCase();

        if (method === 'GET') {
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

            const result = await pool.query(scheduleQuery, ['tbdev-scan-for-main']);

            res.json({
              cronExpression: result.rows[0]?.cron_expression || '0 */30 * * * *',
              lastUpdated: result.rows[0]?.updated_at,
              info: 'Schedule is stored as preference. Update via Azure CLI to apply.'
            });
          } catch (scheduleErr) {
            res.status(500).json({
              error: 'Failed to get schedule',
              detail: scheduleErr.message
            });
          }
        } else if (method === 'POST') {
          // Store schedule preference
          try {
            const scheduleBody = req.body || {};
            const jobName = scheduleBody.jobName || 'tbdev-scan-for-main';
            const cronExpression = scheduleBody.cronExpression || '0 */30 * * * *';

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

            res.json({
              success: true,
              message: 'Schedule preference saved',
              cronExpression: cronExpression,
              cliCommand: `az containerapp job update --name ${jobName} --resource-group rg-tb-chest-counter-dev --cron-expression "${cronExpression}"`
            });
          } catch (updateErr) {
            res.status(500).json({
              error: 'Failed to save schedule',
              detail: updateErr.message
            });
          }
        } else {
          res.status(405).json({ error: 'Method not allowed' });
        }
        break;

      default:
        res.status(400).json({ error: 'Invalid action' });
    }
  } catch (err) {
    console.error('Admin API error:', err.message);
    res.status(500).json({ error: 'Database query failed', detail: err.message });
  }
});

// Start server
app.listen(port, () => {
  console.log(`Admin API server running on port ${port}`);
});