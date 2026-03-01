"""Flask dashboard — Chest leaderboard + chat log viewer."""

import logging
from flask import Flask, render_template_string, request
from storage import Storage

log = logging.getLogger(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>TB Toolkit Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f1419; color: #e7e9ea; }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        h1 { color: #ffd700; margin-bottom: 5px; font-size: 1.5rem; }
        .subtitle { color: #71767b; margin-bottom: 20px; font-size: 0.9rem; }

        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tabs a { padding: 8px 16px; background: #1d2226; color: #e7e9ea;
                  text-decoration: none; border-radius: 6px; font-size: 0.9rem; }
        .tabs a.active { background: #ffd700; color: #0f1419; font-weight: 600; }

        .filters { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .filters a { padding: 4px 12px; background: #1d2226; color: #71767b;
                     text-decoration: none; border-radius: 4px; font-size: 0.8rem; }
        .filters a.active { color: #ffd700; border: 1px solid #ffd700; }

        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 10px; color: #71767b; font-size: 0.8rem;
             text-transform: uppercase; border-bottom: 1px solid #2f3336; }
        td { padding: 10px; border-bottom: 1px solid #1d2226; font-size: 0.9rem; }
        tr:hover { background: #1d2226; }

        .rank { color: #71767b; width: 40px; }
        .rank-1 { color: #ffd700; font-weight: bold; }
        .rank-2 { color: #c0c0c0; font-weight: bold; }
        .rank-3 { color: #cd7f32; font-weight: bold; }
        .points { color: #ffd700; font-weight: 600; }
        .count { color: #71767b; }

        .chat-msg { padding: 8px 12px; border-bottom: 1px solid #1d2226; }
        .chat-msg:hover { background: #1d2226; }
        .chat-nick { color: #1d9bf0; font-weight: 600; }
        .chat-time { color: #71767b; font-size: 0.8rem; float: right; }
        .chat-text { margin-top: 2px; }
        .chat-channel { color: #71767b; font-size: 0.75rem; }

        .empty { color: #71767b; text-align: center; padding: 40px; }

        .stats { display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
        .stat-card { background: #1d2226; padding: 15px 20px; border-radius: 8px; flex: 1; min-width: 120px; }
        .stat-value { font-size: 1.5rem; color: #ffd700; font-weight: bold; }
        .stat-label { color: #71767b; font-size: 0.8rem; margin-top: 2px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚔️ TB Toolkit</h1>
        <p class="subtitle">Chest Counter & Chat Bridge Dashboard</p>

        <div class="tabs">
            <a href="/" class="{{ 'active' if tab == 'leaderboard' else '' }}">🏆 Leaderboard</a>
            <a href="/chat" class="{{ 'active' if tab == 'chat' else '' }}">💬 Chat Log</a>
        </div>

        {% if tab == 'leaderboard' %}
            <div class="filters">
                <a href="/?days=" class="{{ 'active' if not days else '' }}">All Time</a>
                <a href="/?days=7" class="{{ 'active' if days == 7 else '' }}">7 Days</a>
                <a href="/?days=14" class="{{ 'active' if days == 14 else '' }}">14 Days</a>
                <a href="/?days=30" class="{{ 'active' if days == 30 else '' }}">30 Days</a>
            </div>

            {% if stats %}
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{{ stats.total_players }}</div>
                    <div class="stat-label">Players</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ stats.total_chests }}</div>
                    <div class="stat-label">Chests</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ stats.total_points }}</div>
                    <div class="stat-label">Total Points</div>
                </div>
            </div>
            {% endif %}

            {% if leaderboard %}
            <table>
                <thead>
                    <tr><th>#</th><th>Player</th><th>Points</th><th>Chests</th><th>Last Seen</th></tr>
                </thead>
                <tbody>
                    {% for row in leaderboard %}
                    <tr>
                        <td class="rank rank-{{ loop.index if loop.index <= 3 else '' }}">{{ loop.index }}</td>
                        <td><a href="/player/{{ row.player_name }}?days={{ days or '' }}"
                               style="color: #e7e9ea; text-decoration: none;">{{ row.player_name }}</a></td>
                        <td class="points">{{ row.total_points }}</td>
                        <td class="count">{{ row.chest_count }}</td>
                        <td class="count">{{ row.last_seen[:16] if row.last_seen else '—' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">No chest data yet. Run a scan first.</div>
            {% endif %}

        {% elif tab == 'chat' %}
            {% if messages %}
                {% for msg in messages %}
                <div class="chat-msg">
                    <span class="chat-time">{{ msg.datetime_utc[:19] if msg.datetime_utc else '' }}</span>
                    <span class="chat-nick">{{ msg.nickname }}</span>
                    <span class="chat-channel">[{{ msg.channel_url | truncate(30) }}]</span>
                    <div class="chat-text">{{ msg.message }}</div>
                </div>
                {% endfor %}
            {% else %}
            <div class="empty">No chat messages captured yet. Start the chat bridge.</div>
            {% endif %}

        {% elif tab == 'player' %}
            <h2 style="margin-bottom: 15px;">{{ player_name }}</h2>
            {% if breakdown %}
            <table>
                <thead><tr><th>Chest Type</th><th>Points</th><th>Count</th></tr></thead>
                <tbody>
                    {% for row in breakdown %}
                    <tr>
                        <td>{{ row.chest_type }}</td>
                        <td class="points">{{ row.points }}</td>
                        <td class="count">{{ row.count }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">No chest data for this player.</div>
            {% endif %}
        {% endif %}
    </div>
</body>
</html>
"""


def create_app(config: dict) -> Flask:
    app = Flask(__name__)
    storage = Storage(config)

    @app.route("/")
    def leaderboard():
        days_str = request.args.get("days", "")
        days = int(days_str) if days_str.isdigit() else None
        lb = storage.get_leaderboard(days=days)

        stats = None
        if lb:
            stats = {
                "total_players": len(lb),
                "total_chests": sum(r["chest_count"] for r in lb),
                "total_points": sum(r["total_points"] for r in lb),
            }

        return render_template_string(DASHBOARD_HTML,
                                       tab="leaderboard", leaderboard=lb,
                                       days=days, stats=stats)

    @app.route("/chat")
    def chat():
        messages = storage.get_recent_chat(limit=200)
        return render_template_string(DASHBOARD_HTML,
                                       tab="chat", messages=messages)

    @app.route("/player/<name>")
    def player(name):
        days_str = request.args.get("days", "")
        days = int(days_str) if days_str.isdigit() else None
        breakdown = storage.get_gift_breakdown(name, days=days)
        return render_template_string(DASHBOARD_HTML,
                                       tab="player", player_name=name,
                                       breakdown=breakdown, days=days)

    return app
