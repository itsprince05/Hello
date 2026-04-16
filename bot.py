import os
import sys
import asyncio
import string
import random
import subprocess
import re
import logging
import platform
import time
import threading
import socket
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from flask import Flask, jsonify, request, redirect, session

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8616525566:AAFF9H7s0iRacpAMzXZXS3ij3mN8ewJBh6o"

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

DASHBOARD_PORT = get_free_port()
ALLOWED_GROUP_ID = -1003881179060

# Auto-detect OS for cloudflared binary
if platform.system() == "Windows":
    CLOUDFLARED_PATH = "./cloudflared.exe"
else:
    CLOUDFLARED_PATH = "./cloudflared"

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
tunnel_url = None
tunnel_process = None
tunnel_url_ready = threading.Event()
active_groups = {}
activity_logs = []
MAX_LOGS = 200

SHOWS_FILE = "shows.json"

def load_shows():
    import os, json
    if os.path.exists(SHOWS_FILE):
        with open(SHOWS_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_shows(data):
    import json
    with open(SHOWS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

shows_list = load_shows()


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


# ─── HTML BUILDER ─────────────────────────────────────────────────────────────
def get_dashboard_html():
    import html as html_escape
    global shows_list
    if shows_list:
        empty_display = "none"
        list_display = "flex"
        shows_rendered = "".join([
            f"""<div class="item" style="display:flex; justify-content:space-between; align-items:center; background:#fff; padding:0; padding-right:10px; border-radius:10px; border:1px solid #e0e0e0; box-shadow:0 1px 2px rgba(0,0,0,0.05); overflow:hidden;">
                <div style="display:flex; gap:10px; align-items:center; align-self:stretch;">
                    <div style="width:80px; align-self:stretch; background:#f0f2f5; flex-shrink:0; display:flex; align-items:center; justify-content:center;">
                        {f'<img src="{html_escape.escape(s.get("image", ""))}" style="width:100%; height:100%; object-fit:cover;">' if s.get("image") else '<span style="font-size:26px;">📺</span>'}
                    </div>
                    <div style="display:flex; flex-direction:column; gap:4px; margin: 10px 0;">
                        <div style="font-weight:600; font-size:15px; color:#1c1e21;">{html_escape.escape(s.get("name", ""))}</div>
                        <div style="font-size:13px; color:#666;">ID: <span style="color:#2481cc;">{html_escape.escape(s.get("id", ""))}</span></div>
                        <div style="font-size:12px; color:#999;">UID: {html_escape.escape(s.get("rj_uid", "")) or 'N/A'}</div>
                    </div>
                </div>
            </div>"""
            for s in shows_list
        ])
    else:
        empty_display = "block"
        list_display = "none"
        shows_rendered = ""

    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shows</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Outfit', sans-serif; 
            background-color: #f0f2f5; 
            margin: 0; padding: 0; 
            color: #1c1e21; 
        }
        .action-bar { 
            position: relative; z-index: 100; box-sizing: border-box; height: 48px;
            background: #2481cc; color: white; padding: 0 10px; gap: 10px;
            display: flex; align-items: center; justify-content: space-between;
            box-shadow: none; 
        }
        .nav-left { display: flex; align-items: center; }
        .navbar-icon { width: 32px; height: 32px; border-radius: 50%; margin-right: 12px; display: flex; align-items: center; justify-content: center; background: white; color: #2481cc; }
        .navbar-icon svg { width: 18px; height: 18px; }
        .navbar-title { font-size: 18px; font-weight: 600; color: white; letter-spacing: 0.5px; }
        
        .tabs { 
            display: flex; width: 100%; height: 48px; background-color: #2481cc; align-items: center; 
            position: sticky; top: 0; z-index: 99;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .tab { 
            flex: 1; height: 100%; display: flex; align-items: center; justify-content: center;
            font-weight: 500; font-size: 14px; text-transform: none; letter-spacing: 0.5px;
            color: rgba(255,255,255,0.7); cursor: pointer; 
            border-bottom: 3px solid transparent; transition: background 0.2s, color 0.2s; 
        }
        .tab.active { color: #ffffff; border-bottom-color: #ffffff; background-color: rgba(255, 255, 255, 0.15); }
        .tab:hover { background-color: rgba(255,255,255,0.1); color: #ffffff; }

        .container { max-width: 800px; margin: 0 auto; padding: 15px; display: none; }
        .container.active { display: block; }

        .card { 
            background: #ffffff; border-radius: 10px; padding: 20px; border: 1px solid #e0e0e0; 
            margin-bottom: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        .card h3 { margin-top: 0; font-size: 16px; color: #1c1e21; margin-bottom: 15px; border-bottom: 1px solid #eee; padding-bottom: 10px; }
        
        .stat-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
        .stat-row:last-child { border-bottom: none; }
        .stat-label { font-weight: 500; color: #666; font-size: 14px; }
        .stat-val { font-weight: 600; color: #1c1e21; font-size: 14px; }
        .stat-val.blue { color: #2481cc; cursor: pointer; word-break: break-all; }

        .item-list { display: flex; flex-direction: column; gap: 10px; }
        .item { padding: 12px; border-radius: 8px; background: #f9f9f9; border: 1px solid #eee; display:flex; justify-content:space-between; align-items:center; }
        .item-title { font-weight: 600; font-size: 14px; color: #333; }
        .item-sub { font-size: 12px; color: #777; margin-top: 4px; }
        .item-action { cursor: pointer; color: #2481cc; font-size: 12px; font-weight: bold; background: #eef5fb; padding: 5px 10px; border-radius: 6px; }

        .log-item { padding: 8px 0; border-bottom: 1px solid #eee; font-size: 13px; display: flex; align-items: center; gap: 10px; }
        .log-item:last-child { border-bottom: none; }
        .log-type { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; flex-shrink: 0; text-transform: uppercase; }
        .log-type.system { background: #e6fcf5; color: #0ca678; }
        .log-type.tunnel { background: #f3f0ff; color: #845ef7; }
        .log-type.command { background: #e7f5ff; color: #339af0; }
        .log-type.error { background: #fff5f5; color: #fa5252; }
        .log-details { flex: 1; color: #555; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .log-time { color: #999; font-size: 11px; flex-shrink: 0; }

        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%) translateY(50px); background: #333; color: white; padding: 10px 20px; border-radius: 8px; font-size: 14px; opacity: 0; transition: 0.3s; pointer-events: none; z-index: 9999; }
        .toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }
    </style>
</head>
<body>
    <div class="action-bar">
        <div class="nav-left">
            <div class="navbar-icon"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-music4-icon lucide-music-4"><path d="M9 18V5l12-2v13"/><path d="m9 9 12-2"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg></div>
            <div class="navbar-title">Bot Dashboard</div>
        </div>
    </div>
    
    <div class="tabs">
        <div class="tab active" onclick="switchTab('all-show', event)">All Show</div>
        <div class="tab" onclick="switchTab('add-show', event)">Add Show</div>
    </div>

    <!-- TAB 1: ALL SHOW -->
    <div id="all-show" class="container active">
        <div class="card" id="empty-state" style="text-align:center; padding: 60px 20px; color: #666; display:{{EMPTY_DISPLAY}};">
            <div style="margin-bottom: 15px; color: #aaa;">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-brush-cleaning-icon lucide-brush-cleaning"><path d="m16 22-1-4"/><path d="M19 14a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2h-3a1 1 0 0 1-1-1V4a2 2 0 0 0-4 0v5a1 1 0 0 1-1 1H6a2 2 0 0 0-2 2v1a1 1 0 0 0 1 1"/><path d="M19 14H5l-1.973 6.767A1 1 0 0 0 4 22h16a1 1 0 0 0 .973-1.233z"/><path d="m8 22 1-4"/></svg>
            </div>
            <h4 style="margin:0 0 10px 0; color:#1c1e21; font-weight: 500; font-size: 18px;">Empty List</h4>
            <p style="font-size: 14px; margin:0; color:#888;">No shows available right now.</p>
        </div>
        <div id="shows-list" style="display:{{LIST_DISPLAY}}; flex-direction:column; gap:15px;">{{SHOWS_LIST}}</div>
    </div>

    <!-- TAB 2: ADD SHOW -->
    <div id="add-show" class="container">
        <div class="card">
            <h3 style="margin-top:0; color:#1c1e21; border-bottom:1px solid #eee; padding-bottom:10px;">Add Show</h3>
            <div style="display:flex; flex-direction:column; gap: 10px; margin-top: 10px;">
                <input type="text" id="add-show-name" placeholder="Show Name" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <input type="text" id="add-show-id" placeholder="Show ID" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <input type="text" id="add-show-image" placeholder="Show Image URL" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <input type="text" id="add-show-rj-uid" placeholder="RJ UID" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <input type="text" id="add-show-rj-token" placeholder="RJ Refresh Token" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <button onclick="submitAddShow()" style="width: 100%; padding: 12px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 15px; cursor: pointer;">Add Show</button>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">Copied to clipboard!</div>

    <script>
        function switchTab(tabId, event) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.container').forEach(c => c.classList.remove('active'));
            event.currentTarget.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }

        function copyText(text) {
            navigator.clipboard.writeText(text);
            const toast = document.getElementById('toast');
            toast.textContent = "Copied to clipboard!";
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 2000);
        }

        function renderGroup(g) {
            return `<div class="item">
                <div>
                    <div class="item-title">${g.name}</div>
                    <div class="item-sub">Joined: ${g.joined_at}</div>
                </div>
                <div class="item-action" onclick="copyText('${g.id}')">Copy ID</div>
            </div>`;
        }

        function renderLog(l) {
            let typeClass = l.type.toLowerCase();
            return `<div class="log-item">
                <span class="log-type ${typeClass}">${l.type}</span>
                <span class="log-details">${l.details}</span>
                <span class="log-time">${l.timestamp.split(' ')[1]}</span>
            </div>`;
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();

                // No DOM DOM updates for Empty List

            } catch(e) { console.error(e); }
        }

        async function submitAddShow() {
            const data = {
                name: document.getElementById('add-show-name').value,
                id: document.getElementById('add-show-id').value,
                image: document.getElementById('add-show-image').value,
                rj_uid: document.getElementById('add-show-rj-uid').value,
                rj_token: document.getElementById('add-show-rj-token').value
            };
            if(!data.name || !data.id) return alert("Show Name and Show ID are required!");

            try {
                const res = await fetch('/api/shows', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if(res.ok) {
                    ['name', 'id', 'image', 'rj-uid', 'rj-token'].forEach(f => document.getElementById(`add-show-${f}`).value = '');
                    alert("Show added successfully!");
                    loadShows();
                    document.querySelectorAll('.tab')[0].click();
                } else {
                    alert("Failed to add show.");
                }
            } catch(e) { console.error(e); }
        }

        async function loadShows() {
            try {
                const res = await fetch('/api/shows');
                const data = await res.json();
                
                const listContainer = document.getElementById('shows-list');
                const emptyState = document.getElementById('empty-state');
                
                if(data.shows && data.shows.length > 0) {
                    emptyState.style.display = 'none';
                    listContainer.style.display = 'flex';
                    listContainer.innerHTML = data.shows.map(s => 
                        `<div class="item" style="display:flex; justify-content:space-between; align-items:center; background:#fff; padding:0; padding-right:10px; border-radius:10px; border:1px solid #e0e0e0; box-shadow:0 1px 2px rgba(0,0,0,0.05); overflow:hidden;">
                            <div style="display:flex; gap:10px; align-items:center; align-self:stretch;">
                                <div style="width:80px; align-self:stretch; background:#f0f2f5; flex-shrink:0; display:flex; align-items:center; justify-content:center;">
                                    ${s.image ? `<img src="${s.image}" style="width:100%; height:100%; object-fit:cover;">` : '<span style="font-size:26px;">📺</span>'}
                                </div>
                                <div style="display:flex; flex-direction:column; gap:4px; margin: 10px 0;">
                                    <div style="font-weight:600; font-size:15px; color:#1c1e21;">${s.name}</div>
                                    <div style="font-size:13px; color:#666;">ID: <span style="color:#2481cc;">${s.id}</span></div>
                                    <div style="font-size:12px; color:#999;">UID: ${s.rj_uid || 'N/A'}</div>
                                </div>
                            </div>
                        </div>`
                    ).join('');
                } else {
                    emptyState.style.display = 'block';
                    listContainer.style.display = 'none';
                }
            } catch(e) { console.error(e); }
        }

        loadStats();
        loadShows();
        setInterval(loadStats, 5000);
    </script>
</body>
</html>'''

    return html.replace("{{EMPTY_DISPLAY}}", empty_display).replace("{{LIST_DISPLAY}}", list_display).replace("{{SHOWS_LIST}}", shows_rendered)


# ─── CLOUDFLARE TUNNEL ───────────────────────────────────────────────────────
CLOUDFLARED_LINUX_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"


def ensure_cloudflared():
    """Download cloudflared binary if not found (Linux only)"""
    if os.path.exists(CLOUDFLARED_PATH):
        # Make sure it's executable on Linux
        if platform.system() != "Windows":
            os.chmod(CLOUDFLARED_PATH, 0o755)
        return True

    if platform.system() == "Windows":
        logger.error("cloudflared.exe not found. Download from: https://github.com/cloudflare/cloudflared/releases")
        return False

    # Auto-download on Linux
    logger.info("cloudflared not found. Downloading...")
    try:
        import urllib.request
        urllib.request.urlretrieve(CLOUDFLARED_LINUX_URL, CLOUDFLARED_PATH)
        os.chmod(CLOUDFLARED_PATH, 0o755)
        logger.info("cloudflared downloaded successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to download cloudflared: {e}")
        return False


def start_cloudflare_tunnel():
    """Start tunnel — reads stderr (where cloudflared logs) in a thread that runs forever"""
    global tunnel_url, tunnel_process

    if not ensure_cloudflared():
        add_log("ERROR", "cloudflared binary not available")
        return

    tunnel_url_ready.clear()

    try:
        logger.info(f"Starting cloudflare tunnel with: {CLOUDFLARED_PATH}")
        tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://127.0.0.1:{DASHBOARD_PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def read_stream(stream, name):
            """Read a stream line by line — runs forever keeping process alive"""
            global tunnel_url
            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="ignore").strip()
                    if not decoded:
                        continue
                    logger.info(f"[cloudflared-{name}] {decoded}")
                    if not tunnel_url and ".trycloudflare.com" in decoded:
                        match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", decoded)
                        if match:
                            tunnel_url = match.group(0)
                            logger.info(f"Tunnel URL: {tunnel_url}")
                            add_log("TUNNEL", f"Tunnel started: {tunnel_url}")
                            tunnel_url_ready.set()
            except Exception as e:
                logger.error(f"Error reading {name}: {e}")

        # Read both stdout and stderr in separate threads (cloudflared logs to stderr)
        threading.Thread(target=read_stream, args=(tunnel_process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=read_stream, args=(tunnel_process.stderr, "stderr"), daemon=True).start()

    except FileNotFoundError:
        logger.error(f"cloudflared binary not found at: {CLOUDFLARED_PATH}")
        add_log("ERROR", "cloudflared binary not found")
    except Exception as e:
        logger.error(f"Failed to start cloudflare tunnel: {e}")
        add_log("ERROR", f"Tunnel failed: {e}")


def stop_tunnel():
    """Kill the current tunnel process"""
    global tunnel_process, tunnel_url
    tunnel_url = None
    tunnel_url_ready.clear()
    if tunnel_process:
        try:
            tunnel_process.kill()
            tunnel_process.wait(timeout=5)
        except:
            pass
        tunnel_process = None


def restart_tunnel():
    """Stop old tunnel, start new one, wait for URL"""
    stop_tunnel()
    start_cloudflare_tunnel()
    # Wait up to 30 seconds for URL
    tunnel_url_ready.wait(timeout=30)


# ─── FLASK DASHBOARD ─────────────────────────────────────────────────────────
flask_app = Flask(__name__)
flask_app.secret_key = generate_password(32)


@flask_app.route("/health")
def health():
    return "OK", 200


@flask_app.route("/")
def index():
    return get_dashboard_html()


@flask_app.route("/api/stats")
def api_stats():
    return jsonify({
        "total_groups": len(active_groups),
        "tunnel_url": tunnel_url,
        "groups": list(active_groups.values()),
        "logs": activity_logs[:50],
    })


@flask_app.route("/api/shows", methods=["GET", "POST"])
def api_shows():
    if request.method == "POST":
        data = request.json
        shows_list.append(data)
        save_shows(shows_list)
        return jsonify({"status": "success"})
        
    return jsonify({"shows": shows_list})


# ─── BOT HANDLERS ────────────────────────────────────────────────────────────
def is_allowed(chat_id):
    """Check if the chat is the allowed group"""
    return chat_id == ALLOWED_GROUP_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed(chat.id):
        return  # No response — bot appears dead

    group_name = chat.title or "Unknown Group"
    group_id = str(chat.id)

    active_groups[group_id] = {
        "name": group_name,
        "id": group_id,
        "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    add_log("COMMAND", f"/start used in {group_name} ({group_id})")

    message_text = (
        f"<b>Group Name:</b> {group_name}\n"
        f"<b>Group ID:</b> <code>{group_id}</code>"
    )
    await update.message.reply_text(message_text, parse_mode="HTML")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed(chat.id):
        return

    add_log("COMMAND", f"/dashboard used in {chat.title} ({chat.id})")

    msg = await update.message.reply_text("Generating URL...")

    # Restart tunnel in background and wait for new URL (max 30s)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, restart_tunnel)

    if tunnel_url:
        message_text = (
            f"Dashboard URL...\n\n"
            f"{tunnel_url}"
        )
        await msg.edit_text(message_text, parse_mode="HTML")
    else:
        await msg.edit_text("Generating URL Failed...")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed(chat.id):
        return

    add_log("COMMAND", f"/list used in {chat.title} ({chat.id})")

    message_text = (
        "/start - Group Name and ID\n"
        "/dashboard - Dashboard URL\n"
        "/update - Update Bot"
    )
    await update.message.reply_text(message_text)


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed(chat.id):
        return

    user = update.effective_user

    # Check if user is admin with can_change_info permission
    try:
        member = await chat.get_member(user.id)
        is_admin = member.status in ["creator", "administrator"]
        can_change = False
        if member.status == "creator":
            can_change = True
        elif member.status == "administrator" and member.can_change_info:
            can_change = True

        if not is_admin or not can_change:
            await update.message.reply_text("You don't have permission to use this command...")
            return
    except Exception as e:
        logger.error(f"Failed to check admin status: {e}")
        await update.message.reply_text("Failed to verify permissions.")
        return

    add_log("COMMAND", f"/update used by {user.first_name} ({user.id})")

    msg = await update.message.reply_text("Updating Bot...")

    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip() or ""

        if "Already up to date" in output:
            await msg.edit_text("Already up to date...")
        else:
            await msg.edit_text("Update Complete...")
            add_log("SYSTEM", "Bot restarting after update")
            time.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except subprocess.TimeoutExpired:
        await msg.edit_text("Update timed out.")
    except Exception as e:
        logger.error(f"Update failed: {e}")
        await msg.edit_text(f"Update failed...")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def run_flask():
    try:
        from waitress import serve
        logger.info(f"Starting waitress server on 127.0.0.1:{DASHBOARD_PORT}")
        serve(flask_app, host="127.0.0.1", port=DASHBOARD_PORT, threads=4)
    except Exception as e:
        logger.error(f"Server CRASHED: {e}")


async def send_startup_message(bot_app):
    """Send 'Bot is Running...' then edit with dashboard info"""
    try:
        # First send plain message
        msg = await bot_app.bot.send_message(
            chat_id=ALLOWED_GROUP_ID,
            text="Bot is Running...",
        )

        # Wait for tunnel URL
        for _ in range(30):
            if tunnel_url:
                break
            await asyncio.sleep(1)

        # Edit with dashboard info
        if tunnel_url:
            text = (
                f"Bot is Running...\n\n"
                f"{tunnel_url}"
            )
            await msg.edit_text(text, parse_mode="HTML")
        else:
            await msg.edit_text("Bot is Running...\n\nURL not ready yet. Use /dashboard later..")

        logger.info("Startup message sent to group.")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")


def main():
    print("=" * 50)
    print("TELEGRAM BOT + DASHBOARD STARTING")
    print("=" * 50)

    # Start Flask dashboard FIRST so it's ready when tunnel connects
    logger.info(f"Starting dashboard on port {DASHBOARD_PORT}...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(3)

    # Verify Flask is running
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{DASHBOARD_PORT}/health", timeout=5)
        logger.info(f"Flask health check: {resp.read().decode()}")
    except Exception as e:
        logger.error(f"Flask NOT responding on port {DASHBOARD_PORT}: {e}")

    # Start Cloudflare tunnel in background
    logger.info("Starting Cloudflare tunnel...")
    tunnel_thread = threading.Thread(target=start_cloudflare_tunnel, daemon=True)
    tunnel_thread.start()

    # Build and run the Telegram bot
    logger.info("Starting Telegram bot...")
    bot_app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("dashboard", dashboard_command))
    bot_app.add_handler(CommandHandler("list", list_command))
    bot_app.add_handler(CommandHandler("update", update_command))

    add_log("SYSTEM", "Bot started successfully")
    logger.info("Bot is Running...")

    # Send startup message using post_init
    bot_app.post_init = lambda app: send_startup_message(app)

    bot_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
