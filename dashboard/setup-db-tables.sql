-- Create tables for admin panel functionality

-- Table for tracking scan runs
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
);

-- Table for storing job schedules
CREATE TABLE IF NOT EXISTS job_schedules (
    job_name VARCHAR(100) PRIMARY KEY,
    cron_expression VARCHAR(100) NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table for scan logs
CREATE TABLE IF NOT EXISTS scan_logs (
    log_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    level VARCHAR(20),
    message TEXT
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_runs_clan_started ON runs(clan_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_logs_timestamp ON scan_logs(timestamp DESC);

-- Insert a test run to verify the setup
INSERT INTO runs (clan_id, started_at, status, model_used)
VALUES ('FOR', NOW() - INTERVAL '1 hour', 'completed', 'test')
ON CONFLICT DO NOTHING;

-- Insert a default schedule
INSERT INTO job_schedules (job_name, cron_expression)
VALUES ('tbdev-scan-for-main', '0 */30 * * * *')
ON CONFLICT (job_name) DO NOTHING;