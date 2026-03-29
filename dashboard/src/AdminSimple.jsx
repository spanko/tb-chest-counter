import { useState, useEffect, useCallback } from "react";

// Simplified admin panel that shows job status from database
export function AdminPanel({ theme, API_BASE }) {
  // Allow environment variable override for API base URL
  const apiBase = import.meta.env.VITE_API_BASE || API_BASE;
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [adminCode, setAdminCode] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [scheduleMode, setScheduleMode] = useState(false);
  const [cronExpression, setCronExpression] = useState("0 */30 * * * *");
  const [triggerMessage, setTriggerMessage] = useState("");
  const [diagnostics, setDiagnostics] = useState(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [targetSettings, setTargetSettings] = useState({
    weekly_chest_target: 30,
    weekly_point_target: 100,
    target_type: "chests"
  });
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetMessage, setTargetMessage] = useState("");

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
      const res = await fetch(`${apiBase}/admin?action=status`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
        setStats(data.stats || {});
      }
    } catch (e) {
      console.error("Failed to fetch status:", e);
    }
  }, [authorized, apiBase]);

  // Fetch logs
  const fetchLogs = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${apiBase}/admin?action=logs`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
      }
    } catch (e) {
      console.error("Failed to fetch logs:", e);
    }
  }, [authorized, apiBase]);

  // Fetch target settings
  const fetchTargetSettings = useCallback(async () => {
    if (!authorized) return;

    try {
      const res = await fetch(`${apiBase}/targets`);
      if (res.ok) {
        const data = await res.json();
        if (data.settings) {
          setTargetSettings({
            weekly_chest_target: data.settings.weekly_chest_target || 30,
            weekly_point_target: data.settings.weekly_point_target || 100,
            target_type: data.settings.target_type || "chests"
          });
        }
      }
    } catch (e) {
      console.error("Failed to fetch target settings:", e);
    }
  }, [authorized, apiBase]);

  // Save target settings
  const saveTargetSettings = async () => {
    setTargetLoading(true);
    setTargetMessage("");

    try {
      const res = await fetch(`${apiBase}/targets`, {
        method: "POST",
        headers: {
          "X-Admin-Code": "FOR2026-ADMIN",
          "Content-Type": "application/json"
        },
        body: JSON.stringify(targetSettings)
      });

      const data = await res.json();

      if (res.ok) {
        setTargetMessage("Settings saved successfully");
        setTimeout(() => setTargetMessage(""), 3000);
      } else {
        setTargetMessage(`Error: ${data.error}`);
      }
    } catch (e) {
      setTargetMessage(`Failed to save: ${e.message}`);
    } finally {
      setTargetLoading(false);
    }
  };

  // Trigger job
  const triggerJob = async () => {
    setTriggering(true);
    setTriggerMessage("");

    try {
      const res = await fetch(`${apiBase}/admin?action=trigger`, {
        method: "POST",
        headers: {
          "X-Admin-Code": "FOR2026-ADMIN",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          jobName: "tbdev-scan-for-main",
          resourceGroup: "rg-tb-chest-counter-dev"
        })
      });

      let data;
      try {
        data = await res.json();
      } catch (jsonErr) {
        console.error("Failed to parse response:", jsonErr);
        data = { error: "Invalid server response" };
      }

      if (res.ok && data) {
        if (data.cliCommand) {
          setTriggerMessage(
            <div>
              ✅ {data.message}<br/>
              <code style={{
                background: theme.surface,
                padding: "4px 8px",
                borderRadius: 4,
                fontSize: 12,
                display: "inline-block",
                marginTop: 8
              }}>
                {data.cliCommand}
              </code>
            </div>
          );
        } else {
          setTriggerMessage(`✅ ${data.message}`);
        }
        // Refresh status after trigger
        setTimeout(() => {
          fetchStatus();
          setTriggerMessage("");
        }, 5000);
      } else {
        setTriggerMessage(`❌ Error: ${data.error}`);
      }
    } catch (e) {
      setTriggerMessage(`❌ Failed to trigger job: ${e.message}`);
    } finally {
      setTriggering(false);
    }
  };

  // Fetch diagnostics
  const fetchDiagnostics = async () => {
    try {
      const res = await fetch(`${apiBase}/admin?action=health`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });

      // First check if response is ok
      if (!res.ok) {
        console.error("Diagnostics request failed:", res.status, res.statusText);
        setDiagnostics({
          error: `HTTP ${res.status}: ${res.statusText}`,
          details: "Server returned an error response"
        });
        return;
      }

      // Try to get response text first
      const text = await res.text();

      // Try to parse as JSON
      let data;
      try {
        data = text ? JSON.parse(text) : null;
      } catch (jsonErr) {
        console.error("Failed to parse diagnostics response:", jsonErr);
        console.error("Response text was:", text);
        setDiagnostics({
          error: "Invalid diagnostics response",
          details: text ? `Response: ${text.substring(0, 200)}` : "Empty response"
        });
        return;
      }

      if (data) {
        setDiagnostics(data);
      } else {
        setDiagnostics({
          error: "No data received",
          details: "Server returned empty response"
        });
      }
    } catch (e) {
      console.error("Diagnostics fetch error:", e);
      setDiagnostics({
        error: e.message,
        details: "Network or connection error"
      });
    }
  };

  // Update schedule
  const updateSchedule = async () => {
    setLoading(true);

    try {
      const res = await fetch(`${apiBase}/admin?action=schedule`, {
        method: "POST",
        headers: {
          "X-Admin-Code": "FOR2026-ADMIN",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          jobName: "tbdev-scan-for-main",
          resourceGroup: "rg-tb-chest-counter-dev",
          cronExpression: cronExpression
        })
      });

      let data;
      try {
        data = await res.json();
      } catch (jsonErr) {
        console.error("Failed to parse response:", jsonErr);
        data = { error: "Invalid server response" };
      }

      if (res.ok && data) {
        if (data.cliCommand) {
          setTriggerMessage(
            <div>
              ✅ {data.message}<br/>
              <code style={{
                background: theme.surface,
                padding: "4px 8px",
                borderRadius: 4,
                fontSize: 12,
                display: "inline-block",
                marginTop: 8
              }}>
                {data.cliCommand}
              </code>
            </div>
          );
        } else {
          setTriggerMessage(`✅ Schedule updated: ${data.cronExpression}`);
        }
        setScheduleMode(false);
      } else {
        setTriggerMessage(`❌ Error: ${data.error}`);
      }
    } catch (e) {
      setTriggerMessage(`❌ Failed to update schedule: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

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
      fetchTargetSettings();
    }
  }, [authorized, fetchStatus, fetchLogs, fetchTargetSettings]);

  if (!authorized) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <h2 style={{ color: theme.gold, marginBottom: 20 }}>Admin Access Required</h2>
        <input
          type="password"
          placeholder="Enter admin code"
          value={adminCode}
          onChange={(e) => setAdminCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && checkAdminAuth()}
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
            onClick={triggerJob}
            disabled={triggering}
            style={{
              padding: "8px 20px",
              background: triggering ? theme.border : theme.gold,
              color: triggering ? theme.textMuted : theme.bg,
              border: `1px solid ${theme.gold}`,
              borderRadius: 6,
              cursor: triggering ? "not-allowed" : "pointer",
              fontSize: 14,
              fontWeight: 600
            }}
          >
            {triggering ? "⏳ Triggering..." : "🚀 Start Scan"}
          </button>

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

          <button
            onClick={() => setScheduleMode(!scheduleMode)}
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
            ⏰ Schedule
          </button>

          <button
            onClick={() => {
              setShowDiagnostics(!showDiagnostics);
              if (!showDiagnostics) fetchDiagnostics();
            }}
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
            🔧 Diagnostics
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

        {triggerMessage && (
          <div style={{
            marginTop: 15,
            padding: 10,
            background: (typeof triggerMessage === 'string' && triggerMessage.startsWith("❌")) ? `${theme.red}20` : `${theme.green}20`,
            border: `1px solid ${(typeof triggerMessage === 'string' && triggerMessage.startsWith("❌")) ? theme.red : theme.green}`,
            borderRadius: 6,
            color: (typeof triggerMessage === 'string' && triggerMessage.startsWith("❌")) ? theme.red : theme.green,
            fontSize: 13
          }}>
            {triggerMessage}
          </div>
        )}

        {scheduleMode && (
          <div style={{
            marginTop: 15,
            padding: 15,
            background: theme.bg,
            border: `1px solid ${theme.border}`,
            borderRadius: 6
          }}>
            <h4 style={{ color: theme.gold, marginBottom: 10, fontSize: 14 }}>Configure Schedule</h4>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="text"
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                placeholder="Cron expression"
                style={{
                  padding: "6px 12px",
                  background: theme.surface,
                  border: `1px solid ${theme.border}`,
                  color: theme.text,
                  borderRadius: 4,
                  fontSize: 13,
                  width: 200
                }}
              />
              <button
                onClick={updateSchedule}
                disabled={loading}
                style={{
                  padding: "6px 16px",
                  background: theme.gold,
                  color: theme.bg,
                  border: "none",
                  borderRadius: 4,
                  cursor: loading ? "not-allowed" : "pointer",
                  fontSize: 13,
                  fontWeight: 600
                }}
              >
                {loading ? "Updating..." : "Update"}
              </button>
              <button
                onClick={() => setScheduleMode(false)}
                style={{
                  padding: "6px 16px",
                  background: "transparent",
                  color: theme.textMuted,
                  border: `1px solid ${theme.border}`,
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: 13
                }}
              >
                Cancel
              </button>
            </div>
            <div style={{ marginTop: 10, color: theme.textMuted, fontSize: 12 }}>
              <strong>Examples:</strong><br/>
              • Every 30 mins: <code>0 */30 * * * *</code><br/>
              • Every hour: <code>0 0 * * * *</code><br/>
              • Every 6 hours: <code>0 0 */6 * * *</code><br/>
              • Format: <code>second minute hour day month weekday</code>
            </div>
          </div>
        )}

        {showDiagnostics && diagnostics && (
          <div style={{
            marginTop: 15,
            padding: 15,
            background: theme.bg,
            border: `1px solid ${theme.border}`,
            borderRadius: 6
          }}>
            <h4 style={{ color: theme.gold, marginBottom: 10, fontSize: 14 }}>System Diagnostics</h4>
            {diagnostics.error ? (
              <div>
                <div style={{ color: theme.red, marginBottom: 10 }}>❌ Error: {diagnostics.error}</div>
                {diagnostics.details && (
                  <div style={{
                    color: theme.textMuted,
                    fontSize: 12,
                    background: theme.surface,
                    padding: 10,
                    borderRadius: 4,
                    fontFamily: "monospace"
                  }}>
                    {diagnostics.details}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 13 }}>
                <div style={{ marginBottom: 10 }}>
                  <strong style={{ color: theme.text }}>Database Connection:</strong>{" "}
                  <span style={{ color: diagnostics.connection ? theme.green : theme.red }}>
                    {diagnostics.connection ? "✅ Connected" : "❌ Disconnected"}
                  </span>
                </div>

                <div style={{ marginBottom: 10 }}>
                  <strong style={{ color: theme.text }}>Status:</strong>{" "}
                  <span style={{
                    color: diagnostics.status === "healthy" ? theme.green : theme.red,
                    textTransform: "capitalize"
                  }}>
                    {diagnostics.status}
                  </span>
                </div>

                <div style={{ marginBottom: 10 }}>
                  <strong style={{ color: theme.text }}>Tables:</strong>
                </div>

                <div style={{
                  background: theme.surface,
                  border: `1px solid ${theme.border}`,
                  borderRadius: 4,
                  padding: 10,
                  fontFamily: "monospace",
                  fontSize: 12
                }}>
                  {Object.entries(diagnostics.tables || {}).map(([table, info]) => (
                    <div key={table} style={{ marginBottom: 8 }}>
                      <strong>{table}:</strong>{" "}
                      {info.exists !== undefined ? (
                        info.exists ? (
                          <span style={{ color: theme.green }}>
                            ✅ Exists
                            {info.count !== undefined && ` (${info.count} records)`}
                            {info.lastRun && (
                              <span style={{ color: theme.textMuted, marginLeft: 10 }}>
                                Last: {new Date(info.lastRun).toLocaleString()}
                              </span>
                            )}
                            {info.lastScan && (
                              <span style={{ color: theme.textMuted, marginLeft: 10 }}>
                                Last: {new Date(info.lastScan).toLocaleString()}
                              </span>
                            )}
                          </span>
                        ) : (
                          <span style={{ color: theme.red }}>
                            ❌ Not found: {info.error}
                          </span>
                        )
                      ) : (
                        <span style={{ color: theme.textMuted }}>Unknown</span>
                      )}
                    </div>
                  ))}
                </div>

                {diagnostics.errors && diagnostics.errors.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <strong style={{ color: theme.red }}>Errors:</strong>
                    {diagnostics.errors.map((err, i) => (
                      <div key={i} style={{ color: theme.red, fontSize: 12, marginTop: 5 }}>
                        • {err}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
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

      {/* Weekly Targets */}
      <div style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 10,
        padding: 20,
        marginBottom: 20
      }}>
        <h3 style={{ color: theme.gold, marginBottom: 15, fontSize: 16 }}>Weekly Targets</h3>
        <p style={{ color: theme.textMuted, fontSize: 13, marginBottom: 15 }}>
          Set weekly contribution targets for clan members. These appear as progress bars on the leaderboard.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 15, marginBottom: 15 }}>
          <div>
            <label style={{ display: "block", color: theme.textMuted, fontSize: 12, marginBottom: 6 }}>
              Target Type
            </label>
            <select
              value={targetSettings.target_type}
              onChange={(e) => setTargetSettings(s => ({ ...s, target_type: e.target.value }))}
              style={{
                width: "100%",
                padding: "8px 12px",
                background: theme.bg,
                border: `1px solid ${theme.border}`,
                color: theme.text,
                borderRadius: 6,
                fontSize: 14,
                cursor: "pointer"
              }}
            >
              <option value="chests">Chests per week</option>
              <option value="points">Points per week</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", color: theme.textMuted, fontSize: 12, marginBottom: 6 }}>
              Weekly Chest Target
            </label>
            <input
              type="number"
              value={targetSettings.weekly_chest_target}
              onChange={(e) => setTargetSettings(s => ({ ...s, weekly_chest_target: parseInt(e.target.value) || 0 }))}
              style={{
                width: "100%",
                padding: "8px 12px",
                background: theme.bg,
                border: `1px solid ${theme.border}`,
                color: theme.text,
                borderRadius: 6,
                fontSize: 14,
                boxSizing: "border-box"
              }}
            />
          </div>

          <div>
            <label style={{ display: "block", color: theme.textMuted, fontSize: 12, marginBottom: 6 }}>
              Weekly Point Target
            </label>
            <input
              type="number"
              value={targetSettings.weekly_point_target}
              onChange={(e) => setTargetSettings(s => ({ ...s, weekly_point_target: parseInt(e.target.value) || 0 }))}
              style={{
                width: "100%",
                padding: "8px 12px",
                background: theme.bg,
                border: `1px solid ${theme.border}`,
                color: theme.text,
                borderRadius: 6,
                fontSize: 14,
                boxSizing: "border-box"
              }}
            />
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 15 }}>
          <button
            onClick={saveTargetSettings}
            disabled={targetLoading}
            style={{
              padding: "8px 20px",
              background: targetLoading ? theme.border : theme.gold,
              color: targetLoading ? theme.textMuted : theme.bg,
              border: "none",
              borderRadius: 6,
              cursor: targetLoading ? "not-allowed" : "pointer",
              fontSize: 14,
              fontWeight: 600
            }}
          >
            {targetLoading ? "Saving..." : "Save Targets"}
          </button>

          {targetMessage && (
            <span style={{
              color: targetMessage.startsWith("Error") ? theme.red : theme.green,
              fontSize: 13
            }}>
              {targetMessage.startsWith("Error") ? "❌" : "✅"} {targetMessage}
            </span>
          )}
        </div>
      </div>

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