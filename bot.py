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

SHOWS_FILE = "shows.json"
LOGINS_FILE = "logins.json"

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

def load_logins():
    import os, json
    if os.path.exists(LOGINS_FILE):
        with open(LOGINS_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_logins(data):
    import json
    with open(LOGINS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

logins_list = load_logins()


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def generate_password(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def add_log(event_type, details):
    pass


# ─── HTML BUILDER ─────────────────────────────────────────────────────────────
def get_dashboard_html():
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Outfit', sans-serif; 
            background-color: #f0f2f5; 
            margin: 0; padding: 0; 
            color: #1c1e21; 
            -webkit-user-select: none; user-select: none;
        }
        .action-bar { 
            position: relative; z-index: 100; box-sizing: border-box; height: 48px;
            background: #2481cc; color: white; padding: 0 10px; gap: 10px;
            display: flex; align-items: center; justify-content: space-between;
        }
        .nav-left { display: flex; align-items: center; }
        .navbar-icon { width: 32px; height: 32px; border-radius: 50%; margin-right: 12px; display: flex; align-items: center; justify-content: center; background: white; color: #2481cc; }
        .navbar-icon svg { width: 18px; height: 18px; }
        .navbar-title { font-size: 18px; font-weight: 600; color: white; letter-spacing: 0.5px; }
        
        .container { max-width: 800px; margin: 0 auto; padding: 15px; }

        .card { 
            background: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #e0e0e0; 
            margin-bottom: 10px;
        }
        .card h3 { margin-top: 0; font-size: 16px; color: #1c1e21; margin-bottom: 15px; }
        
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
    
    <!-- LOGIN CONTAINER -->
    <div class="container">
        <!-- SAVED LOGINS -->
        <div id="saved-logins-list" style="margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px;"></div>

        <div class="card">
            <h3 style="margin-top:0; color:#1c1e21; margin-bottom: 10px;">New Login</h3>
            <div style="display:flex; flex-direction:column; gap: 10px; margin-top: 10px;">
                <input type="email" id="login-email" placeholder="Email ID" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <input type="password" id="login-password" placeholder="Password" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none;">
                <button onclick="submitLogin(this)" style="width: 100%; padding: 12px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 15px; cursor: pointer;">Login</button>
                <div id="login-error" style="display:none; color: #fa5252; font-weight: 600; font-size: 14px; text-align: center;">Incorrect Details</div>
                <div id="login-response" style="margin-top: 10px; font-size: 13px; color: #333; word-wrap: break-word; white-space: pre-wrap; background: #f9f9f9; padding: 10px; border-radius: 8px; border: 1px solid #eee; display: none; max-height: 200px; overflow-y: auto;"></div>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">Copied to clipboard!</div>

    <!-- DELETE POPUP -->
    <div id="delete-popup" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:9999; align-items:center; justify-content:center;">
        <div style="background:#fff; padding:20px; border-radius:12px; width:calc(100% - 40px); max-width:320px; box-sizing:border-box;">
            <h3 style="margin-top:0; color:#1c1e21;">Confirm Delete</h3>
            <p style="font-size:14px; color:#666; margin-bottom:15px;">Are you sure you want to delete this?</p>
            <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button onclick="hideDeletePopup()" style="padding:10px 15px; background:#f0f2f5; color:#333; border:none; border-radius:10px; cursor:pointer; font-family:inherit; font-weight:500;">Cancel</button>
                <button id="delete-btn-submit" onclick="confirmDelete()" style="padding:10px 15px; background:#fa5252; color:#fff; border:none; border-radius:10px; cursor:pointer; font-family:inherit; font-weight:500;">Delete</button>
            </div>
        </div>
    </div>

    <script>
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

        async function submitLogin(btn) {
            const email = document.getElementById('login-email').value;
            const password = document.getElementById('login-password').value;
            const responseDiv = document.getElementById('login-response');
            const errDiv = document.getElementById('login-error');
            
            if(!email || !password) {
                alert("Please enter both Email ID and Password.");
                return;
            }
            
            btn.disabled = true;
            btn.textContent = 'Logging in...';
            responseDiv.style.display = 'none';
            responseDiv.textContent = '';
            errDiv.style.display = 'none';
            
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                
                if (data.auth_info && data.user_info) {
                    // Success
                    responseDiv.style.display = 'none';
                    document.getElementById('login-email').value = '';
                    document.getElementById('login-password').value = '';
                    loadLogins();
                } else {
                    // Incorrect Details
                    errDiv.style.display = 'block';
                }
                
            } catch(e) { 
                console.error(e);
                errDiv.style.display = 'block';
            } finally {
                btn.disabled = false;
                btn.textContent = 'Login';
            }
        }

        async function loadLogins() {
            try {
                const res = await fetch('/api/logins');
                const data = await res.json();
                const container = document.getElementById('saved-logins-list');
                
                if (!data.logins || data.logins.length === 0) {
                    container.innerHTML = '';
                    return;
                }
                
                container.innerHTML = data.logins.map(l => {
                    const now = Math.floor(Date.now() / 1000);
                    const isExpired = l.expires_at <= now;
                    return `<div class="card" style="margin-bottom: 0; display: flex; justify-content: space-between; align-items: center; cursor: ${isExpired ? 'default' : 'pointer'}; ${isExpired ? 'opacity: 0.6;' : ''}" ${isExpired ? '' : `onclick="window.location.href='/login/${encodeURIComponent(l.uid)}'"`}>
                        <div>
                            <div style="font-weight: 600; font-size: 15px; color: #1c1e21;">${l.name}</div>
                            <div style="font-size: 13px; margin-top: 5px;" class="countdown-timer" data-expires="${l.expires_at}"></div>
                        </div>
                        <div style="display:flex; justify-content:center; align-items:center; cursor:pointer; width:36px; height:36px; border-radius:50%; background:#fff5f5; color:#fa5252;" onclick="showDeletePopup('${l.uid}', 'login'); event.stopPropagation();">
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </div>
                    </div>`;
                }).join('');
                updateTimers();
            } catch(e) { console.error(e); }
        }

        function updateTimers() {
            const container = document.getElementById('saved-logins-list');
            if (!container) return;
            
            let needsReorder = false;
            document.querySelectorAll('.countdown-timer').forEach(el => {
                const expiresAt = parseInt(el.getAttribute('data-expires'), 10);
                const now = Math.floor(Date.now() / 1000);
                const diff = expiresAt - now;
                
                if (diff <= 0) {
                    if (el.getAttribute('data-is-expired') !== 'true') {
                        el.setAttribute('data-is-expired', 'true');
                        needsReorder = true;
                    }
                    el.textContent = "Login expired...";
                    el.style.color = "#fa5252";
                } else {
                    const hrs = Math.floor(diff / 3600);
                    const mins = Math.floor((diff % 3600) / 60);
                    const secs = diff % 60;
                    let timeStr = '';
                    if (hrs > 0) {
                        timeStr = `${hrs}h ${String(mins).padStart(2, '0')}m ${String(secs).padStart(2, '0')}s`;
                    } else {
                        timeStr = `${mins}m ${String(secs).padStart(2, '0')}s`;
                    }
                    el.innerHTML = `Login expired in - <span style="font-weight: bold; color: #2481cc;">${timeStr}</span>`;
                    el.style.color = "#666";
                }
            });
            
            if (needsReorder) {
                const cards = Array.from(container.children);
                cards.sort((a, b) => {
                    const aTimer = a.querySelector('.countdown-timer');
                    const bTimer = b.querySelector('.countdown-timer');
                    if (!aTimer || !bTimer) return 0;
                    
                    const aExp = parseInt(aTimer.getAttribute('data-expires'), 10);
                    const bExp = parseInt(bTimer.getAttribute('data-expires'), 10);
                    const now = Math.floor(Date.now() / 1000);
                    const aIsExp = aExp <= now;
                    const bIsExp = bExp <= now;
                    
                    if (aIsExp && !bIsExp) return 1;
                    if (!aIsExp && bIsExp) return -1;
                    return aExp - bExp;
                });
                cards.forEach(c => container.appendChild(c));
            }
        }
        
        setInterval(updateTimers, 1000);

        let itemToDeleteId = null;
        let itemToDeleteType = null;
        let deleteTimerInterval = null;

        function showDeletePopup(id, type='show') {
            itemToDeleteId = id;
            itemToDeleteType = type;
            document.getElementById('delete-popup').style.display = 'flex';
            
            const btn = document.getElementById('delete-btn-submit');
            btn.disabled = true;
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            
            if(deleteTimerInterval) clearInterval(deleteTimerInterval);
            let counter = 5;
            btn.textContent = `Delete (${counter})`;
            
            deleteTimerInterval = setInterval(() => {
                counter--;
                if(counter <= 0) {
                    clearInterval(deleteTimerInterval);
                    btn.textContent = 'Delete';
                    btn.disabled = false;
                    btn.style.opacity = '1';
                    btn.style.cursor = 'pointer';
                } else {
                    btn.textContent = `Delete (${counter})`;
                }
            }, 1000);
        }

        function hideDeletePopup() {
            document.getElementById('delete-popup').style.display = 'none';
            itemToDeleteId = null;
            itemToDeleteType = null;
            if(deleteTimerInterval) clearInterval(deleteTimerInterval);
        }

        async function confirmDelete() {
            if(!itemToDeleteId) return;
            
            try {
                let url = itemToDeleteType === 'login' ? `/api/logins/${encodeURIComponent(itemToDeleteId)}` : `/api/items/${encodeURIComponent(itemToDeleteId)}`;
                const res = await fetch(url, { method: 'DELETE' });
                if(res.ok) {
                    hideDeletePopup();
                    if (itemToDeleteType === 'login') {
                        loadLogins();
                    }
                } else {
                    alert('Failed to delete.');
                }
            } catch(e) { console.error(e); }
        }

        loadStats();
        loadLogins();
        setInterval(loadStats, 5000);
    </script>
</body>
</html>'''

    return html


def get_show_detail_html(show):
    import html as html_escape
    s_name = html_escape.escape(show.get("name", "Unknown"))
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ 
            font-family: 'Outfit', sans-serif; 
            background-color: #f0f2f5; 
            margin: 0; padding: 0; 
            color: #1c1e21; 
        }}
        .action-bar {{ 
            position: sticky; top: 0; z-index: 100; box-sizing: border-box; height: 48px;
            background: #2481cc; color: white; padding: 0 10px; gap: 10px;
            display: flex; align-items: center;
        }}
        .back-btn {{ width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; color: white; cursor: pointer; border-radius: 50%; }}
        .back-btn:hover {{ background: rgba(255,255,255,0.2); }}
        .navbar-title {{ font-size: 18px; font-weight: 600; letter-spacing: 0.5px; }}
        
        .tabs {{ 
            display: flex; width: 100%; height: 48px; background-color: #2481cc; align-items: center; 
            position: sticky; top: 48px; z-index: 99;
        }}
        .tab {{ 
            flex: 1; height: 100%; display: flex; align-items: center; justify-content: center;
            font-weight: 500; font-size: 14px; text-transform: none; letter-spacing: 0.5px;
            color: rgba(255,255,255,0.7); cursor: pointer; 
            border-bottom: 3px solid transparent; transition: background 0.2s, color 0.2s; 
        }}
        .tab.active {{ color: #ffffff; border-bottom-color: #ffffff; background-color: rgba(255, 255, 255, 0.15); }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 15px; display: none; height: calc(100vh - 96px); box-sizing: border-box; }}
        .container.active {{ display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        
        .get-wrapper {{
            display: flex; flex-direction: column; align-items: center; text-align: center;
        }}
        .get-btn {{
            padding: 12px 30px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 15px; cursor: pointer;
            display: flex; align-items: center; justify-content: center; min-width: 150px; height: 46px; box-sizing: border-box; margin-top: -50px;
        }}
        @keyframes spin {{
            100% {{ transform: rotate(360deg); }}
        }}
        .lucide-loader {{
            animation: spin 1s linear infinite;
        }}
    </style>
</head>
<body>
    <div class="action-bar">
        <div class="back-btn" onclick="window.history.back()">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-arrow-left"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
        </div>
        <div class="navbar-title">{s_name}</div>
    </div>
    
    <div class="tabs">
        <div class="tab active" onclick="switchTab('unofficial', event)">Unofficial</div>
        <div class="tab" onclick="switchTab('published', event)">Published</div>
    </div>

    <!-- TAB 1: UNOFFICIAL -->
    <div id="unofficial" class="container active">
        <div class="get-wrapper">
            <button class="get-btn" onclick="showLoader(this, 'loader-unofficial')">Get</button>
            <div id="loader-unofficial" style="display:none; color:#2481cc;">
                <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-icon lucide-loader"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>
            </div>
        </div>
    </div>

    <!-- TAB 2: PUBLISHED -->
    <div id="published" class="container">
        <div class="get-wrapper">
            <button class="get-btn" onclick="showLoader(this, 'loader-published')">Get</button>
            <div id="loader-published" style="display:none; color:#2481cc;">
                <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-icon lucide-loader"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>
            </div>
        </div>
    </div>

    <script>
        function switchTab(tabId, event) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.container').forEach(c => c.classList.remove('active'));
            event.currentTarget.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }}

        async function showLoader(btn, loaderId) {{
            btn.style.display = 'none';
            const loaderDiv = document.getElementById(loaderId);
            loaderDiv.style.display = 'block';

            const tab = loaderId.split('-')[1]; // unofficial or published
            const showIdStr = '{html_escape.escape(str(show.get("id", "")))}';
            const showIdEncoded = encodeURIComponent(showIdStr);

            try {{
                const res = await fetch(`/api/items/${{showIdEncoded}}/fetch`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ tab: tab }})
                }});
                const data = await res.json();

                if(!data.success && data.code === 'UNAUTHORIZED') {{
                    loaderDiv.style.display = 'none';
                    const wrapper = btn.closest('.get-wrapper');
                    const errLabel = document.createElement('div');
                    errLabel.textContent = 'Unauthorized Error';
                    errLabel.style.color = '#fa5252';
                    errLabel.style.fontWeight = '600';
                    errLabel.style.fontSize = '16px';
                    wrapper.appendChild(errLabel);
                    return; // DO NOT restore the button
                }}
                
                // Normal success or other errors
                if(data.success) {{
                    alert('Items Fetched! Found Pages: ' + data.pages_fetched);
                }} else {{
                    alert(data.error || 'Failed to fetch items');
                }}
            }} catch(e) {{
                alert('Connection Error!');
                console.error(e);
            }} finally {{
                // As long as it is not strictly unauthorized replacing the UI, restore DOM
                if(!btn.closest('.get-wrapper').querySelector('div:last-child').textContent.includes('Unauthorized')) {{
                    loaderDiv.style.display = 'none';
                    btn.style.display = 'flex';
                }}
            }}
        }}
    </script>
</body>
</html>'''
    return html

def get_login_detail_html(uid, name):
    import html as html_escape
    s_name = html_escape.escape(name)
    uid_esc = html_escape.escape(uid)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Outfit', sans-serif; background-color: #f0f2f5; margin: 0; padding: 0; color: #1c1e21; -webkit-user-select: none; user-select: none; }}
        .action-bar {{ position: sticky; top: 0; z-index: 100; box-sizing: border-box; height: 48px; background: #2481cc; color: white; padding: 0 10px; gap: 10px; display: flex; align-items: center; }}
        .back-btn {{ width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; color: white; cursor: pointer; border-radius: 50%; }}
        .back-btn:hover {{ background: rgba(255,255,255,0.2); }}
        .navbar-title {{ font-size: 18px; font-weight: 600; letter-spacing: 0.5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 15px; }}
        .loader-container {{ display: flex; justify-content: center; align-items: center; height: 60vh; color: #2481cc; }}
        @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
        .lucide-loader {{ animation: spin 1s linear infinite; width: 32px; height: 32px; }}
        
        .item-list {{ display: flex; flex-direction: column; gap: 0; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #ddd; }}
        .item {{ display:flex; gap:0; align-items:flex-start; border-bottom: 1px solid #eee; padding: 0; }}
        .item:last-child {{ border-bottom: none; }}
    </style>
</head>
<body>
    <div class="action-bar">
        <div class="back-btn" onclick="window.history.back()">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-arrow-left"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
        </div>
        <div class="navbar-title">{s_name}</div>
    </div>
    
    <div class="container">
        <div id="loader" class="loader-container">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-icon lucide-loader"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>
        </div>
        <div id="shows-container" class="item-list" style="display:none;"></div>
        <div id="empty-state" style="display:none; justify-content:center; align-items:center; height: 60vh; color: #888; font-size: 15px; font-weight: 500;"></div>
    </div>

    <script>
        async function loadUserShows() {{
            try {{
                const res = await fetch(`/api/logins/{uid_esc}/items`);
                const data = await res.json();
                
                document.getElementById('loader').style.display = 'none';
                
                if(res.ok && data.status === 1 && data.result && data.result.books && data.result.books.length > 0) {{
                    const container = document.getElementById('shows-container');
                    container.style.display = 'flex';
                    container.innerHTML = data.result.books.map(b => `
                        <div class="item" style="cursor:pointer;" onclick="window.location.href='/login/{uid_esc}/show/${{encodeURIComponent(b.show_id)}}?title=${{encodeURIComponent(b.show_title)}}'">
                            <div style="width:80px; height:80px; background:#f0f2f5; flex-shrink:0; display:flex; align-items:center; justify-content:center; overflow:hidden;">
                                ${{b.image_url ? `<img src="${{b.image_url}}" style="width:100%; height:100%; object-fit:cover;">` : '<span style="font-size:26px;">📺</span>'}}
                            </div>
                            <div style="display:flex; flex-direction:column; overflow:hidden; padding: 10px; width: 100%;">
                                <div style="font-weight:600; font-size:15px; color:#1c1e21; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; text-overflow:ellipsis; word-wrap:break-word;">${{b.show_title}}</div>
                            </div>
                        </div>
                    `).join('');
                }} else {{
                    document.getElementById('empty-state').style.display = 'flex';
                    document.getElementById('empty-state').innerHTML = 'No items found...';
                }}
            }} catch(e) {{
                console.error(e);
                document.getElementById('loader').style.display = 'none';
                document.getElementById('empty-state').style.display = 'flex';
                document.getElementById('empty-state').innerHTML = 'No items found...';
            }}
        }}
        
        loadUserShows();
    </script>
</body>
</html>'''
    return html


def get_episode_list_html(uid, show_id, show_title):
    import html as html_escape
    s_title = html_escape.escape(show_title)
    uid_esc = html_escape.escape(uid)
    show_id_esc = html_escape.escape(show_id)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Episodes - {s_title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Outfit', sans-serif; background-color: #f0f2f5; margin: 0; padding: 0; color: #1c1e21; -webkit-user-select: none; user-select: none; }}
        .action-bar {{ position: sticky; top: 0; z-index: 100; box-sizing: border-box; height: 48px; background: #2481cc; color: white; padding: 0 10px; gap: 10px; display: flex; align-items: center; }}
        .back-btn {{ width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; color: white; cursor: pointer; border-radius: 50%; flex-shrink: 0; }}
        .back-btn:hover {{ background: rgba(255,255,255,0.2); }}
        .navbar-title {{ font-size: 18px; font-weight: 600; letter-spacing: 0.5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 15px; }}
        .loader-container {{ display: flex; justify-content: center; align-items: center; height: 60vh; color: #2481cc; }}
        @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
        .lucide-loader {{ animation: spin 1s linear infinite; width: 32px; height: 32px; }}
        
        .episode-list {{ display: flex; flex-direction: column; gap: 0; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #ddd; }}
        .episode-item {{ display: flex; flex-direction: column; border-bottom: 1px solid #eee; padding: 12px 15px; }}
        .episode-item:last-child {{ border-bottom: none; }}
        .ep-title {{ font-weight: 600; font-size: 14px; color: #1c1e21; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-wrap: break-word; }}
        .ep-status {{ font-size: 12px; color: #999; margin-top: 4px; }}
        .ep-actions {{ display: flex; gap: 8px; margin-top: 10px; }}
        .ep-btn {{ display: flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; font-family: inherit; }}
        .ep-btn svg {{ width: 16px; height: 16px; }}
        .ep-btn.script {{ background: #eef5fb; color: #2481cc; }}
        .ep-btn.script:hover {{ background: #dbeaf7; }}
        .ep-btn.audio {{ background: #e6fcf5; color: #0ca678; }}
        .ep-btn.audio:hover {{ background: #d3f9eb; }}
        .ep-btn.audio.disabled {{ background: #f0f2f5; color: #bbb; cursor: not-allowed; pointer-events: none; }}
        
        .load-more-btn {{ display: flex; align-items: center; justify-content: center; padding: 12px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer; width: 100%; margin-top: 15px; font-family: inherit; }}
        .load-more-btn:disabled {{ background: #ccc; cursor: not-allowed; }}
    </style>
</head>
<body>
    <div class="action-bar">
        <div class="back-btn" onclick="window.history.back()">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-arrow-left"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
        </div>
        <div class="navbar-title">{s_title}</div>
    </div>
    
    <div class="container">
        <div id="loader" class="loader-container">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-icon lucide-loader"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>
        </div>
        <div id="episodes-container" class="episode-list" style="display:none;"></div>
        <button id="load-more" class="load-more-btn" style="display:none;" onclick="loadMore()">Load More</button>
        <div id="empty-state" style="display:none; justify-content:center; align-items:center; height: 60vh; color: #888; font-size: 15px; font-weight: 500;"></div>
    </div>

    <script>
        let nextUrl = null;
        let isFirstLoad = true;
        
        function downloadScript(fileUrl, title) {{
            if (!fileUrl) return;
            const a = document.createElement('a');
            a.href = fileUrl;
            a.download = title + '.txt';
            a.target = '_blank';
            a.click();
        }}
        
        function downloadAudio(mediaUrl, title) {{
            if (!mediaUrl) return;
            const a = document.createElement('a');
            a.href = mediaUrl;
            a.download = title + '.mp3';
            a.target = '_blank';
            a.click();
        }}
        
        function renderEpisode(ep) {{
            const ch = ep.chapter_details || {{}};
            const title = ch.chapter_title || 'Untitled';
            const fileUrl = ch.file_url || '';
            const mediaUrl = ch.media_url || '';
            const audioAvail = ep.audio_available === true;
            const audioStatus = ch.audio_status || '';
            
            let statusText = '';
            if (!audioAvail) {{
                statusText = 'Audio Unavailable';
            }} else {{
                statusText = audioStatus || 'Available';
            }}
            
            const audioBtnClass = audioAvail ? 'ep-btn audio' : 'ep-btn audio disabled';
            const audioOnclick = audioAvail && mediaUrl ? `onclick="downloadAudio('${{mediaUrl.replace(/'/g, "\\'")}}', '${{title.replace(/'/g, "\\'")}}')"` : '';
            
            return `<div class="episode-item">
                <div class="ep-title">${{title}}</div>
                <div class="ep-status">${{statusText}}</div>
                <div class="ep-actions">
                    <button class="ep-btn script" onclick="downloadScript('${{fileUrl.replace(/'/g, "\\'")}}', '${{title.replace(/'/g, "\\\'")}}')"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-download"><path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/></svg> Script</button>
                    <button class="${{audioBtnClass}}" ${{audioOnclick}}><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-download"><path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/></svg> Audio</button>
                </div>
            </div>`;
        }}
        
        async function loadEpisodes(url) {{
            const loadMoreBtn = document.getElementById('load-more');
            
            if (!isFirstLoad) {{
                loadMoreBtn.disabled = true;
                loadMoreBtn.textContent = 'Loading...';
            }}
            
            try {{
                const fetchUrl = url || `/api/logins/{uid_esc}/shows/{show_id_esc}/episodes`;
                const res = await fetch(fetchUrl);
                const data = await res.json();
                
                if (isFirstLoad) {{
                    document.getElementById('loader').style.display = 'none';
                }}
                
                if (data.status === 1 && data.result && data.result.episodes && data.result.episodes.length > 0) {{
                    const container = document.getElementById('episodes-container');
                    container.style.display = 'flex';
                    
                    const html = data.result.episodes.map(ep => renderEpisode(ep)).join('');
                    container.innerHTML += html;
                    
                    nextUrl = data.result.next_url || null;
                    if (nextUrl) {{
                        loadMoreBtn.style.display = 'flex';
                        loadMoreBtn.disabled = false;
                        loadMoreBtn.textContent = 'Load More';
                    }} else {{
                        loadMoreBtn.style.display = 'none';
                    }}
                }} else if (isFirstLoad) {{
                    document.getElementById('empty-state').style.display = 'flex';
                    document.getElementById('empty-state').innerHTML = 'No episodes found...';
                }} else {{
                    loadMoreBtn.style.display = 'none';
                }}
                
                isFirstLoad = false;
            }} catch(e) {{
                console.error(e);
                if (isFirstLoad) {{
                    document.getElementById('loader').style.display = 'none';
                    document.getElementById('empty-state').style.display = 'flex';
                    document.getElementById('empty-state').innerHTML = 'Failed to load episodes...';
                }} else {{
                    loadMoreBtn.disabled = false;
                    loadMoreBtn.textContent = 'Retry';
                }}
                isFirstLoad = false;
            }}
        }}
        
        function loadMore() {{
            if (nextUrl) {{
                const proxyUrl = `/api/logins/{uid_esc}/shows/{show_id_esc}/episodes?next_url=` + encodeURIComponent(nextUrl);
                loadEpisodes(proxyUrl);
            }}
        }}
        
        loadEpisodes();
    </script>
</body>
</html>'''
    return html


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


@flask_app.route("/item/<path:show_id>")
def show_detail(show_id):
    show = next((s for s in shows_list if str(s.get("id")) == show_id), None)
    if not show:
        return "Show not found", 404
        
    return get_show_detail_html(show)


@flask_app.route("/api/stats")
def api_stats():
    return jsonify({
        "total_groups": len(active_groups),
        "tunnel_url": tunnel_url,
        "groups": list(active_groups.values()),
        "logs": activity_logs[:50],
    })


@flask_app.route("/api/items", methods=["GET", "POST"])
def api_shows():
    if request.method == "POST":
        data = request.json
        shows_list.append(data)
        save_shows(shows_list)
        return jsonify({"status": "success"})
        
    safe_shows = [{"id": s.get("id"), "name": s.get("name"), "image": s.get("image")} for s in shows_list]
    return jsonify({"shows": safe_shows})


@flask_app.route("/api/login", methods=["POST"])
def api_login():
    import urllib.request, urllib.error, json
    data = request.json
    email = data.get("email")
    password = data.get("password")
    
    url = "https://iam-cms.pocketfm.com/v1/studio/auth/users/login/email"
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,hi;q=0.8",
        "app-name": "pocket_studio",
        "content-type": "application/json",
        "origin": "https://partner.pocketfm.com",
        "platform": "web",
        "priority": "u=1, i",
        "referer": "https://partner.pocketfm.com/",
        "sec-ch-ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
    }
    
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            if "auth_info" in res_data and "user_info" in res_data:
                import time
                new_login = {
                    "uid": res_data.get("user_info", {}).get("uid", ""),
                    "name": res_data.get("user_info", {}).get("full_name", ""),
                    "access_token": res_data.get("auth_info", {}).get("access_token", ""),
                    "expires_at": int(time.time()) + 7200  # 2 hours
                }
                global logins_list
                logins_list = [l for l in logins_list if l.get("uid") != new_login["uid"]]
                logins_list.append(new_login)
                save_logins(logins_list)
            return jsonify(res_data)
    except urllib.error.HTTPError as e:
        try:
            return jsonify(json.loads(e.read().decode())), e.code
        except:
            return jsonify({"error": str(e)}), e.code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/logins", methods=["GET"])
def api_get_logins():
    import time
    now = int(time.time())
    active = [l for l in logins_list if l.get("expires_at", 0) > now]
    expired = [l for l in logins_list if l.get("expires_at", 0) <= now]
    active.sort(key=lambda x: x.get("expires_at", 0))
    expired.sort(key=lambda x: x.get("expires_at", 0))
    sorted_logins = active + expired
    safe_logins = [{"uid": l.get("uid"), "name": l.get("name"), "expires_at": l.get("expires_at")} for l in sorted_logins]
    return jsonify({"logins": safe_logins})


@flask_app.route("/api/logins/<path:uid>/items", methods=["GET"])
def api_logins_shows(uid):
    import urllib.request, urllib.error, json
    
    login = next((l for l in logins_list if str(l.get("uid")) == uid), None)
    if not login:
        return jsonify({"status": 0, "message": "User not found or session expired"}), 404
        
    target_url = "https://api.studio.pocketfm.com/v2/content_api/book.published_shows?is_novel=0"
    target_headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "app-client": "consumer-web",
        "app-version": "180",
        "auth-token": "web-auth",
        "authorization": login.get("access_token", ""),
        "origin": "https://partner.pocketfm.com",
        "priority": "u=1, i",
        "referer": "https://partner.pocketfm.com/",
        "sec-ch-ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "source": "studio",
        "uid": login.get("uid", ""),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
        "web-platform": "studio"
    }
    
    proxy_url = "https://curl-proxy.bruceliu-dev.workers.dev/"
    proxy_payload = json.dumps({
        "url": target_url,
        "method": "GET",
        "headers": target_headers
    }).encode("utf-8")
    
    proxy_headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://curlonline.com",
        "referer": "https://curlonline.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
    }
    
    curl_cmd = f"curl '{target_url}'"
    for k, v in target_headers.items():
        curl_cmd += f" \\\n  -H '{k}: {v}'"
    
    try:
        req = urllib.request.Request(proxy_url, data=proxy_payload, headers=proxy_headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            proxy_resp = json.loads(response.read().decode())
        
        resp_body = proxy_resp.get("body", "")
        resp_status = proxy_resp.get("status", 0)
        
        try:
            res_json = json.loads(resp_body)
            if res_json.get("status") == 1 and "result" in res_json and "books" in res_json["result"]:
                filtered_books = []
                for book in res_json["result"]["books"]:
                    filtered_books.append({
                        "show_id": book.get("show_id"),
                        "show_title": book.get("show_title"),
                        "image_url": book.get("image_url")
                    })
                res_json["result"]["books"] = filtered_books
        except:
            res_json = {"status": 0, "message": f"Invalid JSON from API. Proxy status: {resp_status}"}
            
        return jsonify(res_json)
    except urllib.error.HTTPError as e:
        return jsonify({"status": 0, "message": f"Proxy error: {e.code}"}), 502
    except Exception as e:
        return jsonify({"status": 0, "message": str(e)}), 500


@flask_app.route("/login/<path:uid>")
def login_page(uid):
    login = next((l for l in logins_list if str(l.get("uid")) == uid), None)
    if not login:
        return "Login not found", 404
    return get_login_detail_html(uid, login.get("name", "Unknown"))


@flask_app.route("/login/<path:uid>/show/<path:show_id>")
def login_show_episodes_page(uid, show_id):
    login = next((l for l in logins_list if str(l.get("uid")) == uid), None)
    if not login:
        return "Login not found", 404
    show_title = request.args.get("title", "Episodes")
    return get_episode_list_html(uid, show_id, show_title)


@flask_app.route("/api/logins/<path:uid>/shows/<path:show_id>/episodes", methods=["GET"])
def api_login_show_episodes(uid, show_id):
    import urllib.request, urllib.error, json
    
    login = next((l for l in logins_list if str(l.get("uid")) == uid), None)
    if not login:
        return jsonify({"status": 0, "message": "User not found or session expired"}), 404
    
    # Check if next_url is passed for pagination
    next_url_param = request.args.get("next_url", None)
    
    if next_url_param:
        target_url = next_url_param
    else:
        target_url = f"https://api.studio.pocketfm.com/v2/content_api/book.show_episodes?is_novel=0&page_no=1&paginate_chapters=true&show_id={show_id}&view=dashboard"
    
    target_headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "app-client": "consumer-web",
        "app-version": "180",
        "auth-token": "web-auth",
        "authorization": login.get("access_token", ""),
        "origin": "https://partner.pocketfm.com",
        "priority": "u=1, i",
        "referer": "https://partner.pocketfm.com/",
        "sec-ch-ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "source": "studio",
        "uid": login.get("uid", ""),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
        "web-platform": "studio"
    }
    
    proxy_url = "https://curl-proxy.bruceliu-dev.workers.dev/"
    proxy_payload = json.dumps({
        "url": target_url,
        "method": "GET",
        "headers": target_headers
    }).encode("utf-8")
    
    proxy_headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://curlonline.com",
        "referer": "https://curlonline.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
    }
    
    try:
        req = urllib.request.Request(proxy_url, data=proxy_payload, headers=proxy_headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            proxy_resp = json.loads(response.read().decode())
        
        resp_body = proxy_resp.get("body", "")
        
        try:
            res_json = json.loads(resp_body)
        except:
            res_json = {"status": 0, "message": "Invalid JSON from API"}
            
        return jsonify(res_json)
    except urllib.error.HTTPError as e:
        return jsonify({"status": 0, "message": f"Proxy error: {e.code}"}), 502
    except Exception as e:
        return jsonify({"status": 0, "message": str(e)}), 500

@flask_app.route("/api/logins/<path:uid>", methods=["DELETE"])
def api_logins_delete(uid):
    global logins_list
    logins_list = [l for l in logins_list if str(l.get("uid")) != uid]
    save_logins(logins_list)
    return jsonify({"status": "success"})


@flask_app.route("/api/items/<path:show_id>", methods=["DELETE"])
def api_shows_delete(show_id):
    global shows_list
    shows_list = [s for s in shows_list if str(s.get("id")) != show_id]
    save_shows(shows_list)
    return jsonify({"status": "success"})


@flask_app.route("/api/items/<path:show_id>/fetch", methods=["POST"])
def api_shows_fetch(show_id):
    import urllib.request, urllib.error, json
    global shows_list
    
    tab_type = request.json.get("tab", "unofficial")
    show = next((s for s in shows_list if str(s.get("id")) == show_id), None)
    if not show:
        return jsonify({"success": False, "error": "Show not found"}), 404
        
    rj_uid = show.get("rj_uid")
    refresh_token_val = show.get("rj_token")
    
    if not rj_uid or not refresh_token_val:
        return jsonify({"success": False, "error": "Missing UID or Refresh Token"}), 400

    def refresh_pocket_token(refresh_token):
        url = "https://iam-cms.pocketfm.com/v1/auth/refresh"
        headers = {
            "accept": "application/json, text/plain, */*",
            "app-name": "pocket_studio",
            "content-type": "application/json",
            "origin": "https://partner.pocketfm.com",
            "platform": "web",
            "priority": "u=1, i",
            "referer": "https://partner.pocketfm.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
        }
        data = json.dumps({"refresh_token": refresh_token}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except:
                return {"code": "UNAUTHORIZED", "error": str(e)}
        except Exception as e:
            return {"code": "ERROR", "error": str(e)}

    def get_pocket_episodes(acc_token, page_no):
        url = f"https://api.studio.pocketfm.com/v2/content_api/book.show_episodes?is_novel=0&show_id={show_id}&view=dashboard"
        if tab_type == "unofficial":
            url += "&paginate_chapters=true"
        url += f"&page_no={page_no}"
            
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "app-client": "consumer-web",
            "app-version": "180",
            "auth-token": "web-auth",
            "authorization": acc_token,
            "origin": "https://partner.pocketfm.com",
            "priority": "u=1, i",
            "referer": "https://partner.pocketfm.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "source": "studio",
            "uid": rj_uid,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "web-platform": "studio"
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except:
                return {"status": 0, "error": str(e)}
        except Exception as e:
            return {"status": 0, "error": str(e)}

    # Check and generate token initially
    access_token = show.get("access_token")
    if not access_token:
        res = refresh_pocket_token(refresh_token_val)
        if res.get("access_token"):
            show["access_token"] = res["access_token"]
            show["rj_token"] = res.get("refresh_token", refresh_token_val)
            save_shows(shows_list)
            access_token = show["access_token"]
        else:
            if res.get("code") == "UNAUTHORIZED":
                return jsonify({"success": False, "code": "UNAUTHORIZED"}), 200
            return jsonify({"success": False, "error": "Token Refresh Failed", "details": res}), 200

    page = 1
    resp = get_pocket_episodes(access_token, page)
    
    # Checking dynamic token expiration based on provided structures
    if resp.get("status") == 0 and resp.get("error") in ["Invalid token", "Token expired"]:
        # Auto-Refresh requested...
        r_res = refresh_pocket_token(show.get("rj_token"))
        if r_res.get("access_token"):
            show["access_token"] = r_res["access_token"]
            show["rj_token"] = r_res.get("refresh_token", show.get("rj_token"))
            save_shows(shows_list)
            access_token = show["access_token"]
            
            # Fetch again
            resp = get_pocket_episodes(access_token, page)
            if resp.get("status") == 0 and resp.get("error") in ["Invalid token", "Token expired"]:
                return jsonify({"success": False, "error": resp.get("error")}), 200
        else:
            if r_res.get("code") == "UNAUTHORIZED":
                return jsonify({"success": False, "code": "UNAUTHORIZED"}), 200
            return jsonify({"success": False, "error": "Token Refresh Retry Failed"}), 200
            
    # Other explicit server errors
    if resp.get("status") == 0 and "error" in resp:
        return jsonify({"success": False, "error": resp.get("error")}), 200
        
    return jsonify({"success": True, "pages_fetched": 1, "data": [resp]})


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
        f"Group Name: {group_name}\n"
        f"Group ID: <code>{group_id}</code>"
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
