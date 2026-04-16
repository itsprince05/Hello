import os
import json
import string
import random
import asyncio
import subprocess
import re
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from flask import Flask, jsonify, request, redirect, session, make_response
import threading

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8616525566:AAFF9H7s0iRacpAMzXZXS3ij3mN8ewJBh6o"
DASHBOARD_PORT = 8080
CLOUDFLARED_PATH = "./cloudflared.exe"  # Linux: ./cloudflared

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
tunnel_url = None
dashboard_password = None
active_groups = {}
activity_logs = []
MAX_LOGS = 200


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def generate_password(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def add_log(event_type, details):
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "details": details,
    }
    activity_logs.insert(0, entry)
    if len(activity_logs) > MAX_LOGS:
        activity_logs.pop()


# ─── INLINE CSS ───────────────────────────────────────────────────────────────
CSS = """
:root {
    --bg-primary: #0a0e1a;
    --bg-secondary: #111827;
    --bg-card: #1a1f35;
    --bg-card-hover: #222845;
    --bg-sidebar: #0d1225;
    --bg-input: #1e2440;
    --text-primary: #f0f2f5;
    --text-secondary: #9ca3b5;
    --text-muted: #6b7280;
    --accent-purple: #8b5cf6;
    --accent-blue: #3b82f6;
    --accent-green: #10b981;
    --accent-red: #ef4444;
    --accent-orange: #f59e0b;
    --accent-cyan: #06b6d4;
    --border-color: rgba(255,255,255,0.06);
    --shadow: 0 4px 24px rgba(0,0,0,0.3);
    --radius: 12px;
    --radius-sm: 8px;
    --sidebar-width: 260px;
    --font: 'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg-primary);color:var(--text-primary);min-height:100vh;overflow-x:hidden}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(139,92,246,0.3);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:rgba(139,92,246,0.5)}

.login-body{display:flex;align-items:center;justify-content:center;min-height:100vh;background:var(--bg-primary);background-image:radial-gradient(ellipse at 20% 50%,rgba(139,92,246,0.08) 0%,transparent 50%),radial-gradient(ellipse at 80% 20%,rgba(59,130,246,0.06) 0%,transparent 50%)}
.login-container{width:100%;max-width:420px;padding:20px}
.login-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:20px;padding:48px 36px;text-align:center;box-shadow:var(--shadow);animation:fadeInUp .5s ease}
.login-icon{font-size:48px;margin-bottom:16px}
.login-card h1{font-size:24px;font-weight:700;margin-bottom:8px;background:linear-gradient(135deg,var(--accent-purple),var(--accent-blue));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.login-subtitle{color:var(--text-secondary);font-size:14px;margin-bottom:28px}
.input-group{position:relative;margin-bottom:20px}
.input-group input{width:100%;padding:14px 50px 14px 18px;background:var(--bg-input);border:1px solid var(--border-color);border-radius:var(--radius-sm);color:var(--text-primary);font-size:15px;font-family:var(--font);outline:none;transition:border-color .3s,box-shadow .3s}
.input-group input:focus{border-color:var(--accent-purple);box-shadow:0 0 0 3px rgba(139,92,246,0.15)}
.toggle-pwd{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;font-size:18px;opacity:.6;transition:opacity .2s}
.toggle-pwd:hover{opacity:1}
.btn-login{width:100%;padding:14px;background:linear-gradient(135deg,var(--accent-purple),var(--accent-blue));border:none;border-radius:var(--radius-sm);color:#fff;font-size:15px;font-weight:600;font-family:var(--font);cursor:pointer;transition:transform .2s,box-shadow .2s}
.btn-login:hover{transform:translateY(-1px);box-shadow:0 8px 25px rgba(139,92,246,0.3)}
.btn-login:active{transform:translateY(0)}
.error-alert{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:var(--accent-red);padding:12px 16px;border-radius:var(--radius-sm);margin-bottom:20px;font-size:14px}

.app{display:flex;min-height:100vh}
.sidebar{width:var(--sidebar-width);background:var(--bg-sidebar);border-right:1px solid var(--border-color);display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100;transition:transform .3s ease}
.sidebar-header{display:flex;align-items:center;gap:12px;padding:24px 20px;border-bottom:1px solid var(--border-color)}
.logo{font-size:28px}
.sidebar-header h2{font-size:18px;font-weight:700;background:linear-gradient(135deg,var(--accent-purple),var(--accent-cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sidebar-nav{flex:1;padding:16px 12px;display:flex;flex-direction:column;gap:4px}
.nav-item{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:var(--radius-sm);color:var(--text-secondary);text-decoration:none;font-size:14px;font-weight:500;transition:all .2s;cursor:pointer}
.nav-item:hover{background:rgba(139,92,246,0.08);color:var(--text-primary)}
.nav-item.active{background:rgba(139,92,246,0.12);color:var(--accent-purple)}
.nav-icon{font-size:18px}
.sidebar-footer{padding:16px 12px;border-top:1px solid var(--border-color)}
.btn-logout{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:var(--radius-sm);color:var(--text-secondary);text-decoration:none;font-size:14px;transition:all .2s;width:100%}
.btn-logout:hover{background:rgba(239,68,68,0.1);color:var(--accent-red)}

.main-content{flex:1;margin-left:var(--sidebar-width);padding:0}
.top-header{display:flex;align-items:center;justify-content:space-between;padding:20px 32px;border-bottom:1px solid var(--border-color);background:rgba(10,14,26,0.8);backdrop-filter:blur(12px);position:sticky;top:0;z-index:50}
.header-left{display:flex;align-items:center;gap:16px}
.header-left h1{font-size:22px;font-weight:700}
.menu-toggle{display:none;background:none;border:none;color:var(--text-primary);font-size:24px;cursor:pointer}
.header-right{display:flex;align-items:center;gap:16px}
.status-badge{font-size:13px;padding:6px 14px;border-radius:20px;font-weight:500}
.status-badge.online{background:rgba(16,185,129,0.1);color:var(--accent-green);border:1px solid rgba(16,185,129,0.2)}
.time{color:var(--text-secondary);font-size:14px;font-weight:500}

.content-section{display:none;padding:28px 32px;animation:fadeIn .3s ease}
.content-section.active{display:block}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;margin-bottom:28px}
.stat-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:var(--radius);padding:24px;display:flex;align-items:center;gap:18px;transition:transform .2s,border-color .2s}
.stat-card:hover{transform:translateY(-2px);border-color:rgba(139,92,246,0.2)}
.stat-icon{width:50px;height:50px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.stat-icon.purple{background:rgba(139,92,246,0.12)}
.stat-icon.blue{background:rgba(59,130,246,0.12)}
.stat-icon.green{background:rgba(16,185,129,0.12)}
.stat-info{display:flex;flex-direction:column;gap:4px;min-width:0}
.stat-value{font-size:28px;font-weight:800;line-height:1.2}
.stat-value.small{font-size:13px;font-weight:600;color:var(--accent-cyan);word-break:break-all}
.stat-label{font-size:13px;color:var(--text-secondary);font-weight:500}

.content-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:20px}
.card,.card.full-width{background:var(--bg-card);border:1px solid var(--border-color);border-radius:var(--radius);overflow:hidden}
.card-header{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--border-color)}
.card-header h3{font-size:15px;font-weight:600}
.badge{background:rgba(139,92,246,0.15);color:var(--accent-purple);padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.btn-refresh{background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.2);color:var(--accent-purple);padding:6px 14px;border-radius:var(--radius-sm);cursor:pointer;font-size:13px;font-family:var(--font);font-weight:500;transition:all .2s}
.btn-refresh:hover{background:rgba(139,92,246,0.2)}
.card-body{padding:16px 22px;max-height:400px;overflow-y:auto}

.log-entry{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-color);font-size:13px}
.log-entry:last-child{border-bottom:none}
.log-type{padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;flex-shrink:0}
.log-type.command{background:rgba(59,130,246,0.12);color:var(--accent-blue)}
.log-type.system{background:rgba(16,185,129,0.12);color:var(--accent-green)}
.log-type.tunnel{background:rgba(139,92,246,0.12);color:var(--accent-purple)}
.log-type.error{background:rgba(239,68,68,0.12);color:var(--accent-red)}
.log-details{flex:1;color:var(--text-secondary);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.log-time{color:var(--text-muted);font-size:12px;flex-shrink:0}

.group-item{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border-color)}
.group-item:last-child{border-bottom:none}
.group-info{display:flex;flex-direction:column;gap:4px}
.group-name{font-weight:600;font-size:14px}
.group-id{font-size:12px;color:var(--accent-cyan);cursor:pointer;font-family:'JetBrains Mono',monospace;transition:color .2s}
.group-id:hover{color:var(--accent-purple)}
.group-joined{font-size:12px;color:var(--text-muted)}

.table-wrapper{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:12px 16px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border-color)}
td{padding:14px 16px;font-size:14px;border-bottom:1px solid var(--border-color)}
td.clickable{color:var(--accent-cyan);cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:13px}
td.clickable:hover{color:var(--accent-purple)}
tr:hover{background:rgba(139,92,246,0.03)}

.empty-state{text-align:center;padding:40px 20px;color:var(--text-muted);font-size:14px}
.loading-spinner{width:32px;height:32px;border:3px solid var(--border-color);border-top-color:var(--accent-purple);border-radius:50%;animation:spin .8s linear infinite;margin:30px auto}
.toast{position:fixed;bottom:24px;right:24px;background:var(--accent-green);color:#fff;padding:12px 24px;border-radius:var(--radius-sm);font-size:14px;font-weight:500;box-shadow:0 8px 30px rgba(16,185,129,0.3);transform:translateY(20px);opacity:0;transition:all .3s ease;z-index:9999}
.toast.show{transform:translateY(0);opacity:1}

@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes spin{to{transform:rotate(360deg)}}

@media(max-width:768px){
    .sidebar{transform:translateX(-100%)}
    .sidebar.open{transform:translateX(0)}
    .main-content{margin-left:0}
    .menu-toggle{display:block}
    .content-section{padding:20px 16px}
    .top-header{padding:16px 20px}
    .stats-grid{grid-template-columns:1fr}
    .content-grid{grid-template-columns:1fr}
    .stat-value{font-size:22px}
}
"""

# ─── INLINE HTML: LOGIN ──────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login — Bot Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{css}</style>
</head>
<body class="login-body">
    <div class="login-container">
        <div class="login-card">
            <div class="login-icon">🔐</div>
            <h1>Dashboard Access</h1>
            <p class="login-subtitle">Enter the password from your Telegram bot</p>
            {error_block}
            <form method="POST" action="/login">
                <div class="input-group">
                    <input type="password" name="password" id="password" placeholder="Enter password" autocomplete="off" required>
                    <button type="button" class="toggle-pwd" onclick="togglePassword()">👁️</button>
                </div>
                <button type="submit" class="btn-login">Login</button>
            </form>
        </div>
    </div>
    <script>
        function togglePassword() {{
            const input = document.getElementById('password');
            input.type = input.type === 'password' ? 'text' : 'password';
        }}
    </script>
</body>
</html>"""

# ─── INLINE HTML: DASHBOARD ─────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>{css}</style>
</head>
<body>
    <div class="app">
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="logo">🤖</div>
                <h2>Bot Panel</h2>
            </div>
            <nav class="sidebar-nav">
                <a href="#" class="nav-item active" data-section="overview">
                    <span class="nav-icon">📊</span><span>Overview</span>
                </a>
                <a href="#" class="nav-item" data-section="groups">
                    <span class="nav-icon">👥</span><span>Groups</span>
                </a>
                <a href="#" class="nav-item" data-section="logs">
                    <span class="nav-icon">📋</span><span>Activity Logs</span>
                </a>
            </nav>
            <div class="sidebar-footer">
                <a href="/logout" class="btn-logout">🚪 Logout</a>
            </div>
        </aside>
        <main class="main-content">
            <header class="top-header">
                <div class="header-left">
                    <button class="menu-toggle" onclick="toggleSidebar()">☰</button>
                    <h1 id="page-title">Overview</h1>
                </div>
                <div class="header-right">
                    <span class="status-badge online">● Online</span>
                    <span class="time" id="current-time"></span>
                </div>
            </header>
            <section id="section-overview" class="content-section active">
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon purple">👥</div>
                        <div class="stat-info">
                            <span class="stat-value" id="stat-groups">0</span>
                            <span class="stat-label">Active Groups</span>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon blue">🌐</div>
                        <div class="stat-info">
                            <span class="stat-value small" id="stat-tunnel">Loading...</span>
                            <span class="stat-label">Tunnel URL</span>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon green">⚡</div>
                        <div class="stat-info">
                            <span class="stat-value" id="stat-status">Active</span>
                            <span class="stat-label">Bot Status</span>
                        </div>
                    </div>
                </div>
                <div class="content-grid">
                    <div class="card">
                        <div class="card-header"><h3>📋 Recent Activity</h3></div>
                        <div class="card-body" id="recent-activity"><div class="loading-spinner"></div></div>
                    </div>
                    <div class="card">
                        <div class="card-header"><h3>👥 Groups</h3></div>
                        <div class="card-body" id="groups-preview"><div class="loading-spinner"></div></div>
                    </div>
                </div>
            </section>
            <section id="section-groups" class="content-section">
                <div class="card full-width">
                    <div class="card-header">
                        <h3>👥 All Groups</h3>
                        <span class="badge" id="groups-count">0</span>
                    </div>
                    <div class="card-body" id="all-groups"><div class="loading-spinner"></div></div>
                </div>
            </section>
            <section id="section-logs" class="content-section">
                <div class="card full-width">
                    <div class="card-header">
                        <h3>📋 Activity Logs</h3>
                        <button class="btn-refresh" onclick="fetchStats()">🔄 Refresh</button>
                    </div>
                    <div class="card-body" id="all-logs"><div class="loading-spinner"></div></div>
                </div>
            </section>
        </main>
    </div>
    <script>
        document.querySelectorAll('.nav-item').forEach(item => {{
            item.addEventListener('click', (e) => {{
                e.preventDefault();
                const section = item.dataset.section;
                document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
                item.classList.add('active');
                document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
                document.getElementById('section-'+section).classList.add('active');
                document.getElementById('page-title').textContent = section.charAt(0).toUpperCase()+section.slice(1);
            }});
        }});
        function toggleSidebar() {{ document.querySelector('.sidebar').classList.toggle('open'); }}
        function updateTime() {{
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleTimeString('en-US',{{hour:'2-digit',minute:'2-digit'}});
        }}
        setInterval(updateTime,1000); updateTime();
        function copyText(text) {{
            navigator.clipboard.writeText(text).then(()=>{{ showToast('Copied to clipboard!'); }});
        }}
        function showToast(message) {{
            const toast = document.createElement('div');
            toast.className='toast'; toast.textContent=message;
            document.body.appendChild(toast);
            setTimeout(()=>toast.classList.add('show'),10);
            setTimeout(()=>{{ toast.classList.remove('show'); setTimeout(()=>toast.remove(),300); }},2000);
        }}
        async function fetchStats() {{
            try {{
                const res = await fetch('/api/stats');
                if(res.status===401){{ window.location.href='/login'; return; }}
                const data = await res.json();
                document.getElementById('stat-groups').textContent=data.total_groups;
                document.getElementById('stat-tunnel').textContent=data.tunnel_url||'Starting...';
                document.getElementById('stat-tunnel').onclick=()=>{{ if(data.tunnel_url) copyText(data.tunnel_url); }};
                document.getElementById('stat-tunnel').style.cursor='pointer';

                const actEl=document.getElementById('recent-activity');
                if(data.logs.length===0){{ actEl.innerHTML='<div class="empty-state">No activity yet</div>'; }}
                else {{ actEl.innerHTML=data.logs.slice(0,10).map(log=>`
                    <div class="log-entry">
                        <span class="log-type ${{log.type.toLowerCase()}}">${{log.type}}</span>
                        <span class="log-details">${{log.details}}</span>
                        <span class="log-time">${{log.timestamp}}</span>
                    </div>`).join(''); }}

                const grpEl=document.getElementById('groups-preview');
                if(data.groups.length===0){{ grpEl.innerHTML='<div class="empty-state">No groups yet. Add bot to a group and use /start</div>'; }}
                else {{ grpEl.innerHTML=data.groups.slice(0,5).map(g=>`
                    <div class="group-item">
                        <div class="group-info">
                            <span class="group-name">${{g.name}}</span>
                            <span class="group-id" onclick="copyText('${{g.id}}')" title="Click to copy">${{g.id}}</span>
                        </div>
                        <span class="group-joined">${{g.joined_at}}</span>
                    </div>`).join(''); }}

                document.getElementById('groups-count').textContent=data.groups.length;
                const allGrp=document.getElementById('all-groups');
                if(data.groups.length===0){{ allGrp.innerHTML='<div class="empty-state">No groups yet</div>'; }}
                else {{ allGrp.innerHTML=`<div class="table-wrapper"><table><thead><tr><th>Group Name</th><th>Group ID</th><th>Joined At</th></tr></thead><tbody>${{data.groups.map(g=>`<tr><td>${{g.name}}</td><td class="clickable" onclick="copyText('${{g.id}}')">${{g.id}}</td><td>${{g.joined_at}}</td></tr>`).join('')}}</tbody></table></div>`; }}

                const allLogs=document.getElementById('all-logs');
                if(data.logs.length===0){{ allLogs.innerHTML='<div class="empty-state">No logs yet</div>'; }}
                else {{ allLogs.innerHTML=data.logs.map(log=>`
                    <div class="log-entry">
                        <span class="log-type ${{log.type.toLowerCase()}}">${{log.type}}</span>
                        <span class="log-details">${{log.details}}</span>
                        <span class="log-time">${{log.timestamp}}</span>
                    </div>`).join(''); }}
            }} catch(err) {{ console.error('Failed to fetch stats:',err); }}
        }}
        fetchStats(); setInterval(fetchStats,10000);
    </script>
</body>
</html>"""


# ─── CLOUDFLARE TUNNEL ───────────────────────────────────────────────────────
def start_cloudflare_tunnel():
    global tunnel_url
    try:
        process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{DASHBOARD_PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for line in process.stderr:
            logger.info(f"[cloudflared] {line.strip()}")
            match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
            if match:
                tunnel_url = match.group(0)
                logger.info(f"✅ Tunnel URL: {tunnel_url}")
                add_log("TUNNEL", f"Cloudflare tunnel started: {tunnel_url}")
                break
    except Exception as e:
        logger.error(f"❌ Failed to start cloudflare tunnel: {e}")
        add_log("ERROR", f"Tunnel failed: {e}")


# ─── FLASK DASHBOARD ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = generate_password(32)


def render_login(error=None):
    error_block = ""
    if error:
        error_block = f'<div class="error-alert"><span>⚠️</span> {error}</div>'
    return LOGIN_HTML.format(css=CSS, error_block=error_block)


def render_dashboard():
    return DASHBOARD_HTML.format(css=CSS)


@app.route("/")
def index():
    if not session.get("authenticated"):
        return redirect("/login")
    return render_dashboard()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == dashboard_password:
            session["authenticated"] = True
            return redirect("/")
        return render_login(error="Incorrect Password")
    return render_login()


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect("/login")


@app.route("/api/stats")
def api_stats():
    if not session.get("authenticated"):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(
        {
            "total_groups": len(active_groups),
            "tunnel_url": tunnel_url,
            "groups": list(active_groups.values()),
            "logs": activity_logs[:50],
        }
    )


# ─── BOT HANDLERS ────────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        return

    group_name = chat.title or "Unknown Group"
    group_id = str(chat.id)

    active_groups[group_id] = {
        "name": group_name,
        "id": group_id,
        "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    add_log("COMMAND", f"/start used in {group_name} ({group_id})")

    message_text = (
        f"📌 <b>Group Name:</b> {group_name}\n"
        f"🆔 <b>Group ID:</b> <code>{group_id}</code>"
    )
    await update.message.reply_text(message_text, parse_mode="HTML")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        return

    if not tunnel_url:
        await update.message.reply_text("⏳ Tunnel is not ready yet. Please wait...")
        return

    add_log("COMMAND", f"/dashboard used in {chat.title} ({chat.id})")

    message_text = (
        f"🌐 <b>Dashboard Access</b>\n\n"
        f"🔗 <b>URL:</b> <code>{tunnel_url}</code>\n"
        f"🔑 <b>Password:</b> <code>{dashboard_password}</code>\n\n"
        f"⚠️ <i>This URL changes every restart. Password is auto-generated.</i>"
    )
    await update.message.reply_text(message_text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        return

    add_log("COMMAND", f"/help used in {chat.title} ({chat.id})")

    message_text = (
        "🤖 <b>Bot Commands</b>\n\n"
        "📌 /start — Show group name & ID\n"
        "🌐 /dashboard — Get dashboard access URL\n"
        "❓ /help — Show this help message\n\n"
        "<i>Note: This bot only works in groups.</i>"
    )
    await update.message.reply_text(message_text, parse_mode="HTML")


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # Silently ignore all DMs


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def run_flask():
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False)


def main():
    global dashboard_password

    dashboard_password = generate_password(12)
    logger.info(f"🔑 Dashboard Password: {dashboard_password}")

    # Start Cloudflare tunnel in background
    tunnel_thread = threading.Thread(target=start_cloudflare_tunnel, daemon=True)
    tunnel_thread.start()

    import time
    time.sleep(5)

    # Start Flask dashboard in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Dashboard running on port {DASHBOARD_PORT}")

    # Build and run the Telegram bot
    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("dashboard", dashboard_command))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_private_message))

    logger.info("🤖 Bot is running...")
    add_log("SYSTEM", "Bot started successfully")

    bot_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
