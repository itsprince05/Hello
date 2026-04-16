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
    ContextTypes,
)
from aiohttp import web

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8616525566:AAFF9H7s0iRacpAMzXZXS3ij3mN8ewJBh6o"
DASHBOARD_PORT = 5050
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
TUNNEL_PROCESS = None
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


# ─── HTML ─────────────────────────────────────────────────────────────────────
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


# ─── CLOUDFLARE TUNNEL (same as GhostCatcher) ────────────────────────────────
CLOUDFLARED_LINUX_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"


def ensure_cloudflared():
    """Download cloudflared binary if not found (Linux only)"""
    if os.path.exists(CLOUDFLARED_PATH):
        if platform.system() != "Windows":
            os.chmod(CLOUDFLARED_PATH, 0o755)
        return True

    if platform.system() == "Windows":
        logger.error("cloudflared.exe not found.")
        return False

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


async def start_cloudflared_tunnel():
    """Start cloudflare tunnel — exact same pattern as GhostCatcher"""
    global TUNNEL_PROCESS, tunnel_url

    # Kill existing tunnel if any
    if TUNNEL_PROCESS:
        try:
            logger.info("Stopping existing tunnel...")
            TUNNEL_PROCESS.terminate()
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to stop tunnel: {e}")

    if not ensure_cloudflared():
        add_log("ERROR", "cloudflared binary not available")
        return

    tunnel_url = None

    try:
        process = await asyncio.create_subprocess_exec(
            CLOUDFLARED_PATH, 'tunnel', '--url', f'http://127.0.0.1:{DASHBOARD_PORT}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        TUNNEL_PROCESS = process
        logger.info("Cloudflared process started")

        state = {'url_sent': False}

        async def check_stream(stream, stream_name):
            global tunnel_url
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='ignore').strip()
                if not decoded_line:
                    continue
                logger.info(f"CLOUDFLARED: {decoded_line}")

                if not state['url_sent'] and '.trycloudflare.com' in decoded_line:
                    match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', decoded_line)
                    if match:
                        tunnel_url = match.group(0)
                        logger.info(f"Tunnel URL: {tunnel_url}")
                        add_log("TUNNEL", f"Tunnel started: {tunnel_url}")
                        state['url_sent'] = True

        asyncio.create_task(check_stream(process.stderr, "STDERR"))
        asyncio.create_task(check_stream(process.stdout, "STDOUT"))
        return process
    except Exception as e:
        logger.error(f"Error starting cloudflared: {e}")
        add_log("ERROR", f"Tunnel failed: {e}")


# ─── AIOHTTP WEB SERVER (same as GhostCatcher) ──────────────────────────────
async def handle_health(request):
    return web.Response(text="OK")


async def handle_index(request):
    if request.cookies.get('auth') != 'true':
        raise web.HTTPFound('/login')
    return web.Response(text=get_dashboard_html(), content_type='text/html')


async def handle_login_page(request):
    return web.Response(text=get_login_html(), content_type='text/html')


async def handle_login_post(request):
    data = await request.post()
    pwd = data.get('password', '')
    if pwd == dashboard_password:
        resp = web.HTTPFound('/')
        resp.set_cookie('auth', 'true', max_age=18000)
        return resp
    return web.Response(text=get_login_html(error="Incorrect Password"), content_type='text/html')


async def handle_logout(request):
    resp = web.HTTPFound('/login')
    resp.del_cookie('auth')
    return resp


async def handle_api_stats(request):
    if request.cookies.get('auth') != 'true':
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({
        "total_groups": len(active_groups),
        "tunnel_url": tunnel_url,
        "groups": list(active_groups.values()),
        "logs": activity_logs[:50],
    })


async def start_web_server():
    """Start aiohttp web server — same approach as GhostCatcher"""
    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_get('/', handle_index)
    app.router.add_get('/login', handle_login_page)
    app.router.add_post('/login', handle_login_post)
    app.router.add_get('/logout', handle_logout)
    app.router.add_get('/api/stats', handle_api_stats)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', DASHBOARD_PORT)
    await site.start()
    logger.info(f"Web server started on http://0.0.0.0:{DASHBOARD_PORT}")
    return site


# ─── BOT HANDLERS ────────────────────────────────────────────────────────────
def is_allowed(chat_id):
    return chat_id == ALLOWED_GROUP_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed(chat.id):
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

    # Restart tunnel
    await start_cloudflared_tunnel()

    # Wait for URL
    for _ in range(30):
        if tunnel_url:
            break
        await asyncio.sleep(1)

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
            await asyncio.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except subprocess.TimeoutExpired:
        await msg.edit_text("Update timed out.")
    except Exception as e:
        logger.error(f"Update failed: {e}")
        await msg.edit_text("Update failed...")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def post_init(app):
    """Runs after bot starts — start web server + tunnel, send msg in background"""
    # Start aiohttp web server
    await start_web_server()

    # Start cloudflare tunnel
    await start_cloudflared_tunnel()

    # Send startup message in background (don't block bot from polling)
    asyncio.create_task(send_startup_message(app))


async def send_startup_message(app):
    """Background task — waits for tunnel URL, sends message"""
    try:
        msg = await app.bot.send_message(
            chat_id=ALLOWED_GROUP_ID,
            text="Bot is Running...",
        )

        # Wait for tunnel URL (up to 30s)
        for _ in range(30):
            if tunnel_url:
                break
            await asyncio.sleep(1)

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

    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("dashboard", dashboard_command))
    bot_app.add_handler(CommandHandler("list", list_command))
    bot_app.add_handler(CommandHandler("update", update_command))

    add_log("SYSTEM", "Bot started successfully")
    logger.info("Bot is Running...")

    bot_app.post_init = post_init

    bot_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

