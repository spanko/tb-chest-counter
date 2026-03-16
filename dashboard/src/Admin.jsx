import { useState, useEffect, useCallback } from "react";

// Admin panel for managing chest counter jobs
export function AdminPanel({ theme, API_BASE }) {
  const [jobs, setJobs] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedJob, setSelectedJob] = useState("tbdev-scan-for-main");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [adminCode, setAdminCode] = useState("");
  const [authorized, setAuthorized] = useState(false);

  // Check if admin code is correct (FOR2026-ADMIN)
  const checkAdminAuth = () => {
    if (adminCode === "FOR2026-ADMIN") {
      setAuthorized(true);
      sessionStorage.setItem("tb-admin-auth", "1");
    }
  };

  useEffect(() => {
    // Check if already authorized
    if (sessionStorage.getItem("tb-admin-auth") === "1") {
      setAuthorized(true);
    }
  }, []);

  // Fetch job status
  const fetchJobStatus = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${API_BASE}/admin/jobs?job=${selectedJob}`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setJobs(data.jobs || []);
        setExecutions(data.executions || []);
      }
    } catch (e) {
      console.error("Failed to fetch job status:", e);
    }
  }, [authorized, selectedJob, API_BASE]);

  // Fetch recent logs
  const fetchLogs = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${API_BASE}/admin/logs?job=${selectedJob}&minutes=10`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
      }
    } catch (e) {
      console.error("Failed to fetch logs:", e);
    }
  }, [authorized, selectedJob, API_BASE]);

  // Start a job
  const startJob = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/start-job`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ jobName: selectedJob })
      });

      if (res.ok) {
        const data = await res.json();
        alert(`Job started: ${data.executionName}`);
        fetchJobStatus();
        fetchLogs();
      } else {
        alert("Failed to start job");
      }
    } catch (e) {
      alert(`Error starting job: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Auto-refresh effect
  useEffect(() => {
    if (autoRefresh && authorized) {
      const interval = setInterval(() => {
        fetchJobStatus();
        fetchLogs();
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [autoRefresh, authorized, fetchJobStatus, fetchLogs]);

  // Initial load
  useEffect(() => {
    if (authorized) {
      fetchJobStatus();
      fetchLogs();
    }
  }, [authorized, fetchJobStatus, fetchLogs]);

  if (!authorized) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <h2 style={{ color: theme.gold, marginBottom: 20 }}>Admin Access Required</h2>
        <input
          type="password"
          placeholder="Enter admin code"
          value={adminCode}
          onChange={(e) => setAdminCode(e.target.value)}
          onKeyPress={(e) => e.key === "Enter" && checkAdminAuth()}
          style={{
            padding: "10px 20px",
            fontSize: 14,
            background: theme.surface,
            border: `1px solid ${theme.border}`,
            color: theme.text,
            borderRadius: 6,
            marginRight: 10
          }}
        />
        <button
          onClick={checkAdminAuth}
          style={{
            padding: "10px 20px",
            background: theme.gold,
            color: theme.bg,
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
            fontWeight: 600
          }}
        >
          Login
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: "0 20px" }}>
      {/* Controls */}
      <div style={{
        display: "flex",
        gap: 15,
        marginBottom: 25,
        flexWrap: "wrap",
        alignItems: "center",
        background: theme.surface,
        padding: 20,
        borderRadius: 10,
        border: `1px solid ${theme.border}`
      }}>
        <select
          value={selectedJob}
          onChange={(e) => setSelectedJob(e.target.value)}
          style={{
            padding: "8px 12px",
            background: theme.bg,
            border: `1px solid ${theme.border}`,
            color: theme.text,
            borderRadius: 6,
            fontSize: 14
          }}
        >
          <option value="tbdev-scan-for-main">Main Scanner (Opens Gifts)</option>
          <option value="tb-smoke-test">Smoke Test (Validation Only)</option>
        </select>

        <button
          onClick={startJob}
          disabled={loading}
          style={{
            padding: "8px 20px",
            background: loading ? theme.border : theme.green,
            color: theme.bg,
            border: "none",
            borderRadius: 6,
            cursor: loading ? "not-allowed" : "pointer",
            fontWeight: 600,
            fontSize: 14
          }}
        >
          {loading ? "Starting..." : "▶ Start Job"}
        </button>

        <button
          onClick={() => { fetchJobStatus(); fetchLogs(); }}
          style={{
            padding: "8px 20px",
            background: "transparent",
            color: theme.text,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            cursor: "pointer",
            fontSize: 14
          }}
        >
          ↻ Refresh
        </button>

        <label style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          <span style={{ color: theme.textMuted, fontSize: 14 }}>Auto-refresh (5s)</span>
        </label>
      </div>

      {/* Job Executions */}
      <div style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 10,
        padding: 20,
        marginBottom: 20
      }}>
        <h3 style={{ color: theme.gold, marginBottom: 15, fontSize: 16 }}>Recent Executions</h3>
        {executions.length === 0 ? (
          <p style={{ color: theme.textMuted, fontSize: 14 }}>No recent executions</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Execution</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Status</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Started</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Duration</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((exec, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${theme.border}20` }}>
                    <td style={{ padding: "8px 12px", color: theme.text, fontFamily: "monospace", fontSize: 12 }}>
                      {exec.name}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{
                        color: exec.status === "Succeeded" ? theme.green :
                               exec.status === "Running" ? theme.gold :
                               exec.status === "Failed" ? theme.red : theme.textMuted,
                        fontWeight: 600
                      }}>
                        {exec.status}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", color: theme.textMuted, fontSize: 13 }}>
                      {exec.startTime || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: theme.textMuted, fontSize: 13 }}>
                      {exec.duration || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Logs */}
      <div style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 10,
        padding: 20
      }}>
        <h3 style={{ color: theme.gold, marginBottom: 15, fontSize: 16 }}>
          Recent Logs {logs.length > 0 && `(${logs.length})`}
        </h3>
        <div style={{
          background: theme.bg,
          border: `1px solid ${theme.border}`,
          borderRadius: 6,
          padding: 15,
          maxHeight: 400,
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: 12,
          lineHeight: 1.5
        }}>
          {logs.length === 0 ? (
            <p style={{ color: theme.textMuted }}>No logs available</p>
          ) : (
            logs.map((log, i) => (
              <div key={i} style={{ marginBottom: 4 }}>
                <span style={{ color: theme.textMuted }}>{log.timestamp}</span>
                <span style={{
                  color: log.level === "ERROR" ? theme.red :
                         log.level === "WARNING" ? theme.gold :
                         theme.text,
                  marginLeft: 10
                }}>
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Quick Stats */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: 15,
        marginTop: 20
      }}>
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          padding: 15
        }}>
          <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Next Scheduled Run</div>
          <div style={{ color: theme.gold, fontSize: 18, fontWeight: 600 }}>
            {jobs[0]?.nextRun || "Not scheduled"}
          </div>
        </div>
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          padding: 15
        }}>
          <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Last Run Status</div>
          <div style={{
            color: executions[0]?.status === "Succeeded" ? theme.green : theme.red,
            fontSize: 18,
            fontWeight: 600
          }}>
            {executions[0]?.status || "No runs"}
          </div>
        </div>
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          padding: 15
        }}>
          <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Schedule</div>
          <div style={{ color: theme.text, fontSize: 18, fontWeight: 600 }}>
            {jobs[0]?.schedule || "Manual"}
          </div>
        </div>
      </div>
    </div>
  );
}