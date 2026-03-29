import { useState, useEffect, useCallback } from "react";
import { AdminPanel } from "./AdminSimple";
import { PieChart, Pie, Cell, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

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

// ── Chart Colors ─────────────────────────────────────────────────────────────
const CHART_COLORS = ["#c9a227", "#4ade80", "#60a5fa", "#f472b6", "#a78bfa", "#fb923c", "#f87171", "#2dd4bf"];

// ── Stat Card with Trend ─────────────────────────────────────────────────────
function StatCard({ label, value, icon, delta, deltaPct }) {
  const hasDelta = delta !== undefined && delta !== null;
  const isPositive = delta > 0;
  const isNegative = delta < 0;
  const trendColor = isPositive ? theme.green : isNegative ? theme.red : theme.textMuted;
  const trendArrow = isPositive ? "↑" : isNegative ? "↓" : "→";

  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "18px 22px", flex: "1 1 140px", minWidth: 140,
    }}>
      <div style={{ fontSize: 12, color: theme.textMuted, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
        {icon} {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontSize: 28, fontFamily: font, color: theme.goldBright, fontWeight: 700 }}>
          {value != null ? value.toLocaleString() : "—"}
        </div>
        {hasDelta && (
          <div style={{ fontSize: 12, color: trendColor, fontWeight: 600 }}>
            {trendArrow} {Math.abs(delta).toLocaleString()}
            {deltaPct != null && <span style={{ marginLeft: 4 }}>({deltaPct > 0 ? "+" : ""}{deltaPct}%)</span>}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Scan Health Indicator ────────────────────────────────────────────────────
function ScanHealthIndicator({ health }) {
  if (!health) return null;

  const statusColors = {
    healthy: theme.green,
    running: "#60a5fa",
    warning: "#fb923c",
    stale: theme.goldDim,
    error: theme.red,
    unknown: theme.textMuted,
  };

  const statusIcons = {
    healthy: "●",
    running: "◉",
    warning: "◉",
    stale: "○",
    error: "●",
    unknown: "○",
  };

  const color = statusColors[health.status] || theme.textMuted;
  const icon = statusIcons[health.status] || "○";

  const lastScan = health.lastRun?.completedAt
    ? new Date(health.lastRun.completedAt)
    : null;

  const timeAgo = lastScan
    ? formatTimeAgo(lastScan)
    : "Never";

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "6px 12px", borderRadius: 6,
      background: `${color}15`, border: `1px solid ${color}30`,
      fontSize: 12, color: color,
    }}>
      <span style={{ fontSize: 10 }}>{icon}</span>
      <span>Last scan: {timeAgo}</span>
      {health.lastRun?.chestsFound != null && (
        <span style={{ color: theme.textMuted }}>({health.lastRun.chestsFound} chests)</span>
      )}
    </div>
  );
}

function formatTimeAgo(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ── Category Donut Chart ─────────────────────────────────────────────────────
function CategoryDonutChart({ data }) {
  if (!data || data.length === 0) return null;

  const total = data.reduce((sum, d) => sum + d.points, 0);

  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "18px 22px", marginBottom: 24,
    }}>
      <h3 style={{ fontSize: 14, color: theme.textMuted, marginBottom: 16, textTransform: "uppercase", letterSpacing: 1 }}>
        Chest Sources
      </h3>
      <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
        <div style={{ width: 160, height: 160 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={data}
                dataKey="points"
                nameKey="category"
                cx="50%"
                cy="50%"
                innerRadius={45}
                outerRadius={70}
                paddingAngle={2}
              >
                {data.map((entry, index) => (
                  <Cell key={entry.category} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 6 }}
                labelStyle={{ color: theme.textBright }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          {data.slice(0, 6).map((cat, i) => (
            <div key={cat.category} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: CHART_COLORS[i % CHART_COLORS.length] }} />
              <span style={{ flex: 1, color: theme.text, fontSize: 13 }}>{cat.category}</span>
              <span style={{ color: theme.goldDim, fontSize: 12, fontWeight: 600 }}>{cat.count}</span>
              <span style={{ color: theme.textMuted, fontSize: 11, width: 50, textAlign: "right" }}>
                {total > 0 ? Math.round((cat.points / total) * 100) : 0}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Daily Trend Chart ────────────────────────────────────────────────────────
function DailyTrendChart({ data }) {
  if (!data || data.length === 0) return null;

  // Format dates for display
  const formatted = data.map((d) => ({
    ...d,
    label: new Date(d.period).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
  }));

  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "18px 22px", marginBottom: 24,
    }}>
      <h3 style={{ fontSize: 14, color: theme.textMuted, marginBottom: 16, textTransform: "uppercase", letterSpacing: 1 }}>
        Daily Activity
      </h3>
      <div style={{ width: "100%", height: 180 }}>
        <ResponsiveContainer>
          <LineChart data={formatted} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: theme.textMuted }} axisLine={{ stroke: theme.border }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: theme.textMuted }} axisLine={false} tickLine={false} width={40} />
            <Tooltip
              contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: theme.textBright }}
            />
            <Line type="monotone" dataKey="chests" stroke={theme.gold} strokeWidth={2} dot={{ fill: theme.gold, r: 3 }} name="Chests" />
            <Line type="monotone" dataKey="players" stroke={theme.green} strokeWidth={2} dot={{ fill: theme.green, r: 3 }} name="Players" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Status Badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const statusConfig = {
    completed: { label: "Done", bg: `${theme.green}25`, color: theme.green, icon: "✓" },
    on_track: { label: "On Track", bg: `${theme.green}15`, color: theme.green, icon: "●" },
    at_risk: { label: "At Risk", bg: "#fb923c25", color: "#fb923c", icon: "!" },
    behind: { label: "Behind", bg: `${theme.red}20`, color: theme.red, icon: "↓" },
    inactive: { label: "Inactive", bg: `${theme.textMuted}15`, color: theme.textMuted, icon: "○" },
  };

  const config = statusConfig[status] || statusConfig.inactive;

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
      background: config.bg, color: config.color, textTransform: "uppercase", letterSpacing: 0.5,
    }}>
      <span style={{ fontSize: 8 }}>{config.icon}</span> {config.label}
    </span>
  );
}

// ── Progress Bar ─────────────────────────────────────────────────────────────
function ProgressBar({ value, max, status }) {
  const pct = Math.min((value / max) * 100, 100);
  const barColor = status === "completed" ? theme.green
    : status === "on_track" ? theme.green
    : status === "at_risk" ? "#fb923c"
    : status === "behind" ? theme.red
    : theme.textMuted;

  return (
    <div style={{
      width: "100%", height: 6, background: theme.border, borderRadius: 3, overflow: "hidden",
    }}>
      <div style={{
        width: `${pct}%`, height: "100%", background: barColor, borderRadius: 3,
        transition: "width 0.3s ease",
      }} />
    </div>
  );
}

// ── At-Risk Callout ──────────────────────────────────────────────────────────
function AtRiskCallout({ players, target, targetType }) {
  if (!players || players.length === 0) return null;

  return (
    <div style={{
      background: `${theme.red}10`, border: `1px solid ${theme.red}30`,
      borderRadius: 10, padding: "16px 20px", marginBottom: 24,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>⚠️</span>
        <h3 style={{ fontSize: 14, color: theme.red, margin: 0, fontWeight: 600 }}>
          Members At Risk ({players.length})
        </h3>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {players.slice(0, 8).map((p) => (
          <div key={p.player_name} style={{
            background: theme.surface, border: `1px solid ${theme.border}`,
            borderRadius: 6, padding: "8px 12px", fontSize: 12,
          }}>
            <span style={{ color: theme.textBright, fontWeight: 500 }}>{p.player_name}</span>
            <span style={{ color: theme.textMuted, marginLeft: 8 }}>
              {p[targetType === "points" ? "total_points" : "chest_count"]}/{target}
            </span>
            <span style={{ color: theme.red, marginLeft: 4, fontSize: 10 }}>
              ({p.progress}%)
            </span>
          </div>
        ))}
        {players.length > 8 && (
          <div style={{
            background: theme.surface, border: `1px solid ${theme.border}`,
            borderRadius: 6, padding: "8px 12px", fontSize: 12, color: theme.textMuted,
          }}>
            +{players.length - 8} more
          </div>
        )}
      </div>
    </div>
  );
}

// ── Day of Week Chart ────────────────────────────────────────────────────────
function DayOfWeekChart({ data }) {
  if (!data || data.length === 0) return null;

  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const formatted = data.map((d) => ({
    ...d,
    label: dayLabels[d.day_of_week] || d.day_of_week,
  }));

  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "18px 22px",
    }}>
      <h3 style={{ fontSize: 14, color: theme.textMuted, marginBottom: 16, textTransform: "uppercase", letterSpacing: 1 }}>
        Activity by Day
      </h3>
      <div style={{ width: "100%", height: 160 }}>
        <ResponsiveContainer>
          <BarChart data={formatted} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: theme.textMuted }} axisLine={{ stroke: theme.border }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: theme.textMuted }} axisLine={false} tickLine={false} width={40} />
            <Tooltip
              contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: theme.textBright }}
            />
            <Bar dataKey="chests" fill={theme.gold} radius={[4, 4, 0, 0]} name="Chests" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Chest Archive Table ──────────────────────────────────────────────────────
function ChestArchive({ API_BASE }) {
  const [chests, setChests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, total_pages: 1 });
  const [filters, setFilters] = useState({ player: "", chest_type: "", category: "", hours: "" });
  const [categories, setCategories] = useState([]);

  const fetchChests = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, limit: 50 });
      if (filters.player) params.set("player", filters.player);
      if (filters.chest_type) params.set("chest_type", filters.chest_type);
      if (filters.category) params.set("category", filters.category);
      if (filters.hours) params.set("hours", filters.hours);

      const res = await fetch(`${API_BASE}/chests?${params}`);
      if (res.ok) {
        const data = await res.json();
        setChests(data.chests || []);
        setPagination(data.pagination || { total: 0, total_pages: 1 });
        setCategories(data.filters?.categories || []);
      }
    } catch (e) {
      console.error("Failed to fetch chests:", e);
    } finally {
      setLoading(false);
    }
  }, [API_BASE, page, filters]);

  useEffect(() => { fetchChests(); }, [fetchChests]);

  const handleExport = () => {
    const params = new URLSearchParams({ export: "csv" });
    if (filters.player) params.set("player", filters.player);
    if (filters.chest_type) params.set("chest_type", filters.chest_type);
    if (filters.category) params.set("category", filters.category);
    if (filters.hours) params.set("hours", filters.hours);
    window.open(`${API_BASE}/chests?${params}`, "_blank");
  };

  const updateFilter = (key, value) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  };

  return (
    <div>
      {/* Filters */}
      <div style={{
        display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 20,
        background: theme.surface, border: `1px solid ${theme.border}`,
        borderRadius: 10, padding: 16,
      }}>
        <input
          type="text"
          placeholder="Search player..."
          value={filters.player}
          onChange={(e) => updateFilter("player", e.target.value)}
          style={{
            flex: "1 1 150px", padding: "8px 12px", borderRadius: 6,
            border: `1px solid ${theme.border}`, background: theme.bg,
            color: theme.textBright, fontSize: 13, outline: "none",
          }}
        />
        <input
          type="text"
          placeholder="Chest type..."
          value={filters.chest_type}
          onChange={(e) => updateFilter("chest_type", e.target.value)}
          style={{
            flex: "1 1 150px", padding: "8px 12px", borderRadius: 6,
            border: `1px solid ${theme.border}`, background: theme.bg,
            color: theme.textBright, fontSize: 13, outline: "none",
          }}
        />
        <select
          value={filters.category}
          onChange={(e) => updateFilter("category", e.target.value)}
          style={{
            flex: "0 1 140px", padding: "8px 12px", borderRadius: 6,
            border: `1px solid ${theme.border}`, background: theme.bg,
            color: theme.textBright, fontSize: 13, outline: "none", cursor: "pointer",
          }}
        >
          <option value="">All Categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={filters.hours}
          onChange={(e) => updateFilter("hours", e.target.value)}
          style={{
            flex: "0 1 120px", padding: "8px 12px", borderRadius: 6,
            border: `1px solid ${theme.border}`, background: theme.bg,
            color: theme.textBright, fontSize: 13, outline: "none", cursor: "pointer",
          }}
        >
          <option value="">All Time</option>
          <option value="24">Last 24h</option>
          <option value="168">Last Week</option>
          <option value="720">Last Month</option>
        </select>
        <button
          onClick={handleExport}
          style={{
            padding: "8px 16px", borderRadius: 6, fontSize: 12, fontWeight: 600,
            background: theme.gold, color: theme.bg, border: "none",
            cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
          }}
        >
          📥 Export CSV
        </button>
      </div>

      {/* Table */}
      <div style={{
        background: theme.surface, border: `1px solid ${theme.border}`,
        borderRadius: 10, overflow: "hidden",
      }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: theme.textMuted }}>Loading...</div>
        ) : chests.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: theme.textMuted }}>No chests found</div>
        ) : (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <th style={{ padding: "12px", textAlign: "left", color: theme.textMuted, fontSize: 11, textTransform: "uppercase" }}>Player</th>
                  <th style={{ padding: "12px", textAlign: "left", color: theme.textMuted, fontSize: 11, textTransform: "uppercase" }}>Chest Type</th>
                  <th style={{ padding: "12px", textAlign: "left", color: theme.textMuted, fontSize: 11, textTransform: "uppercase" }}>Category</th>
                  <th style={{ padding: "12px", textAlign: "right", color: theme.textMuted, fontSize: 11, textTransform: "uppercase" }}>Points</th>
                  <th style={{ padding: "12px", textAlign: "right", color: theme.textMuted, fontSize: 11, textTransform: "uppercase" }}>Scanned</th>
                </tr>
              </thead>
              <tbody>
                {chests.map((c) => (
                  <tr key={c.id} style={{ borderBottom: `1px solid ${theme.border}` }}>
                    <td style={{ padding: "10px 12px", color: theme.textBright }}>{c.player_name}</td>
                    <td style={{ padding: "10px 12px", color: theme.text }}>{c.chest_type}</td>
                    <td style={{ padding: "10px 12px", color: theme.textMuted }}>{c.category || "—"}</td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: theme.goldDim, fontWeight: 600 }}>{c.points}</td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: theme.textMuted, fontSize: 12 }}>
                      {c.scanned_at ? new Date(c.scanned_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "12px 16px", borderTop: `1px solid ${theme.border}`,
            }}>
              <span style={{ color: theme.textMuted, fontSize: 12 }}>
                Showing {chests.length} of {pagination.total} chests
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                  style={{
                    padding: "6px 12px", borderRadius: 4, fontSize: 12,
                    background: page === 1 ? theme.border : theme.surfaceHover,
                    color: page === 1 ? theme.textMuted : theme.textBright,
                    border: "none", cursor: page === 1 ? "default" : "pointer",
                  }}
                >← Prev</button>
                <span style={{ color: theme.textMuted, fontSize: 12, padding: "6px 8px" }}>
                  Page {page} of {pagination.total_pages}
                </span>
                <button
                  disabled={page >= pagination.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                  style={{
                    padding: "6px 12px", borderRadius: 4, fontSize: 12,
                    background: page >= pagination.total_pages ? theme.border : theme.surfaceHover,
                    color: page >= pagination.total_pages ? theme.textMuted : theme.textBright,
                    border: "none", cursor: page >= pagination.total_pages ? "default" : "pointer",
                  }}
                >Next →</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Player Row ──────────────────────────────────────────────────────────────
function PlayerRow({ rank, player, onSelect, isExpanded, breakdown, targetData }) {
  const rankColor = rank === 1 ? theme.rank1 : rank === 2 ? theme.rank2 : rank === 3 ? theme.rank3 : theme.textMuted;
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `${rank}`;

  // Find target progress for this player
  const playerTarget = targetData?.players?.find((p) => p.player_name === player.player_name);
  const hasTarget = targetData && playerTarget;
  const target = targetData?.settings?.target_type === "points"
    ? targetData?.settings?.weekly_point_target
    : targetData?.settings?.weekly_chest_target;

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
        <td style={{ color: theme.textBright, fontWeight: 500 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {player.player_name}
            {hasTarget && <StatusBadge status={playerTarget.status} />}
          </div>
          {hasTarget && (
            <div style={{ marginTop: 6, width: 120 }}>
              <ProgressBar
                value={targetData.settings.target_type === "points" ? playerTarget.total_points : playerTarget.chest_count}
                max={target}
                status={playerTarget.status}
              />
            </div>
          )}
        </td>
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
  const [sources, setSources] = useState(null);
  const [trends, setTrends] = useState(null);
  const [health, setHealth] = useState(null);
  const [targetData, setTargetData] = useState(null);
  const [dayOfWeek, setDayOfWeek] = useState(null);

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

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/sources?hours=${hours}`);
      if (res.ok) {
        const data = await res.json();
        setSources(data.categories || []);
      }
    } catch {
      setSources(null);
    }
  }, [hours]);

  const fetchTrends = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/trends?hours=${hours}`);
      if (res.ok) {
        const data = await res.json();
        setTrends(data);
      }
    } catch {
      setTrends(null);
    }
  }, [hours]);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch {
      setHealth(null);
    }
  }, []);

  const fetchTargets = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/targets`);
      if (res.ok) {
        const data = await res.json();
        setTargetData(data);
      }
    } catch {
      setTargetData(null);
    }
  }, []);

  const fetchDayOfWeek = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/trends?hours=${hours}&group=dow`);
      if (res.ok) {
        const data = await res.json();
        setDayOfWeek(data.data || []);
      }
    } catch {
      setDayOfWeek(null);
    }
  }, [hours]);

  useEffect(() => { fetchLeaderboard(); fetchSources(); fetchTrends(); fetchDayOfWeek(); }, [fetchLeaderboard, fetchSources, fetchTrends, fetchDayOfWeek]);
  useEffect(() => { fetchHealth(); fetchTargets(); }, [fetchHealth, fetchTargets]);

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
          <ScanHealthIndicator health={health} />
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
            onClick={() => setActiveTab("archive")}
            style={{
              background: activeTab === "archive" ? theme.gold : "transparent",
              color: activeTab === "archive" ? theme.bg : theme.textMuted,
              border: `1px solid ${activeTab === "archive" ? theme.gold : theme.border}`,
              padding: "8px 16px", borderRadius: 6, fontSize: 12,
              cursor: "pointer", fontFamily: fontBody, fontWeight: 600,
            }}
          >Archive</button>
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

      <div style={{ maxWidth: activeTab === "admin" ? 1000 : 900, margin: "0 auto", padding: "24px 16px" }}>
        {activeTab === "admin" ? (
          <AdminPanel theme={theme} API_BASE={API_BASE} />
        ) : activeTab === "archive" ? (
          <ChestArchive API_BASE={API_BASE} />
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

        {/* Stats with Trend Arrows */}
        <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
          <StatCard
            icon="👥"
            label="Players"
            value={players.length}
            delta={trends?.comparison?.deltas?.players}
          />
          <StatCard
            icon="📦"
            label="Chests"
            value={totalChests}
            delta={trends?.comparison?.deltas?.chests}
            deltaPct={trends?.comparison?.deltas?.chests_pct}
          />
          <StatCard
            icon="⭐"
            label="Points"
            value={totalPoints}
            delta={trends?.comparison?.deltas?.points}
            deltaPct={trends?.comparison?.deltas?.points_pct}
          />
        </div>

        {/* Charts Section */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, marginBottom: 24 }}>
          <CategoryDonutChart data={sources} />
          <DailyTrendChart data={trends?.data} />
          <DayOfWeekChart data={dayOfWeek} />
        </div>

        {/* At-Risk Members Callout */}
        <AtRiskCallout
          players={targetData?.at_risk}
          target={targetData?.settings?.target_type === "points"
            ? targetData?.settings?.weekly_point_target
            : targetData?.settings?.weekly_chest_target}
          targetType={targetData?.settings?.target_type || "chests"}
        />

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
                    targetData={targetData}
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
