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
DASHBOARD_PORT = 8080
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
dashboard_password = None
tunnel_process = None
tunnel_url_ready = threading.Event()
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


# ─── HTML BUILDER ─────────────────────────────────────────────────────────────
def get_login_html(error=None):
    error_block = ""
    if error:
        error_block = f'<div class="err">{error}</div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:'Inter',sans-serif;background:#17212B;color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center}}
        .card{{background:#232E3C;border-radius:12px;padding:40px 32px;width:100%;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,0.3)}}
        .card h1{{font-size:20px;font-weight:600;color:#2AABEE;margin-bottom:6px;text-align:center}}
        .card p{{font-size:13px;color:#8B9BAA;margin-bottom:24px;text-align:center}}
        input{{width:100%;padding:12px 16px;background:#17212B;border:1px solid #2B3B4A;border-radius:8px;color:#fff;font-size:14px;font-family:inherit;outline:none;transition:border-color .2s;margin-bottom:16px}}
        input:focus{{border-color:#2AABEE}}
        button{{width:100%;padding:12px;background:#2AABEE;border:none;border-radius:8px;color:#fff;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;transition:background .2s}}
        button:hover{{background:#229ED9}}
        .err{{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:13px;text-align:center}}
    </style>
</head>
<body>
    <div class="card">
        <h1>Bot Dashboard</h1>
        <p>Enter password to continue</p>
        {error_block}
        <form method="POST" action="/login">
            <input type="password" name="password" placeholder="Password" autocomplete="off" required>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>'''


def get_dashboard_html():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Inter',sans-serif;background:#0E1621;color:#fff;min-height:100vh}
        ::-webkit-scrollbar{width:5px}
        ::-webkit-scrollbar-thumb{background:#2B3B4A;border-radius:3px}
        .app{display:flex;min-height:100vh}
        .side{width:220px;background:#17212B;border-right:1px solid #232E3C;display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100}
        .side-top{padding:20px;border-bottom:1px solid #232E3C}
        .side-top h2{font-size:15px;font-weight:600;color:#2AABEE}
        .side-top span{font-size:11px;color:#6C7883}
        .nav{flex:1;padding:8px}
        .nav a{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:8px;color:#8B9BAA;text-decoration:none;font-size:13px;font-weight:500;margin-bottom:2px;transition:all .15s;cursor:pointer}
        .nav a:hover{background:#232E3C;color:#fff}
        .nav a.act{background:#2AABEE;color:#fff}
        .side-bot{padding:12px;border-top:1px solid #232E3C}
        .side-bot a{display:block;padding:10px 14px;border-radius:8px;color:#8B9BAA;text-decoration:none;font-size:13px;transition:all .15s}
        .side-bot a:hover{background:rgba(239,68,68,0.1);color:#f87171}
        .main{flex:1;margin-left:220px}
        .hdr{padding:14px 24px;border-bottom:1px solid #232E3C;background:#17212B;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50}
        .hdr h1{font-size:15px;font-weight:600}
        .hdr-r{display:flex;align-items:center;gap:12px}
        .badge{font-size:11px;padding:3px 10px;border-radius:12px;background:rgba(34,197,94,0.1);color:#22C55E;border:1px solid rgba(34,197,94,0.2)}
        .tm{font-size:12px;color:#6C7883}
        .mbtn{display:none;background:none;border:none;color:#fff;font-size:20px;cursor:pointer}
        .sec{display:none;padding:24px;animation:fi .2s ease}
        .sec.act{display:block}
        .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
        .st{background:#17212B;border:1px solid #232E3C;border-radius:10px;padding:18px}
        .st-l{font-size:11px;color:#6C7883;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
        .st-v{font-size:22px;font-weight:700}
        .st-v.sm{font-size:12px;font-weight:500;color:#2AABEE;word-break:break-all;cursor:pointer}
        .grd{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}
        .cd{background:#17212B;border:1px solid #232E3C;border-radius:10px;overflow:hidden}
        .cd-h{padding:12px 16px;border-bottom:1px solid #232E3C;display:flex;align-items:center;justify-content:space-between}
        .cd-h h3{font-size:13px;font-weight:600}
        .cd-b{padding:12px 16px;max-height:340px;overflow-y:auto}
        .cnt{background:#2AABEE;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
        .lg{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid #1E2C3A;font-size:12px}
        .lg:last-child{border-bottom:none}
        .lg-t{padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.3px;flex-shrink:0}
        .lg-t.command{background:rgba(42,171,238,0.12);color:#2AABEE}
        .lg-t.system{background:rgba(34,197,94,0.12);color:#22C55E}
        .lg-t.tunnel{background:rgba(139,92,246,0.12);color:#A78BFA}
        .lg-t.error{background:rgba(239,68,68,0.12);color:#f87171}
        .lg-d{flex:1;color:#8B9BAA;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .lg-tm{color:#4E5D6B;font-size:11px;flex-shrink:0}
        .grp{display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid #1E2C3A}
        .grp:last-child{border-bottom:none}
        .grp-n{font-size:13px;font-weight:600}
        .grp-i{font-size:11px;color:#2AABEE;cursor:pointer;font-family:monospace}
        .grp-i:hover{color:#fff}
        .tw{overflow-x:auto}
        table{width:100%;border-collapse:collapse}
        th{text-align:left;padding:9px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#4E5D6B;font-weight:600;border-bottom:1px solid #232E3C}
        td{padding:10px 12px;font-size:13px;border-bottom:1px solid #1E2C3A}
        td.ck{color:#2AABEE;cursor:pointer;font-family:monospace;font-size:12px}
        td.ck:hover{color:#fff}
        tr:hover{background:rgba(42,171,238,0.03)}
        .em{text-align:center;padding:28px;color:#4E5D6B;font-size:13px}
        .sp{width:24px;height:24px;border:3px solid #232E3C;border-top-color:#2AABEE;border-radius:50%;animation:spin .7s linear infinite;margin:20px auto}
        .tst{position:fixed;bottom:20px;right:20px;background:#2AABEE;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:500;transform:translateY(20px);opacity:0;transition:all .3s;z-index:9999}
        .tst.sh{transform:translateY(0);opacity:1}
        .rbtn{background:rgba(42,171,238,0.1);border:1px solid rgba(42,171,238,0.2);color:#2AABEE;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit;font-weight:500;transition:all .2s}
        .rbtn:hover{background:rgba(42,171,238,0.2)}
        @keyframes fi{from{opacity:0}to{opacity:1}}
        @keyframes spin{to{transform:rotate(360deg)}}
        @media(max-width:768px){
            .side{transform:translateX(-100%);transition:transform .3s}
            .side.open{transform:translateX(0)}
            .main{margin-left:0}
            .mbtn{display:block}
            .sec{padding:16px}
            .stats{grid-template-columns:1fr}
            .grd{grid-template-columns:1fr}
        }
    </style>
</head>
<body>
    <div class="app">
        <aside class="side" id="sb">
            <div class="side-top"><h2>Bot Dashboard</h2><span>Telegram Bot Panel</span></div>
            <nav class="nav">
                <a href="#" class="act" data-s="overview">Overview</a>
                <a href="#" data-s="groups">Groups</a>
                <a href="#" data-s="logs">Logs</a>
            </nav>
            <div class="side-bot"><a href="/logout">Logout</a></div>
        </aside>
        <div class="main">
            <header class="hdr">
                <div style="display:flex;align-items:center;gap:12px">
                    <button class="mbtn" onclick="document.getElementById('sb').classList.toggle('open')">&#9776;</button>
                    <h1 id="ttl">Overview</h1>
                </div>
                <div class="hdr-r"><span class="badge">Online</span><span class="tm" id="clk"></span></div>
            </header>
            <div id="s-overview" class="sec act">
                <div class="stats">
                    <div class="st"><div class="st-l">Groups</div><div class="st-v" id="sg">0</div></div>
                    <div class="st"><div class="st-l">Tunnel URL</div><div class="st-v sm" id="su" onclick="cp(this.textContent)">Loading...</div></div>
                    <div class="st"><div class="st-l">Status</div><div class="st-v" style="color:#22C55E">Active</div></div>
                </div>
                <div class="grd">
                    <div class="cd"><div class="cd-h"><h3>Recent Activity</h3></div><div class="cd-b" id="ra"><div class="sp"></div></div></div>
                    <div class="cd"><div class="cd-h"><h3>Groups</h3></div><div class="cd-b" id="rg"><div class="sp"></div></div></div>
                </div>
            </div>
            <div id="s-groups" class="sec">
                <div class="cd"><div class="cd-h"><h3>All Groups</h3><span class="cnt" id="gc">0</span></div><div class="cd-b" id="ag"><div class="sp"></div></div></div>
            </div>
            <div id="s-logs" class="sec">
                <div class="cd"><div class="cd-h"><h3>Activity Logs</h3><button class="rbtn" onclick="load()">Refresh</button></div><div class="cd-b" id="al"><div class="sp"></div></div></div>
            </div>
        </div>
    </div>
    <div class="tst" id="tst">Copied!</div>
    <script>
        document.querySelectorAll('.nav a').forEach(function(a){
            a.addEventListener('click',function(e){
                e.preventDefault();
                var s=a.dataset.s;
                document.querySelectorAll('.nav a').forEach(function(n){n.classList.remove('act')});
                a.classList.add('act');
                document.querySelectorAll('.sec').forEach(function(x){x.classList.remove('act')});
                document.getElementById('s-'+s).classList.add('act');
                document.getElementById('ttl').textContent=s.charAt(0).toUpperCase()+s.slice(1);
                document.getElementById('sb').classList.remove('open');
            });
        });
        function tick(){var d=new Date();document.getElementById('clk').textContent=d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}
        setInterval(tick,1000);tick();
        function cp(t){navigator.clipboard.writeText(t);var el=document.getElementById('tst');el.classList.add('sh');setTimeout(function(){el.classList.remove('sh')},1500)}
        function lh(l){return '<div class="lg"><span class="lg-t '+l.type.toLowerCase()+'">'+l.type+'</span><span class="lg-d">'+l.details+'</span><span class="lg-tm">'+l.timestamp+'</span></div>'}
        function gh(g){return '<div class="grp"><div><div class="grp-n">'+g.name+'</div><div class="grp-i" onclick="cp(\''+g.id+'\')">'+g.id+'</div></div><span class="grp-d">'+g.joined_at+'</span></div>'}
        async function load(){
            try{
                var r=await fetch('/api/stats');
                if(r.status===401){window.location.href='/login';return}
                var d=await r.json();
                document.getElementById('sg').textContent=d.total_groups;
                document.getElementById('su').textContent=d.tunnel_url||'Not ready';
                document.getElementById('ra').innerHTML=d.logs.length?d.logs.slice(0,8).map(lh).join(''):'<div class="em">No activity</div>';
                document.getElementById('rg').innerHTML=d.groups.length?d.groups.slice(0,5).map(gh).join(''):'<div class="em">No groups</div>';
                document.getElementById('gc').textContent=d.groups.length;
                var ag=document.getElementById('ag');
                if(!d.groups.length){ag.innerHTML='<div class="em">No groups</div>'}
                else{var rows=d.groups.map(function(g){return '<tr><td>'+g.name+'</td><td class="ck" onclick="cp(\''+g.id+'\')">'+g.id+'</td><td>'+g.joined_at+'</td></tr>'}).join('');
                ag.innerHTML='<div class="tw"><table><thead><tr><th>Name</th><th>ID</th><th>Joined</th></tr></thead><tbody>'+rows+'</tbody></table></div>'}
                document.getElementById('al').innerHTML=d.logs.length?d.logs.map(lh).join(''):'<div class="em">No logs</div>';
            }catch(e){console.error(e)}
        }
        load();setInterval(load,10000);
    </script>
</body>
</html>'''


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
    if not session.get("authenticated"):
        return redirect("/login")
    return get_dashboard_html()


@flask_app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == dashboard_password:
            session["authenticated"] = True
            return redirect("/")
        return get_login_html(error="Incorrect Password")
    return get_login_html()


@flask_app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect("/login")


@flask_app.route("/api/stats")
def api_stats():
    if not session.get("authenticated"):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "total_groups": len(active_groups),
        "tunnel_url": tunnel_url,
        "groups": list(active_groups.values()),
        "logs": activity_logs[:50],
    })


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
            f"Password\n"
            f"<code>{dashboard_password}</code>\n\n"
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
    flask_app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False, threaded=True)


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
                f"Password\n"
                f"<code>{dashboard_password}</code>\n\n"
                f"{tunnel_url}"
            )
            await msg.edit_text(text, parse_mode="HTML")
        else:
            await msg.edit_text("Bot is Running...\n\nURL not ready yet. Use /dashboard later..")

        logger.info("Startup message sent to group.")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")


def main():
    global dashboard_password

    print("=" * 50)
    print("TELEGRAM BOT + DASHBOARD STARTING")
    print("=" * 50)

    dashboard_password = generate_password(12)
    logger.info(f"Dashboard Password: {dashboard_password}")

    # Start Flask dashboard FIRST so it's ready when tunnel connects
    logger.info(f"Starting dashboard on port {DASHBOARD_PORT}...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

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
