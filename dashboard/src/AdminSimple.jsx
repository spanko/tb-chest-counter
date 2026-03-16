import { useState, useEffect, useCallback } from "react";

// Simplified admin panel that shows job status from database
export function AdminPanel({ theme, API_BASE }) {
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [adminCode, setAdminCode] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [message, setMessage] = useState("");

  // Check if admin code is correct
  const checkAdminAuth = () => {
    if (adminCode === "FOR2026-ADMIN") {
      setAuthorized(true);
      sessionStorage.setItem("tb-admin-auth", "1");
    }
  };

  useEffect(() => {
    if (sessionStorage.getItem("tb-admin-auth") === "1") {
      setAuthorized(true);
    }
  }, []);

  // Fetch status from database
  const fetchStatus = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${API_BASE}/admin?action=status`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
        setStats(data.stats || {});
        setMessage(data.message || "");
      }
    } catch (e) {
      console.error("Failed to fetch status:", e);
    }
  }, [authorized, API_BASE]);

  // Fetch logs
  const fetchLogs = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${API_BASE}/admin?action=logs`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
      }
    } catch (e) {
      console.error("Failed to fetch logs:", e);
    }
  }, [authorized, API_BASE]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh && authorized) {
      const interval = setInterval(() => {
        fetchStatus();
        fetchLogs();
      }, 10000); // 10 seconds
      return () => clearInterval(interval);
    }
  }, [autoRefresh, authorized, fetchStatus, fetchLogs]);

  // Initial load
  useEffect(() => {
    if (authorized) {
      fetchStatus();
      fetchLogs();
    }
  }, [authorized, fetchStatus, fetchLogs]);

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
      {/* Header */}
      <div style={{
        background: theme.surface,
        padding: 20,
        borderRadius: 10,
        border: `1px solid ${theme.border}`,
        marginBottom: 20
      }}>
        <h2 style={{ color: theme.gold, marginBottom: 15 }}>Job Management</h2>

        <div style={{ display: "flex", gap: 15, alignItems: "center", flexWrap: "wrap" }}>
          <button
            onClick={() => { fetchStatus(); fetchLogs(); }}
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

          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span style={{ color: theme.textMuted, fontSize: 14 }}>Auto-refresh (10s)</span>
          </label>
        </div>

        {message && (
          <div style={{
            marginTop: 15,
            padding: 12,
            background: theme.bg,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            color: theme.gold,
            fontSize: 13
          }}>
            <strong>ℹ️ How to start a job:</strong><br/>
            {message}<br/><br/>
            <code style={{ background: theme.surface, padding: "4px 8px", borderRadius: 4 }}>
              az containerapp job start --name tbdev-scan-for-main --resource-group rg-tb-chest-counter-dev
            </code>
          </div>
        )}
      </div>

      {/* Stats */}
      {stats && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 15,
          marginBottom: 20
        }}>
          <div style={{
            background: theme.surface,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            padding: 15
          }}>
            <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Total Players (7d)</div>
            <div style={{ color: theme.gold, fontSize: 24, fontWeight: 600 }}>
              {stats.total_players || 0}
            </div>
          </div>
          <div style={{
            background: theme.surface,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            padding: 15
          }}>
            <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Total Chests (7d)</div>
            <div style={{ color: theme.gold, fontSize: 24, fontWeight: 600 }}>
              {stats.total_chests || 0}
            </div>
          </div>
          <div style={{
            background: theme.surface,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            padding: 15
          }}>
            <div style={{ color: theme.textMuted, fontSize: 12, marginBottom: 5 }}>Last Scan</div>
            <div style={{ color: theme.text, fontSize: 14 }}>
              {stats.last_scan ? new Date(stats.last_scan).toLocaleString() : "Never"}
            </div>
          </div>
        </div>
      )}

      {/* Recent Runs */}
      <div style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 10,
        padding: 20,
        marginBottom: 20
      }}>
        <h3 style={{ color: theme.gold, marginBottom: 15, fontSize: 16 }}>Recent Runs</h3>
        {runs.length === 0 ? (
          <p style={{ color: theme.textMuted, fontSize: 14 }}>No recent runs</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Started</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Status</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Found</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>New</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", color: theme.textMuted }}>Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${theme.border}20` }}>
                    <td style={{ padding: "8px 12px", color: theme.text, fontSize: 13 }}>
                      {new Date(run.startTime).toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{
                        color: run.status === "completed" ? theme.green :
                               run.status === "running" ? theme.gold :
                               run.status === "failed" ? theme.red : theme.textMuted,
                        fontWeight: 600
                      }}>
                        {run.status}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", color: theme.text }}>
                      {run.giftsFound || 0}
                    </td>
                    <td style={{ padding: "8px 12px", color: theme.green }}>
                      {run.newGifts || 0}
                    </td>
                    <td style={{ padding: "8px 12px", color: theme.textMuted, fontSize: 13 }}>
                      {run.duration || "—"}
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
          Activity Log {logs.length > 0 && `(${logs.length})`}
        </h3>
        <div style={{
          background: theme.bg,
          border: `1px solid ${theme.border}`,
          borderRadius: 6,
          padding: 15,
          maxHeight: 300,
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: 12,
          lineHeight: 1.5
        }}>
          {logs.length === 0 ? (
            <p style={{ color: theme.textMuted }}>No recent activity</p>
          ) : (
            logs.map((log, i) => (
              <div key={i} style={{ marginBottom: 8 }}>
                <span style={{ color: theme.textMuted }}>
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
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
    </div>
  );
}