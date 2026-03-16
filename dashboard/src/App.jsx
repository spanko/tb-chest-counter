import { useState, useEffect, useCallback } from "react";
import { AdminPanel } from "./AdminSimple";

// ── Config ──────────────────────────────────────────────────────────────────
const ACCESS_CODE = "FOR2026"; // Change this or move to env var
const API_BASE = "/api"; // SWA Functions proxy

// ── Time Ranges ─────────────────────────────────────────────────────────────
const TIME_RANGES = [
  { key: "1h", label: "1 Hour", hours: 1 },
  { key: "8h", label: "8 Hours", hours: 8 },
  { key: "24h", label: "24 Hours", hours: 24 },
  { key: "7d", label: "Last Week", hours: 168 },
  { key: "30d", label: "Last Month", hours: 720 },
];

// ── Styles ──────────────────────────────────────────────────────────────────
const font = `'Cinzel', serif`;
const fontBody = `'Fira Sans', sans-serif`;

const theme = {
  bg: "#0a0c10",
  surface: "#12151c",
  surfaceHover: "#1a1e28",
  border: "#1f2533",
  gold: "#c9a227",
  goldDim: "#8b7019",
  goldBright: "#f0d060",
  text: "#d4d4d8",
  textMuted: "#6b7084",
  textBright: "#f0f0f5",
  green: "#4ade80",
  red: "#f87171",
  rank1: "#f0d060",
  rank2: "#b0b8c8",
  rank3: "#cd7f32",
};

// ── Gate Screen ─────────────────────────────────────────────────────────────
function GateScreen({ onUnlock }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState(false);
  const [shake, setShake] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (code.trim().toUpperCase() === ACCESS_CODE) {
      sessionStorage.setItem("tb-dash-auth", "1");
      onUnlock();
    } else {
      setError(true);
      setShake(true);
      setTimeout(() => setShake(false), 500);
    }
  };

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: `radial-gradient(ellipse at 50% 30%, #1a1510 0%, ${theme.bg} 70%)`,
      fontFamily: fontBody,
    }}>
      <form onSubmit={handleSubmit} style={{
        background: theme.surface, border: `1px solid ${theme.border}`,
        borderRadius: 12, padding: "48px 40px", width: 360, textAlign: "center",
        animation: shake ? "shake 0.4s ease" : "fadeIn 0.6s ease",
      }}>
        <div style={{
          fontSize: 42, marginBottom: 8, filter: "drop-shadow(0 0 12px rgba(201,162,39,0.3))",
        }}>⚔️</div>
        <h1 style={{
          fontFamily: font, fontSize: 22, color: theme.gold, margin: "0 0 6px",
          letterSpacing: 2, textTransform: "uppercase",
        }}>Chest Counter</h1>
        <p style={{ color: theme.textMuted, fontSize: 13, margin: "0 0 28px" }}>
          Enter access code to continue
        </p>
        <input
          type="password"
          value={code}
          onChange={(e) => { setCode(e.target.value); setError(false); }}
          placeholder="Access code"
          autoFocus
          style={{
            width: "100%", padding: "12px 16px", fontSize: 15, borderRadius: 8,
            border: `1px solid ${error ? theme.red : theme.border}`,
            background: theme.bg, color: theme.textBright, outline: "none",
            fontFamily: fontBody, letterSpacing: 1, textAlign: "center",
            boxSizing: "border-box",
            transition: "border-color 0.2s",
          }}
        />
        {error && (
          <p style={{ color: theme.red, fontSize: 12, margin: "10px 0 0" }}>
            Invalid code. Try again.
          </p>
        )}
        <button type="submit" style={{
          width: "100%", marginTop: 18, padding: "12px 0", fontSize: 14,
          fontFamily: font, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
          background: `linear-gradient(135deg, ${theme.gold}, ${theme.goldDim})`,
          color: theme.bg, border: "none", borderRadius: 8, cursor: "pointer",
          transition: "transform 0.15s, box-shadow 0.15s",
        }}
          onMouseDown={(e) => e.currentTarget.style.transform = "scale(0.97)"}
          onMouseUp={(e) => e.currentTarget.style.transform = "scale(1)"}
        >Enter</button>
      </form>
    </div>
  );
}

// ── Stat Card ───────────────────────────────────────────────────────────────
function StatCard({ label, value, icon }) {
  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "18px 22px", flex: "1 1 140px", minWidth: 140,
    }}>
      <div style={{ fontSize: 12, color: theme.textMuted, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: 28, fontFamily: font, color: theme.goldBright, fontWeight: 700 }}>
        {value != null ? value.toLocaleString() : "—"}
      </div>
    </div>
  );
}

// ── Player Row ──────────────────────────────────────────────────────────────
function PlayerRow({ rank, player, onSelect, isExpanded, breakdown }) {
  const rankColor = rank === 1 ? theme.rank1 : rank === 2 ? theme.rank2 : rank === 3 ? theme.rank3 : theme.textMuted;
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `${rank}`;

  return (
    <>
      <tr
        onClick={() => onSelect(player.player_name)}
        style={{
          cursor: "pointer",
          background: isExpanded ? theme.surfaceHover : "transparent",
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => { if (!isExpanded) e.currentTarget.style.background = theme.surfaceHover; }}
        onMouseLeave={(e) => { if (!isExpanded) e.currentTarget.style.background = "transparent"; }}
      >
        <td style={{ width: 48, textAlign: "center", fontWeight: 700, color: rankColor, fontSize: rank <= 3 ? 18 : 14 }}>
          {medal}
        </td>
        <td style={{ color: theme.textBright, fontWeight: 500 }}>{player.player_name}</td>
        <td style={{ textAlign: "right", fontFamily: font, color: theme.goldBright, fontWeight: 700, fontSize: 16 }}>
          {player.total_points?.toLocaleString()}
        </td>
        <td style={{ textAlign: "right", color: theme.textMuted }}>
          {player.chest_count?.toLocaleString()}
        </td>
      </tr>
      {isExpanded && breakdown && (
        <tr>
          <td colSpan={4} style={{ padding: "0 12px 16px 60px", background: theme.surfaceHover }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, paddingTop: 8 }}>
              {breakdown.length === 0 ? (
                <span style={{ color: theme.textMuted, fontSize: 13 }}>No breakdown data</span>
              ) : breakdown.map((b, i) => (
                <div key={i} style={{
                  background: theme.bg, border: `1px solid ${theme.border}`,
                  borderRadius: 6, padding: "8px 14px", fontSize: 13,
                }}>
                  <span style={{ color: theme.text }}>{b.chest_type}</span>
                  <span style={{ color: theme.goldDim, marginLeft: 8, fontWeight: 600 }}>×{b.count}</span>
                  <span style={{ color: theme.textMuted, marginLeft: 6, fontSize: 11 }}>{b.points}pts</span>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main Dashboard ──────────────────────────────────────────────────────────
function Dashboard() {
  const [activeTab, setActiveTab] = useState("leaderboard");
  const [range, setRange] = useState("7d");
  const [players, setPlayers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [breakdown, setBreakdown] = useState(null);
  const [sortBy, setSortBy] = useState("points"); // "points" or "chests"

  const hours = TIME_RANGES.find((r) => r.key === range)?.hours || 168;

  const fetchLeaderboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExpandedPlayer(null);
    setBreakdown(null);
    try {
      const res = await fetch(`${API_BASE}/leaderboard?hours=${hours}`);
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      setPlayers(data.players || []);
    } catch (e) {
      setError(e.message);
      setPlayers([]);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => { fetchLeaderboard(); }, [fetchLeaderboard]);

  const handlePlayerSelect = async (name) => {
    if (expandedPlayer === name) {
      setExpandedPlayer(null);
      setBreakdown(null);
      return;
    }
    setExpandedPlayer(name);
    setBreakdown(null);
    try {
      const res = await fetch(`${API_BASE}/player/${encodeURIComponent(name)}?hours=${hours}`);
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      setBreakdown(data.breakdown || []);
    } catch {
      setBreakdown([]);
    }
  };

  const sorted = [...players].sort((a, b) =>
    sortBy === "points"
      ? (b.total_points || 0) - (a.total_points || 0)
      : (b.chest_count || 0) - (a.chest_count || 0)
  );

  const totalPoints = players.reduce((s, p) => s + (p.total_points || 0), 0);
  const totalChests = players.reduce((s, p) => s + (p.chest_count || 0), 0);

  return (
    <div style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse at 50% 0%, #141018 0%, ${theme.bg} 60%)`,
      fontFamily: fontBody, color: theme.text,
    }}>
      {/* Header */}
      <div style={{
        borderBottom: `1px solid ${theme.border}`, padding: "20px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 28 }}>⚔️</span>
          <div>
            <h1 style={{ fontFamily: font, fontSize: 20, color: theme.gold, margin: 0, letterSpacing: 2, textTransform: "uppercase" }}>
              Chest Counter
            </h1>
            <p style={{ color: theme.textMuted, fontSize: 12, margin: 0 }}>FOR Clan Dashboard</p>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={() => setActiveTab("leaderboard")}
            style={{
              background: activeTab === "leaderboard" ? theme.gold : "transparent",
              color: activeTab === "leaderboard" ? theme.bg : theme.textMuted,
              border: `1px solid ${activeTab === "leaderboard" ? theme.gold : theme.border}`,
              padding: "8px 16px", borderRadius: 6, fontSize: 12,
              cursor: "pointer", fontFamily: fontBody, fontWeight: 600,
            }}
          >Leaderboard</button>
          <button
            onClick={() => setActiveTab("admin")}
            style={{
              background: activeTab === "admin" ? theme.gold : "transparent",
              color: activeTab === "admin" ? theme.bg : theme.textMuted,
              border: `1px solid ${activeTab === "admin" ? theme.gold : theme.border}`,
              padding: "8px 16px", borderRadius: 6, fontSize: 12,
              cursor: "pointer", fontFamily: fontBody, fontWeight: 600,
            }}
          >Admin</button>
          {activeTab === "leaderboard" && (
            <button
              onClick={fetchLeaderboard}
              style={{
                background: "transparent", border: `1px solid ${theme.border}`,
                color: theme.textMuted, padding: "8px 16px", borderRadius: 6, fontSize: 12,
                cursor: "pointer", fontFamily: fontBody, transition: "border-color 0.2s, color 0.2s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = theme.gold; e.currentTarget.style.color = theme.gold; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = theme.border; e.currentTarget.style.color = theme.textMuted; }}
            >↻ Refresh</button>
          )}
        </div>
      </div>

      <div style={{ maxWidth: activeTab === "admin" ? 1000 : 800, margin: "0 auto", padding: "24px 16px" }}>
        {activeTab === "admin" ? (
          <AdminPanel theme={theme} API_BASE={API_BASE} />
        ) : (
          <>
        {/* Time Range Tabs */}
        <div style={{ display: "flex", gap: 6, marginBottom: 24, flexWrap: "wrap" }}>
          {TIME_RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              style={{
                padding: "8px 18px", borderRadius: 20, fontSize: 13, fontWeight: 600,
                border: range === r.key ? `1px solid ${theme.gold}` : `1px solid ${theme.border}`,
                background: range === r.key ? `${theme.gold}18` : "transparent",
                color: range === r.key ? theme.goldBright : theme.textMuted,
                cursor: "pointer", fontFamily: fontBody, transition: "all 0.2s",
              }}
            >{r.label}</button>
          ))}
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
          <StatCard icon="👥" label="Players" value={players.length} />
          <StatCard icon="📦" label="Chests" value={totalChests} />
          <StatCard icon="⭐" label="Points" value={totalPoints} />
        </div>

        {/* Error */}
        {error && (
          <div style={{
            background: `${theme.red}15`, border: `1px solid ${theme.red}40`,
            borderRadius: 8, padding: "14px 18px", marginBottom: 20, fontSize: 13, color: theme.red,
          }}>
            Failed to load data: {error}
          </div>
        )}

        {/* Loading */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: theme.textMuted }}>
            <div style={{ fontSize: 32, marginBottom: 12, animation: "pulse 1.5s ease infinite" }}>⚔️</div>
            Loading...
          </div>
        ) : players.length === 0 && !error ? (
          <div style={{ textAlign: "center", padding: 60, color: theme.textMuted }}>
            No chest data for this time range.
          </div>
        ) : (
          /* Leaderboard Table */
          <div style={{
            background: theme.surface, border: `1px solid ${theme.border}`,
            borderRadius: 10, overflow: "hidden",
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <th style={{ padding: "14px 8px", textAlign: "center", color: theme.textMuted, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>#</th>
                  <th style={{ padding: "14px 12px", textAlign: "left", color: theme.textMuted, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>Player</th>
                  <th
                    onClick={() => setSortBy("points")}
                    style={{
                      padding: "14px 12px", textAlign: "right", fontSize: 11, textTransform: "uppercase",
                      letterSpacing: 1, cursor: "pointer",
                      color: sortBy === "points" ? theme.gold : theme.textMuted,
                    }}
                  >Points {sortBy === "points" ? "▼" : ""}</th>
                  <th
                    onClick={() => setSortBy("chests")}
                    style={{
                      padding: "14px 12px", textAlign: "right", fontSize: 11, textTransform: "uppercase",
                      letterSpacing: 1, cursor: "pointer",
                      color: sortBy === "chests" ? theme.gold : theme.textMuted,
                    }}
                  >Chests {sortBy === "chests" ? "▼" : ""}</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((p, i) => (
                  <PlayerRow
                    key={p.player_name}
                    rank={i + 1}
                    player={p}
                    onSelect={handlePlayerSelect}
                    isExpanded={expandedPlayer === p.player_name}
                    breakdown={expandedPlayer === p.player_name ? breakdown : null}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        </>
        )}
      </div>

      {/* Global Styles */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Fira+Sans:wght@400;500;600&display=swap');

        * { margin: 0; padding: 0; box-sizing: border-box; }

        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20%, 60% { transform: translateX(-6px); }
          40%, 80% { transform: translateX(6px); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }

        table td, table th {
          padding: 12px;
        }
        tbody tr {
          border-bottom: 1px solid ${theme.border};
        }
        tbody tr:last-child {
          border-bottom: none;
        }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${theme.bg}; }
        ::-webkit-scrollbar-thumb { background: ${theme.border}; border-radius: 3px; }
      `}</style>
    </div>
  );
}

// ── App Root ────────────────────────────────────────────────────────────────
export default function App() {
  const [authed, setAuthed] = useState(() => sessionStorage.getItem("tb-dash-auth") === "1");

  if (!authed) return <GateScreen onUnlock={() => setAuthed(true)} />;
  return <Dashboard />;
}
