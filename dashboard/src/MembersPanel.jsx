import { useState, useEffect, useCallback } from "react";

// Members management panel for tracking aliases and departed players
export function MembersPanel({ theme, API_BASE }) {
  const [members, setMembers] = useState([]);
  const [canonicalNames, setCanonicalNames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all"); // all, active, left, aliased
  const [search, setSearch] = useState("");
  const [editingAlias, setEditingAlias] = useState(null);
  const [editingStatus, setEditingStatus] = useState(null);

  // AI recommendations state
  const [showRecommendations, setShowRecommendations] = useState(false);
  const [recommendations, setRecommendations] = useState([]);
  const [recStats, setRecStats] = useState(null);
  const [loadingRecs, setLoadingRecs] = useState(false);

  // Fetch members data
  const fetchMembers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/mgmt?action=members`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      setMembers(data.members || []);
      setCanonicalNames(data.canonicalNames || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [API_BASE]);

  useEffect(() => {
    fetchMembers();
  }, [fetchMembers]);

  // Add/update alias
  const saveAlias = async (rawName, canonicalName) => {
    try {
      const res = await fetch(`${API_BASE}/mgmt?action=alias`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ rawName, canonicalName })
      });
      if (!res.ok) throw new Error("Failed to save alias");
      setEditingAlias(null);
      fetchMembers();
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  // Remove alias
  const removeAlias = async (rawName) => {
    if (!confirm(`Remove alias for ${rawName}?`)) return;
    try {
      const res = await fetch(`${API_BASE}/mgmt?action=alias`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ rawName, remove: true })
      });
      if (!res.ok) throw new Error("Failed to remove alias");
      fetchMembers();
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  // Update member status
  const updateStatus = async (playerName, status, notes) => {
    try {
      const res = await fetch(`${API_BASE}/mgmt?action=member-status`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ playerName, status, notes })
      });
      if (!res.ok) throw new Error("Failed to update status");
      setEditingStatus(null);
      fetchMembers();
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  // Request AI recommendations (uses roster from database)
  const requestRecommendations = async () => {
    setLoadingRecs(true);
    try {
      const res = await fetch(`${API_BASE}/mgmt?action=suggest-aliases`, {
        method: "GET",
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || "Failed to get recommendations");
      }
      const data = await res.json();
      setRecommendations(data.recommendations || []);
      setRecStats(data.stats || null);
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setLoadingRecs(false);
    }
  };

  // Apply a recommendation
  const applyRecommendation = async (rec) => {
    try {
      if (rec.type === "alias" && rec.canonical) {
        await saveAlias(rec.detected, rec.canonical);
      } else if (rec.type === "add_to_roster" && rec.detected) {
        // Add to roster
        const res = await fetch(`${API_BASE}/mgmt?action=add-roster-member`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Admin-Code": "FOR2026-ADMIN"
          },
          body: JSON.stringify({ name: rec.detected, addedBy: "ai-recommendation" })
        });
        if (!res.ok) throw new Error("Failed to add to roster");
      } else if (rec.type === "remove_from_roster" && rec.rosterName) {
        // Remove from roster
        const res = await fetch(`${API_BASE}/mgmt?action=remove-roster-member`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Admin-Code": "FOR2026-ADMIN"
          },
          body: JSON.stringify({ name: rec.rosterName })
        });
        if (!res.ok) throw new Error("Failed to remove from roster");
      }
      // Remove from recommendations list
      setRecommendations(prev => prev.filter(r => r !== rec));
      fetchMembers();
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  // Dismiss a recommendation
  const dismissRecommendation = (rec) => {
    setRecommendations(prev => prev.filter(r => r !== rec));
  };

  // Filter members
  const filteredMembers = members.filter(m => {
    // Search filter
    if (search && !m.name.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    // Status filter
    switch (filter) {
      case "active":
        return m.status === "active" && !m.canonicalName;
      case "left":
        return m.status === "left";
      case "aliased":
        return m.canonicalName != null;
      default:
        return true;
    }
  });

  // Stats
  const totalMembers = members.length;
  const activeMembers = members.filter(m => m.status === "active" && !m.canonicalName).length;
  const leftMembers = members.filter(m => m.status === "left").length;
  const aliasedNames = members.filter(m => m.canonicalName != null).length;

  const formatDate = (dateStr) => {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    return d.toLocaleDateString();
  };

  const daysSince = (dateStr) => {
    if (!dateStr) return null;
    const d = new Date(dateStr);
    const now = new Date();
    return Math.floor((now - d) / (1000 * 60 * 60 * 24));
  };

  return (
    <div>
      {/* Stats Row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
        marginBottom: 20
      }}>
        <StatCard label="Total Names" value={totalMembers} theme={theme} />
        <StatCard label="Active Members" value={activeMembers} theme={theme} color={theme.green} />
        <StatCard label="Left Clan" value={leftMembers} theme={theme} color={theme.red} />
        <StatCard label="Aliased Names" value={aliasedNames} theme={theme} color={theme.gold} />
      </div>

      {/* Filters */}
      <div style={{
        display: "flex",
        gap: 12,
        marginBottom: 16,
        flexWrap: "wrap",
        alignItems: "center"
      }}>
        <input
          type="text"
          placeholder="Search names..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            padding: "8px 12px",
            fontSize: 13,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            background: theme.surface,
            color: theme.text,
            width: 200
          }}
        />
        <div style={{ display: "flex", gap: 4 }}>
          {[
            { key: "all", label: "All" },
            { key: "active", label: "Active" },
            { key: "left", label: "Left" },
            { key: "aliased", label: "Aliased" }
          ].map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 500,
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                background: filter === f.key ? theme.gold : theme.surfaceAlt,
                color: filter === f.key ? "#fff" : theme.textMuted
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => {
            setShowRecommendations(!showRecommendations);
            if (!showRecommendations && recommendations.length === 0) {
              requestRecommendations();
            }
          }}
          disabled={loadingRecs}
          style={{
            padding: "6px 14px",
            fontSize: 12,
            border: `1px solid ${theme.gold}`,
            borderRadius: 6,
            cursor: loadingRecs ? "wait" : "pointer",
            background: showRecommendations ? theme.gold : "transparent",
            color: showRecommendations ? "#fff" : theme.gold,
            marginLeft: "auto"
          }}
        >
          {loadingRecs ? "Analyzing..." : "AI Recommendations"}
        </button>
        <button
          onClick={fetchMembers}
          style={{
            padding: "6px 14px",
            fontSize: 12,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            cursor: "pointer",
            background: "transparent",
            color: theme.textMuted
          }}
        >
          Refresh
        </button>
      </div>

      {/* AI Recommendations Panel */}
      {showRecommendations && (
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.gold}`,
          borderRadius: 10,
          padding: 16,
          marginBottom: 16
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, color: theme.text, margin: 0 }}>
              AI Recommendations
            </h3>
            <button
              onClick={requestRecommendations}
              disabled={loadingRecs}
              style={{
                padding: "6px 12px",
                fontSize: 12,
                border: `1px solid ${theme.border}`,
                borderRadius: 6,
                cursor: loadingRecs ? "wait" : "pointer",
                background: "transparent",
                color: theme.textMuted
              }}
            >
              {loadingRecs ? "Analyzing..." : "Refresh"}
            </button>
          </div>

          {recStats && (
            <div style={{
              display: "flex",
              gap: 16,
              fontSize: 12,
              color: theme.textMuted,
              marginBottom: 12,
              padding: "8px 12px",
              background: theme.bg,
              borderRadius: 6
            }}>
              <span>Roster: <strong style={{ color: theme.text }}>{recStats.rosterCount}</strong></span>
              <span>Detected names: <strong style={{ color: theme.text }}>{recStats.detectedCount}</strong></span>
              <span>Unaliased: <strong style={{ color: theme.gold }}>{recStats.unaliasedCount}</strong></span>
              <span>Unseen roster: <strong style={{ color: theme.red }}>{recStats.unseenRosterCount}</strong></span>
            </div>
          )}

          {loadingRecs ? (
            <div style={{ textAlign: "center", padding: 20, color: theme.textMuted }}>
              Claude is analyzing your roster and detected names...
            </div>
          ) : recommendations.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {recommendations.map((rec, idx) => (
                <RecommendationRow
                  key={`${rec.type}-${rec.detected || rec.rosterName}-${idx}`}
                  recommendation={rec}
                  onApply={() => applyRecommendation(rec)}
                  onDismiss={() => dismissRecommendation(rec)}
                  theme={theme}
                />
              ))}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: 20, color: theme.green }}>
              No recommendations - roster and detected names are in sync!
            </div>
          )}
        </div>
      )}

      {/* Members Table */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 40, color: theme.textMuted }}>
          Loading...
        </div>
      ) : error ? (
        <div style={{ textAlign: "center", padding: 40, color: theme.red }}>
          {error}
        </div>
      ) : (
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.border}`,
          borderRadius: 10,
          overflow: "hidden"
        }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${theme.border}`, background: theme.surfaceAlt }}>
                <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 500, color: theme.textMuted }}>Name</th>
                <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 500, color: theme.textMuted }}>Alias Of</th>
                <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 500, color: theme.textMuted }}>Status</th>
                <th style={{ padding: "10px 12px", textAlign: "right", fontWeight: 500, color: theme.textMuted }}>Chests</th>
                <th style={{ padding: "10px 12px", textAlign: "right", fontWeight: 500, color: theme.textMuted }}>Last Seen</th>
                <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 500, color: theme.textMuted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredMembers.map((m) => {
                const inactive = daysSince(m.lastSeen) > 14;
                return (
                  <tr
                    key={m.name}
                    style={{
                      borderBottom: `1px solid ${theme.border}20`,
                      opacity: m.status === "left" ? 0.6 : 1
                    }}
                  >
                    <td style={{ padding: "10px 12px", color: theme.text, fontWeight: 500 }}>
                      {m.name}
                      {m.notes && (
                        <span style={{ marginLeft: 6, fontSize: 11, color: theme.textMuted }}>
                          ({m.notes})
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      {editingAlias === m.name ? (
                        <AliasEditor
                          currentAlias={m.canonicalName}
                          canonicalNames={canonicalNames.filter(n => n !== m.name)}
                          onSave={(canonical) => saveAlias(m.name, canonical)}
                          onCancel={() => setEditingAlias(null)}
                          theme={theme}
                        />
                      ) : m.canonicalName ? (
                        <span style={{ color: theme.gold, fontSize: 12 }}>
                          → {m.canonicalName}
                          <button
                            onClick={() => removeAlias(m.name)}
                            style={{
                              marginLeft: 8,
                              background: "none",
                              border: "none",
                              color: theme.red,
                              cursor: "pointer",
                              fontSize: 11
                            }}
                          >
                            ✕
                          </button>
                        </span>
                      ) : (
                        <span style={{ color: theme.textMuted, fontSize: 12 }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "center" }}>
                      {editingStatus === m.name ? (
                        <StatusEditor
                          currentStatus={m.status}
                          currentNotes={m.notes}
                          onSave={(status, notes) => updateStatus(m.name, status, notes)}
                          onCancel={() => setEditingStatus(null)}
                          theme={theme}
                        />
                      ) : (
                        <StatusBadge status={m.status} inactive={inactive} theme={theme} />
                      )}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: theme.textMuted }}>
                      {m.chestCount}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: inactive ? theme.red : theme.textMuted, fontSize: 12 }}>
                      {formatDate(m.lastSeen)}
                      {inactive && !m.canonicalName && m.status !== "left" && (
                        <span style={{ marginLeft: 4, color: theme.red }}>({daysSince(m.lastSeen)}d)</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "center" }}>
                      <div style={{ display: "flex", gap: 6, justifyContent: "center" }}>
                        {!m.canonicalName && (
                          <button
                            onClick={() => setEditingAlias(m.name)}
                            style={{
                              padding: "4px 8px",
                              fontSize: 11,
                              border: `1px solid ${theme.border}`,
                              borderRadius: 4,
                              background: "transparent",
                              color: theme.textMuted,
                              cursor: "pointer"
                            }}
                          >
                            Alias
                          </button>
                        )}
                        <button
                          onClick={() => setEditingStatus(m.name)}
                          style={{
                            padding: "4px 8px",
                            fontSize: 11,
                            border: `1px solid ${theme.border}`,
                            borderRadius: 4,
                            background: "transparent",
                            color: theme.textMuted,
                            cursor: "pointer"
                          }}
                        >
                          Status
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filteredMembers.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: theme.textMuted }}>
              No members match the current filter
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Stat card component
function StatCard({ label, value, theme, color }) {
  return (
    <div style={{
      background: theme.surface,
      border: `1px solid ${theme.border}`,
      borderRadius: 8,
      padding: 14
    }}>
      <div style={{ fontSize: 11, color: theme.textMuted, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: color || theme.text }}>{value}</div>
    </div>
  );
}

// Status badge component
function StatusBadge({ status, inactive, theme }) {
  const colors = {
    active: { bg: `${theme.green}15`, text: theme.green },
    left: { bg: `${theme.red}15`, text: theme.red }
  };
  const c = colors[status] || colors.active;

  return (
    <span style={{
      display: "inline-block",
      padding: "3px 10px",
      borderRadius: 12,
      fontSize: 11,
      fontWeight: 500,
      background: c.bg,
      color: c.text
    }}>
      {status === "left" ? "Left" : inactive ? "Inactive" : "Active"}
    </span>
  );
}

// Inline alias editor
function AliasEditor({ currentAlias, canonicalNames, onSave, onCancel, theme }) {
  const [selected, setSelected] = useState(currentAlias || "");

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <select
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        style={{
          padding: "4px 8px",
          fontSize: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: theme.surface,
          color: theme.text,
          maxWidth: 150
        }}
      >
        <option value="">Select player...</option>
        {canonicalNames.map(name => (
          <option key={name} value={name}>{name}</option>
        ))}
      </select>
      <button
        onClick={() => selected && onSave(selected)}
        disabled={!selected}
        style={{
          padding: "4px 8px",
          fontSize: 11,
          border: "none",
          borderRadius: 4,
          background: selected ? theme.green : theme.border,
          color: "#fff",
          cursor: selected ? "pointer" : "not-allowed"
        }}
      >
        Save
      </button>
      <button
        onClick={onCancel}
        style={{
          padding: "4px 8px",
          fontSize: 11,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: "transparent",
          color: theme.textMuted,
          cursor: "pointer"
        }}
      >
        Cancel
      </button>
    </div>
  );
}

// Inline status editor
function StatusEditor({ currentStatus, currentNotes, onSave, onCancel, theme }) {
  const [status, setStatus] = useState(currentStatus || "active");
  const [notes, setNotes] = useState(currentNotes || "");

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        style={{
          padding: "4px 8px",
          fontSize: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: theme.surface,
          color: theme.text
        }}
      >
        <option value="active">Active</option>
        <option value="left">Left</option>
      </select>
      <input
        type="text"
        placeholder="Notes..."
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        style={{
          padding: "4px 8px",
          fontSize: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: theme.surface,
          color: theme.text,
          width: 100
        }}
      />
      <button
        onClick={() => onSave(status, notes)}
        style={{
          padding: "4px 8px",
          fontSize: 11,
          border: "none",
          borderRadius: 4,
          background: theme.green,
          color: "#fff",
          cursor: "pointer"
        }}
      >
        Save
      </button>
      <button
        onClick={onCancel}
        style={{
          padding: "4px 8px",
          fontSize: 11,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: "transparent",
          color: theme.textMuted,
          cursor: "pointer"
        }}
      >
        Cancel
      </button>
    </div>
  );
}

// AI recommendation row
function RecommendationRow({ recommendation, onApply, onDismiss, theme }) {
  const { type, detected, canonical, rosterName, reason, confidence } = recommendation;

  const typeConfig = {
    alias: {
      bg: `${theme.gold}15`,
      text: theme.gold,
      label: "Alias",
      icon: "→",
      actionLabel: "Create Alias"
    },
    add_to_roster: {
      bg: `${theme.green}15`,
      text: theme.green,
      label: "Add to Roster",
      icon: "+",
      actionLabel: "Add"
    },
    remove_from_roster: {
      bg: `${theme.red}15`,
      text: theme.red,
      label: "Consider Removing",
      icon: "−",
      actionLabel: "Remove"
    }
  };
  const config = typeConfig[type] || typeConfig.alias;

  const displayName = type === "remove_from_roster" ? rosterName : detected;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "10px 12px",
      background: theme.bg,
      borderRadius: 6,
      border: `1px solid ${theme.border}`
    }}>
      <span style={{
        width: 24,
        height: 24,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "50%",
        background: config.bg,
        color: config.text,
        fontWeight: 600,
        fontSize: 14
      }}>
        {config.icon}
      </span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: theme.text }}>
          {displayName}
          {type === "alias" && canonical && (
            <span style={{ color: theme.gold, marginLeft: 6 }}>→ {canonical}</span>
          )}
        </div>
        {reason && (
          <div style={{ fontSize: 11, color: theme.textMuted, marginTop: 2 }}>
            {reason}
          </div>
        )}
      </div>
      <span style={{
        padding: "3px 10px",
        borderRadius: 12,
        fontSize: 11,
        fontWeight: 500,
        background: config.bg,
        color: config.text
      }}>
        {config.label}
      </span>
      {confidence && (
        <span style={{ fontSize: 11, color: theme.textMuted, minWidth: 35 }}>
          {Math.round(confidence * 100)}%
        </span>
      )}
      <button
        onClick={onApply}
        style={{
          padding: "4px 10px",
          fontSize: 11,
          border: "none",
          borderRadius: 4,
          background: config.text,
          color: "#fff",
          cursor: "pointer"
        }}
      >
        {config.actionLabel}
      </button>
      <button
        onClick={onDismiss}
        style={{
          padding: "4px 10px",
          fontSize: 11,
          border: `1px solid ${theme.border}`,
          borderRadius: 4,
          background: "transparent",
          color: theme.textMuted,
          cursor: "pointer"
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
