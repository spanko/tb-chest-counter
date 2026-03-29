import { useState, useEffect, useCallback } from "react";

export function RosterPanel({ theme, API_BASE }) {
  const [roster, setRoster] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [bulkInput, setBulkInput] = useState("");
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  // Fetch current roster
  const fetchRoster = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/admin?action=roster`, {
        headers: { "X-Admin-Code": "FOR2026-ADMIN" }
      });
      if (!res.ok) throw new Error(`API Error: ${res.status}`);
      const data = await res.json();
      setRoster(data.roster || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [API_BASE]);

  useEffect(() => {
    fetchRoster();
  }, [fetchRoster]);

  // Add single member
  const addMember = async () => {
    if (!newName.trim()) return;

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/admin?action=add-roster-member`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ name: newName.trim(), addedBy: "admin-ui" })
      });
      if (!res.ok) throw new Error("Failed to add member");
      setNewName("");
      fetchRoster();
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  // Remove single member
  const removeMember = async (name) => {
    if (!confirm(`Remove "${name}" from roster?`)) return;

    try {
      const res = await fetch(`${API_BASE}/admin?action=remove-roster-member`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ name })
      });
      if (!res.ok) throw new Error("Failed to remove member");
      fetchRoster();
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  // Bulk update roster
  const saveBulkRoster = async () => {
    const names = bulkInput
      .split('\n')
      .map(n => n.trim())
      .filter(n => n.length > 0);

    if (names.length === 0) {
      alert("No names to save");
      return;
    }

    if (!confirm(`Replace entire roster with ${names.length} names?`)) return;

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/admin?action=update-roster`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Code": "FOR2026-ADMIN"
        },
        body: JSON.stringify({ names, addedBy: "bulk-import" })
      });
      if (!res.ok) throw new Error("Failed to update roster");
      setShowBulkEdit(false);
      setBulkInput("");
      fetchRoster();
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  // Load current roster into bulk editor
  const loadRosterIntoBulk = () => {
    setBulkInput(roster.map(r => r.name).join('\n'));
    setShowBulkEdit(true);
  };

  return (
    <div>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 16
      }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: theme.text, marginBottom: 4 }}>
            Clan Roster
          </h2>
          <p style={{ fontSize: 12, color: theme.textMuted }}>
            {roster.length} members - Used by scanner for name matching
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={loadRosterIntoBulk}
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
            Bulk Edit
          </button>
          <button
            onClick={fetchRoster}
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
      </div>

      {/* Bulk Edit Panel */}
      {showBulkEdit && (
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.gold}`,
          borderRadius: 10,
          padding: 16,
          marginBottom: 16
        }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 12
          }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, color: theme.text }}>
              Bulk Edit Roster
            </h3>
            <button
              onClick={() => setShowBulkEdit(false)}
              style={{
                background: "none",
                border: "none",
                fontSize: 18,
                color: theme.textMuted,
                cursor: "pointer"
              }}
            >
              ×
            </button>
          </div>
          <p style={{ fontSize: 12, color: theme.textMuted, marginBottom: 12 }}>
            Paste your full clan roster (one name per line). This will replace the existing roster.
          </p>
          <textarea
            value={bulkInput}
            onChange={(e) => setBulkInput(e.target.value)}
            placeholder="Player Name 1&#10;Player Name 2&#10;Player Name 3"
            style={{
              width: "100%",
              minHeight: 200,
              padding: 10,
              fontSize: 12,
              border: `1px solid ${theme.border}`,
              borderRadius: 6,
              background: theme.bg,
              color: theme.text,
              fontFamily: "monospace",
              resize: "vertical",
              marginBottom: 12
            }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={saveBulkRoster}
              disabled={saving}
              style={{
                padding: "8px 16px",
                fontSize: 13,
                fontWeight: 500,
                border: "none",
                borderRadius: 6,
                cursor: saving ? "not-allowed" : "pointer",
                background: saving ? theme.border : theme.gold,
                color: "#fff"
              }}
            >
              {saving ? "Saving..." : `Save Roster (${bulkInput.split('\n').filter(n => n.trim()).length} names)`}
            </button>
            <button
              onClick={() => setShowBulkEdit(false)}
              style={{
                padding: "8px 16px",
                fontSize: 13,
                border: `1px solid ${theme.border}`,
                borderRadius: 6,
                cursor: "pointer",
                background: "transparent",
                color: theme.textMuted
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Add Single Member */}
      <div style={{
        display: "flex",
        gap: 8,
        marginBottom: 16
      }}>
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addMember()}
          placeholder="Add new member..."
          style={{
            flex: 1,
            padding: "8px 12px",
            fontSize: 13,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            background: theme.bg,
            color: theme.text
          }}
        />
        <button
          onClick={addMember}
          disabled={saving || !newName.trim()}
          style={{
            padding: "8px 16px",
            fontSize: 13,
            fontWeight: 500,
            border: "none",
            borderRadius: 6,
            cursor: saving || !newName.trim() ? "not-allowed" : "pointer",
            background: saving || !newName.trim() ? theme.border : theme.green,
            color: "#fff"
          }}
        >
          Add
        </button>
      </div>

      {/* Roster List */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 40, color: theme.textMuted }}>
          Loading...
        </div>
      ) : error ? (
        <div style={{ textAlign: "center", padding: 40, color: theme.red }}>
          {error}
        </div>
      ) : roster.length === 0 ? (
        <div style={{
          textAlign: "center",
          padding: 40,
          color: theme.textMuted,
          background: theme.surface,
          borderRadius: 10
        }}>
          <p style={{ marginBottom: 12 }}>No roster configured yet.</p>
          <p style={{ fontSize: 12 }}>
            Use "Bulk Edit" to paste your clan member list, or add members one at a time.
          </p>
        </div>
      ) : (
        <div style={{
          background: theme.surface,
          border: `1px solid ${theme.border}`,
          borderRadius: 10,
          overflow: "hidden"
        }}>
          <div style={{
            maxHeight: 400,
            overflowY: "auto"
          }}>
            {roster.map((member, i) => (
              <div
                key={member.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "10px 14px",
                  borderBottom: i < roster.length - 1 ? `1px solid ${theme.border}` : "none"
                }}
              >
                <div>
                  <span style={{ fontSize: 13, color: theme.text }}>
                    {member.name}
                  </span>
                  <span style={{
                    fontSize: 11,
                    color: theme.textMuted,
                    marginLeft: 8
                  }}>
                    added {new Date(member.addedAt).toLocaleDateString()}
                  </span>
                </div>
                <button
                  onClick={() => removeMember(member.name)}
                  style={{
                    padding: "4px 10px",
                    fontSize: 11,
                    border: `1px solid ${theme.border}`,
                    borderRadius: 4,
                    cursor: "pointer",
                    background: "transparent",
                    color: theme.red
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scanner Info */}
      <div style={{
        marginTop: 16,
        padding: 12,
        background: `${theme.gold}10`,
        border: `1px solid ${theme.gold}30`,
        borderRadius: 8
      }}>
        <p style={{ fontSize: 12, color: theme.text }}>
          <strong>Scanner Integration:</strong> The scanner can fetch this roster from{" "}
          <code style={{ background: theme.bg, padding: "2px 6px", borderRadius: 4 }}>
            /api/roster
          </code>{" "}
          to match OCR-detected names during scans.
        </p>
      </div>
    </div>
  );
}
