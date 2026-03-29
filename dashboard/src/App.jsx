import { useState, useEffect, useCallback, useMemo } from "react";
import { AdminPanel } from "./AdminSimple.jsx";
import { MembersPanel } from "./MembersPanel.jsx";
import { RosterPanel } from "./RosterPanel.jsx";

// ── Config ──────────────────────────────────────────────────────────────────
const ACCESS_CODE = "FOR2026";
const API_BASE = "/api";

// ── Time Ranges ─────────────────────────────────────────────────────────────
const TIME_RANGES = [
  { key: "1h", label: "1h", hours: 1 },
  { key: "8h", label: "8h", hours: 8 },
  { key: "24h", label: "24h", hours: 24 },
  { key: "7d", label: "7d", hours: 168 },
  { key: "30d", label: "30d", hours: 720 },
];

// ── Theme ───────────────────────────────────────────────────────────────────
const t = {
  bg: "#f8f7f4",
  surface: "#ffffff",
  surfaceAlt: "#f1f0ed",
  border: "#e4e2dd",
  borderLight: "#eceae5",

  primary: "#6c3fc5",
  primaryLight: "#8b66d6",
  primaryFaint: "#f0eaf9",

  text: "#1a1a1a",
  textSecondary: "#6b6966",
  textTertiary: "#9e9a95",

  rank1: "#c9a227",
  rank2: "#8e8e93",
  rank3: "#b07340",

  catCrypt: "#6c3fc5",
  catEvent: "#d4537e",
  catCitadel: "#1d9e75",
  catHeroic: "#d85a30",
  catClan: "#3266ad",
};

const font = `'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif`;

// ── Category Definitions ────────────────────────────────────────────────────
const CATEGORIES = [
  { key: "cr", label: "Crypts", color: t.catCrypt, hasAvg: true, avgKey: "crAvg", avgLabel: "Crypt avg lvl" },
  { key: "ev", label: "Events", color: t.catEvent, hasAvg: false },
  { key: "ci", label: "Citadels", color: t.catCitadel, hasAvg: true, avgKey: "ciAvg", avgLabel: "Citadel avg lvl" },
  { key: "he", label: "Heroic", color: t.catHeroic, hasAvg: true, avgKey: "heAvg", avgLabel: "Heroic avg lvl" },
  { key: "cl", label: "Clan", color: t.catClan, hasAvg: false },
];

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
      background: t.bg, fontFamily: font,
    }}>
      <form onSubmit={handleSubmit} style={{
        background: t.surface, border: `1px solid ${t.border}`,
        borderRadius: 16, padding: "48px 40px", width: 380, textAlign: "center",
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
        animation: shake ? "shake 0.4s ease" : "fadeIn 0.5s ease",
      }}>
        <div style={{ fontSize: 28, marginBottom: 8 }}>⚔️</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, color: t.text, marginBottom: 6 }}>
          FOR Chest Tracker
        </h2>
        <p style={{ fontSize: 13, color: t.textTertiary, marginBottom: 28 }}>
          Enter your clan access code
        </p>
        <input
          type="password"
          value={code}
          onChange={(e) => { setCode(e.target.value); setError(false); }}
          placeholder="Access code"
          autoFocus
          style={{
            width: "100%", padding: "12px 16px", fontSize: 15,
            border: `1px solid ${error ? "#e24b4a" : t.border}`,
            borderRadius: 10, outline: "none", background: t.surfaceAlt,
            fontFamily: font, color: t.text, marginBottom: 16,
            transition: "border-color 0.2s",
          }}
        />
        <button type="submit" style={{
          width: "100%", padding: "12px 0", fontSize: 14, fontWeight: 600,
          background: t.primary, color: "#fff", border: "none", borderRadius: 10,
          cursor: "pointer", fontFamily: font, transition: "background 0.2s",
        }}>
          Enter
        </button>
        {error && (
          <p style={{ color: "#e24b4a", fontSize: 13, marginTop: 12 }}>
            Invalid access code
          </p>
        )}
      </form>
    </div>
  );
}

// ── KPI Card ────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub }) {
  return (
    <div style={{
      background: t.surfaceAlt, borderRadius: 12, padding: "14px 16px",
      minWidth: 0,
    }}>
      <div style={{ fontSize: 11, color: t.textTertiary, marginBottom: 4, fontWeight: 500 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 600, color: t.text, lineHeight: 1.2 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: t.textTertiary, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

// ── Category Card ───────────────────────────────────────────────────────────
function CategoryCard({ label, count, avgLevel }) {
  return (
    <div style={{
      background: t.surface, border: `1px solid ${t.borderLight}`,
      borderRadius: 14, padding: "14px 16px",
    }}>
      <div style={{ fontSize: 12, color: t.textSecondary, marginBottom: 6, fontWeight: 500 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color: t.text }}>{count}</div>
      {avgLevel !== undefined && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 6 }}>
          <span style={{ fontSize: 11, color: t.textTertiary }}>avg lvl</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{avgLevel}</span>
        </div>
      )}
    </div>
  );
}

// ── Toggle Pill ─────────────────────────────────────────────────────────────
function TogglePill({ label, checked, color, onChange }) {
  return (
    <label style={{
      display: "flex", alignItems: "center", gap: 6,
      fontSize: 12, color: checked ? t.text : t.textTertiary,
      cursor: "pointer", padding: "4px 12px",
      borderRadius: 8, border: `1px solid ${checked ? color : t.borderLight}`,
      background: checked ? `${color}08` : "transparent",
      userSelect: "none", transition: "all 0.15s",
      fontWeight: 500,
    }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        style={{ width: 13, height: 13, margin: 0, accentColor: color }}
      />
      {label}
    </label>
  );
}

// ── Sortable Header Cell ────────────────────────────────────────────────────
function SortHeader({ label, sortKey, currentSort, currentDir, onSort, align = "right", color, rotated = true }) {
  const isActive = currentSort === sortKey;
  const arrow = isActive ? (currentDir === -1 ? " ▾" : " ▴") : "";

  return (
    <th
      onClick={() => onSort(sortKey)}
      style={{
        textAlign: align,
        padding: rotated ? "0 4px 10px" : "10px 4px",
        fontWeight: 500, fontSize: 11,
        color: color || (isActive ? t.primary : t.textTertiary),
        cursor: "pointer", userSelect: "none",
        verticalAlign: "bottom",
        ...(rotated ? { height: 62, whiteSpace: "nowrap", position: "relative" } : {}),
      }}
    >
      {rotated ? (
        <span style={{
          position: "absolute", bottom: 10, left: "50%",
          transformOrigin: "bottom left", transform: "rotate(-50deg)",
          display: "block",
        }}>
          {label}{arrow}
        </span>
      ) : (
        <>{label}{arrow}</>
      )}
    </th>
  );
}

// ── Dashboard ───────────────────────────────────────────────────────────────
function Dashboard() {
  const [range, setRange] = useState("24h");
  const [players, setPlayers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState("pts");
  const [sortDir, setSortDir] = useState(-1);

  // Avg level toggles — crypt on by default
  const [showCryptAvg, setShowCryptAvg] = useState(true);
  const [showCitadelAvg, setShowCitadelAvg] = useState(false);
  const [showHeroicAvg, setShowHeroicAvg] = useState(false);

  // Player details modal
  const [selectedPlayer, setSelectedPlayer] = useState(null);

  const hours = TIME_RANGES.find((r) => r.key === range)?.hours || 24;

  const fetchLeaderboard = useCallback(async () => {
    setLoading(true);
    setError(null);
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

  const handleSort = (key) => {
    if (sortBy === key) setSortDir((d) => d * -1);
    else { setSortBy(key); setSortDir(-1); }
  };

  const sorted = useMemo(() => {
    const s = [...players].sort((a, b) => {
      const va = a[sortBy], vb = b[sortBy];
      if (typeof va === "string") return sortDir * va.localeCompare(vb);
      return sortDir * ((va ?? 0) - (vb ?? 0));
    });
    return s.map((p, i) => ({ ...p, rank: i + 1 }));
  }, [players, sortBy, sortDir]);

  // Aggregate stats
  const totalChests = players.reduce((s, p) => s + (p.cr || 0) + (p.ev || 0) + (p.ci || 0) + (p.he || 0) + (p.cl || 0), 0);
  const totalPts = players.reduce((s, p) => s + (p.pts || 0), 0);
  const activePlayers = players.length;
  const avgPerPlayer = activePlayers ? (totalChests / activePlayers).toFixed(1) : 0;
  const topPlayer = sorted[0];

  // Category totals
  const catTotals = {
    cr: players.reduce((s, p) => s + (p.cr || 0), 0),
    ev: players.reduce((s, p) => s + (p.ev || 0), 0),
    ci: players.reduce((s, p) => s + (p.ci || 0), 0),
    he: players.reduce((s, p) => s + (p.he || 0), 0),
    cl: players.reduce((s, p) => s + (p.cl || 0), 0),
  };

  // Clan-wide avg levels
  const clanCryptAvg = activePlayers ? (players.reduce((s, p) => s + (p.crAvg || 0), 0) / activePlayers).toFixed(1) : "—";
  const clanCitadelAvg = activePlayers ? (players.reduce((s, p) => s + (p.ciAvg || 0), 0) / activePlayers).toFixed(1) : "—";

  const rankColors = { 1: t.rank1, 2: t.rank2, 3: t.rank3 };

  // Players at risk: bottom 20% by points, or players with 0 chests in selected timeframe
  const playersAtRisk = useMemo(() => {
    if (players.length < 5) return [];
    const threshold = Math.ceil(players.length * 0.2);
    const sortedByPts = [...players].sort((a, b) => (a.pts || 0) - (b.pts || 0));
    return sortedByPts.slice(0, threshold).map(p => ({
      ...p,
      totalChests: (p.cr || 0) + (p.ev || 0) + (p.ci || 0) + (p.he || 0) + (p.cl || 0)
    }));
  }, [players]);

  // Build column definitions dynamically
  const columns = useMemo(() => {
    const cols = [
      { key: "rank", label: "#", align: "left", w: "28px", sortable: false, rotated: false },
      { key: "name", label: "Player", align: "left", w: null, sortable: true, rotated: false },
      { key: "pts", label: "Points", align: "right", w: "52px", sortable: true },
      { key: "cr", label: "Crypts", align: "right", w: "48px", sortable: true },
    ];
    if (showCryptAvg) cols.push({ key: "crAvg", label: "Crypt lvl", align: "right", w: "52px", sortable: true, color: t.catCrypt });
    cols.push({ key: "ev", label: "Events", align: "right", w: "46px", sortable: true });
    cols.push({ key: "ci", label: "Citadels", align: "right", w: "52px", sortable: true });
    if (showCitadelAvg) cols.push({ key: "ciAvg", label: "Citdl lvl", align: "right", w: "52px", sortable: true, color: t.catCitadel });
    cols.push({ key: "he", label: "Heroic", align: "right", w: "46px", sortable: true });
    if (showHeroicAvg) cols.push({ key: "heAvg", label: "Hero lvl", align: "right", w: "52px", sortable: true, color: t.catHeroic });
    cols.push({ key: "cl", label: "Clan", align: "right", w: "38px", sortable: true });
    return cols;
  }, [showCryptAvg, showCitadelAvg, showHeroicAvg]);

  return (
    <div style={{
      minHeight: "100vh", background: t.bg, fontFamily: font, color: t.text,
      padding: "28px 24px 48px",
    }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: t.text, marginBottom: 2 }}>
              ⚔️ FOR Chest Tracker
            </h1>
            <p style={{ fontSize: 13, color: t.textTertiary }}>
              Clan performance dashboard
            </p>
          </div>
          <a
            href="#admin"
            style={{
              fontSize: 12, color: t.textTertiary, textDecoration: "none",
              padding: "6px 12px", borderRadius: 6, border: `1px solid ${t.border}`,
              background: t.surface, marginTop: 4,
            }}
            onMouseEnter={(e) => { e.target.style.borderColor = t.primary; e.target.style.color = t.primary; }}
            onMouseLeave={(e) => { e.target.style.borderColor = t.border; e.target.style.color = t.textTertiary; }}
          >
            Admin
          </a>
        </div>

        {/* KPI Row */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8,
          marginBottom: 20,
        }}>
          <KpiCard label="Total chests" value={totalChests.toLocaleString()} />
          <KpiCard label="Active players" value={activePlayers} />
          <KpiCard label="Avg / player" value={avgPerPlayer} />
          <KpiCard label="Total points" value={totalPts.toLocaleString()} />
          <KpiCard
            label="Top performer"
            value={topPlayer?.name || "—"}
            sub={topPlayer ? `${topPlayer.pts} pts` : undefined}
          />
        </div>

        {/* Category Cards */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8,
          marginBottom: 20,
        }}>
          <CategoryCard label="Crypts" count={catTotals.cr} avgLevel={clanCryptAvg} />
          <CategoryCard label="Events" count={catTotals.ev} />
          <CategoryCard label="Citadels" count={catTotals.ci} avgLevel={clanCitadelAvg} />
          <CategoryCard label="Heroic" count={catTotals.he} />
          <CategoryCard label="Clan" count={catTotals.cl} />
        </div>

        {/* Players at Risk */}
        {playersAtRisk.length > 0 && (
          <div style={{
            background: "#fef2f2", border: "1px solid #fecaca",
            borderRadius: 12, padding: 14, marginBottom: 24,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 14 }}>⚠️</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#b91c1c" }}>
                Players at Risk ({playersAtRisk.length})
              </span>
              <span style={{ fontSize: 11, color: "#dc2626", marginLeft: "auto" }}>
                Bottom 20% by points
              </span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {playersAtRisk.map(p => (
                <button
                  key={p.name}
                  onClick={() => setSelectedPlayer(p.name)}
                  style={{
                    padding: "4px 10px", fontSize: 12,
                    background: "#fff", border: "1px solid #fecaca",
                    borderRadius: 6, cursor: "pointer",
                    color: "#b91c1c", fontWeight: 500,
                  }}
                >
                  {p.name} <span style={{ color: "#ef4444", fontWeight: 400 }}>({p.pts} pts)</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Leaderboard */}
        <div>
          {/* Title + Time Range */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 14,
          }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: t.text }}>
              Leaderboard
            </span>
            <div style={{ display: "flex", gap: 3 }}>
              {TIME_RANGES.map((tr) => (
                <button
                  key={tr.key}
                  onClick={() => setRange(tr.key)}
                  style={{
                    fontSize: 11, fontWeight: 600, padding: "4px 11px",
                    borderRadius: 7, border: "none", cursor: "pointer",
                    fontFamily: font,
                    background: range === tr.key ? t.primary : t.surfaceAlt,
                    color: range === tr.key ? "#fff" : t.textTertiary,
                    transition: "all 0.15s",
                  }}
                >
                  {tr.label}
                </button>
              ))}
            </div>
          </div>

          {/* Avg Level Toggles */}
          <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
            <TogglePill label="Crypt avg lvl" checked={showCryptAvg} color={t.catCrypt} onChange={() => setShowCryptAvg(!showCryptAvg)} />
            <TogglePill label="Citadel avg lvl" checked={showCitadelAvg} color={t.catCitadel} onChange={() => setShowCitadelAvg(!showCitadelAvg)} />
            <TogglePill label="Heroic avg lvl" checked={showHeroicAvg} color={t.catHeroic} onChange={() => setShowHeroicAvg(!showHeroicAvg)} />
          </div>

          {/* Table */}
          {loading ? (
            <div style={{ textAlign: "center", padding: 48, color: t.textTertiary, fontSize: 14 }}>
              Loading…
            </div>
          ) : error ? (
            <div style={{
              textAlign: "center", padding: 32, color: "#e24b4a", fontSize: 14,
              background: "#fef2f2", borderRadius: 12,
            }}>
              {error}
            </div>
          ) : (
            <div style={{
              background: t.surface, border: `1px solid ${t.borderLight}`,
              borderRadius: 14, overflow: "hidden",
            }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${t.borderLight}` }}>
                    {columns.map((col) => (
                      <SortHeader
                        key={col.key}
                        label={col.label}
                        sortKey={col.key}
                        currentSort={sortBy}
                        currentDir={sortDir}
                        onSort={col.sortable ? handleSort : () => {}}
                        align={col.align}
                        color={col.color}
                        rotated={col.rotated !== false}
                      />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((p) => (
                    <tr
                      key={p.name || p.player_name}
                      style={{
                        borderBottom: `1px solid ${t.borderLight}`,
                        transition: "background 0.1s",
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = t.surfaceAlt}
                      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                    >
                      {columns.map((col) => {
                        const val = col.key === "name" ? (p.name || p.player_name) : p[col.key];

                        if (col.key === "rank") {
                          return (
                            <td key={col.key} style={{
                              padding: "11px 4px 11px 14px", fontWeight: 600, fontSize: 12,
                              color: rankColors[val] || t.textTertiary,
                              width: col.w,
                            }}>
                              {val}
                            </td>
                          );
                        }
                        if (col.key === "name") {
                          return (
                            <td key={col.key} style={{
                              padding: "11px 4px", fontWeight: p.rank <= 3 ? 600 : 400,
                              color: t.text, overflow: "hidden",
                              textOverflow: "ellipsis", whiteSpace: "nowrap",
                            }}>
                              <button
                                onClick={() => setSelectedPlayer(val)}
                                style={{
                                  background: "none", border: "none", padding: 0, margin: 0,
                                  font: "inherit", fontWeight: "inherit", color: "inherit",
                                  cursor: "pointer", textDecoration: "none",
                                }}
                                onMouseEnter={(e) => e.target.style.color = t.primary}
                                onMouseLeave={(e) => e.target.style.color = t.text}
                              >
                                {val}
                              </button>
                            </td>
                          );
                        }
                        if (col.key === "pts") {
                          return (
                            <td key={col.key} style={{
                              padding: "11px 4px", textAlign: "right",
                              fontWeight: 600, color: t.text, width: col.w,
                            }}>
                              {val}
                            </td>
                          );
                        }
                        if (col.color) {
                          // Avg level column
                          return (
                            <td key={col.key} style={{
                              padding: "11px 4px", textAlign: "right",
                              fontWeight: 600, fontSize: 12, color: col.color,
                              width: col.w,
                            }}>
                              {typeof val === "number" ? val.toFixed(1) : (val || "—")}
                            </td>
                          );
                        }
                        // Regular category count
                        return (
                          <td key={col.key} style={{
                            padding: "11px 4px", textAlign: "right",
                            color: t.textSecondary, width: col.w,
                          }}>
                            {val || "—"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Global Styles */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

        * { margin: 0; padding: 0; box-sizing: border-box; }

        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20%, 60% { transform: translateX(-5px); }
          40%, 80% { transform: translateX(5px); }
        }

        button:hover {
          filter: brightness(1.06);
        }

        input:focus {
          border-color: ${t.primary} !important;
          box-shadow: 0 0 0 3px ${t.primaryFaint};
        }
      `}</style>

      {/* Player Details Modal */}
      {selectedPlayer && (
        <PlayerModal
          playerName={selectedPlayer}
          onClose={() => setSelectedPlayer(null)}
        />
      )}
    </div>
  );
}

// ── Player Details Modal ─────────────────────────────────────────────────────
function PlayerModal({ playerName, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState("7d");

  const hours = { "24h": 24, "7d": 168, "30d": 720 }[range] || 168;

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/player?name=${encodeURIComponent(playerName)}&hours=${hours}`)
      .then(res => res.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [playerName, hours]);

  // Close on escape
  useEffect(() => {
    const handler = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const catColors = {
    cr: t.catCrypt, ev: t.catEvent, ci: t.catCitadel, he: t.catHeroic, cl: t.catClan
  };
  const catLabels = {
    cr: "Crypts", ev: "Events", ci: "Citadels", he: "Heroic", cl: "Clan"
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000, padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: t.surface, borderRadius: 16, width: "100%", maxWidth: 600,
          maxHeight: "90vh", overflow: "auto", boxShadow: "0 25px 50px rgba(0,0,0,0.15)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "20px 24px", borderBottom: `1px solid ${t.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 600, color: t.text }}>{playerName}</h2>
            <p style={{ fontSize: 12, color: t.textTertiary, marginTop: 2 }}>Player Statistics</p>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 32, height: 32, borderRadius: 8, border: "none",
              background: t.surfaceAlt, color: t.textSecondary,
              fontSize: 18, cursor: "pointer", display: "flex",
              alignItems: "center", justifyContent: "center",
            }}
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: 24 }}>
          {/* Time Range */}
          <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
            {["24h", "7d", "30d"].map(r => (
              <button
                key={r}
                onClick={() => setRange(r)}
                style={{
                  padding: "6px 14px", fontSize: 12, fontWeight: 500,
                  border: "none", borderRadius: 6, cursor: "pointer",
                  background: range === r ? t.primary : t.surfaceAlt,
                  color: range === r ? "#fff" : t.textTertiary,
                }}
              >
                {r}
              </button>
            ))}
          </div>

          {loading ? (
            <div style={{ textAlign: "center", padding: 40, color: t.textTertiary }}>
              Loading...
            </div>
          ) : !data ? (
            <div style={{ textAlign: "center", padding: 40, color: "#e24b4a" }}>
              Failed to load player data
            </div>
          ) : (
            <>
              {/* Summary Stats */}
              <div style={{
                display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12,
                marginBottom: 24,
              }}>
                <div style={{ background: t.surfaceAlt, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 11, color: t.textTertiary, marginBottom: 4 }}>Total Chests</div>
                  <div style={{ fontSize: 24, fontWeight: 600, color: t.text }}>
                    {data.summary?.chest_count || 0}
                  </div>
                </div>
                <div style={{ background: t.surfaceAlt, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 11, color: t.textTertiary, marginBottom: 4 }}>Total Points</div>
                  <div style={{ fontSize: 24, fontWeight: 600, color: t.text }}>
                    {(data.summary?.total_points || 0).toLocaleString()}
                  </div>
                </div>
                <div style={{ background: t.surfaceAlt, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 11, color: t.textTertiary, marginBottom: 4 }}>Last Active</div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: t.text }}>
                    {data.summary?.last_seen
                      ? new Date(data.summary.last_seen).toLocaleDateString()
                      : "—"}
                  </div>
                </div>
              </div>

              {/* Category Breakdown */}
              <div style={{ marginBottom: 24 }}>
                <h3 style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
                  Category Breakdown
                </h3>
                <div style={{ display: "flex", gap: 8 }}>
                  {Object.entries(data.categories || {}).map(([cat, count]) => (
                    <div key={cat} style={{
                      flex: 1, background: `${catColors[cat]}10`, borderRadius: 8,
                      padding: 12, textAlign: "center", border: `1px solid ${catColors[cat]}30`,
                    }}>
                      <div style={{ fontSize: 20, fontWeight: 600, color: catColors[cat] }}>
                        {count}
                      </div>
                      <div style={{ fontSize: 11, color: t.textSecondary, marginTop: 2 }}>
                        {catLabels[cat]}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Daily Activity Chart */}
              {data.daily && data.daily.length > 0 && (
                <div style={{ marginBottom: 24 }}>
                  <h3 style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
                    Daily Activity
                  </h3>
                  <div style={{
                    background: t.surfaceAlt, borderRadius: 10, padding: 16,
                    height: 120, display: "flex", alignItems: "flex-end", gap: 4,
                  }}>
                    {(() => {
                      const maxChests = Math.max(...data.daily.map(d => d.chests), 1);
                      return data.daily.map((d, i) => (
                        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                          <div
                            style={{
                              width: "100%", maxWidth: 24, borderRadius: 4,
                              background: t.primary,
                              height: `${(d.chests / maxChests) * 80}px`,
                              minHeight: d.chests > 0 ? 4 : 0,
                            }}
                            title={`${new Date(d.date).toLocaleDateString()}: ${d.chests} chests, ${d.points} pts`}
                          />
                          <div style={{ fontSize: 9, color: t.textTertiary, marginTop: 4 }}>
                            {new Date(d.date).getDate()}
                          </div>
                        </div>
                      ));
                    })()}
                  </div>
                </div>
              )}

              {/* Recent Chests */}
              {data.recent && data.recent.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
                    Recent Chests
                  </h3>
                  <div style={{
                    background: t.surfaceAlt, borderRadius: 10,
                    maxHeight: 200, overflow: "auto",
                  }}>
                    {data.recent.slice(0, 10).map((c, i) => (
                      <div key={i} style={{
                        padding: "10px 14px", borderBottom: i < 9 ? `1px solid ${t.border}` : "none",
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                      }}>
                        <div>
                          <div style={{ fontSize: 13, color: t.text }}>{c.chestType}</div>
                          {c.source && (
                            <div style={{ fontSize: 11, color: t.textTertiary }}>{c.source}</div>
                          )}
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 13, fontWeight: 500, color: t.primary }}>
                            +{c.points} pts
                          </div>
                          <div style={{ fontSize: 10, color: t.textTertiary }}>
                            {new Date(c.scannedAt).toLocaleDateString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Admin View with Tabs ─────────────────────────────────────────────────────
function AdminView({ theme, onBack }) {
  const [activeTab, setActiveTab] = useState("jobs");

  const tabs = [
    { key: "jobs", label: "Jobs" },
    { key: "members", label: "Members" },
    { key: "roster", label: "Roster" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: t.bg, fontFamily: font, padding: "28px 24px 48px" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: t.text }}>⚙️ Admin Panel</h1>
          <a
            href="#"
            onClick={(e) => { e.preventDefault(); onBack(); }}
            style={{
              fontSize: 12, color: t.textTertiary, textDecoration: "none",
              padding: "6px 12px", borderRadius: 6, border: `1px solid ${t.border}`,
              background: t.surface,
            }}
          >
            ← Dashboard
          </a>
        </div>

        {/* Tabs */}
        <div style={{
          display: "flex",
          gap: 4,
          marginBottom: 20,
          borderBottom: `1px solid ${t.border}`,
          paddingBottom: 0,
        }}>
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: "10px 20px",
                fontSize: 13,
                fontWeight: 500,
                border: "none",
                borderBottom: activeTab === tab.key ? `2px solid ${t.primary}` : "2px solid transparent",
                background: "transparent",
                color: activeTab === tab.key ? t.text : t.textSecondary,
                cursor: "pointer",
                marginBottom: -1,
                transition: "all 0.15s",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {activeTab === "jobs" && <AdminPanel theme={theme} API_BASE={API_BASE} />}
        {activeTab === "members" && <MembersPanel theme={theme} API_BASE={API_BASE} />}
        {activeTab === "roster" && <RosterPanel theme={theme} API_BASE={API_BASE} />}
      </div>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
      `}</style>
    </div>
  );
}

// ── Admin Theme (matches new dashboard theme) ──────────────────────────────
const adminTheme = {
  bg: t.bg,
  surface: t.surface,
  surfaceAlt: t.surfaceAlt,
  border: t.border,
  gold: t.primary,        // Use primary purple instead of gold
  green: "#1d9e75",
  red: "#e24b4a",
  text: t.text,
  textMuted: t.textSecondary,
};

// ── App Root ────────────────────────────────────────────────────────────────
export default function App() {
  const [authed, setAuthed] = useState(() => sessionStorage.getItem("tb-dash-auth") === "1");
  const [view, setView] = useState(() => {
    // Check for admin route
    const hash = window.location.hash;
    const path = window.location.pathname;
    if (hash === "#admin" || path.includes("admin")) return "admin";
    return "dashboard";
  });

  // Listen for hash changes
  useEffect(() => {
    const handleHashChange = () => {
      setView(window.location.hash === "#admin" ? "admin" : "dashboard");
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  if (!authed) return <GateScreen onUnlock={() => setAuthed(true)} />;

  if (view === "admin") {
    return <AdminView theme={adminTheme} onBack={() => { setView("dashboard"); window.location.hash = ""; }} />;
  }

  return <Dashboard />;
}
