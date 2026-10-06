#!/usr/bin/env python3
"""
fleet_receiver.py -- telemetry receiver + dashboard for the Boboe fleet.

Your Mac side of the bridge. Each Boboe agent pushes a JSON telemetry payload
every ~30s over your Tailscale network; this script stores it and serves a
live dashboard. Click any agent card for the read-only detail view
(processes, files, cron history, activity timeline).

Setup:
  1. Edit BIND_IP below to your Mac's Tailscale IP (Tailscale menu bar icon,
     or run `tailscale ip -4` in Terminal).
  2. Edit TOKEN below (generate with: openssl rand -hex 32). Keep it private.
  3. Run:  python3 fleet_receiver.py
  4. Open:  http://<your-tailscale-ip>:8787

Payload schema each agent sends (for reference):
  {"agent": "boboe2", "ts": 1728..., "boot_id": "...",
   "cpu": {"count": 2, "load1": 0.2, "load5": 0.18, "load15": 0.15},
   "mem": {"top": [["hatch", 412], ...], "all": [...], "unit": "MB"},
   "disk": {"total_gb": 100, "used_gb": 0.13, "path": "/home/hatch"},
   "uptime_s": 9690,
   "files": {"count": 42, "mb": 3.1,
             "entries": [["workspace/report.md", 12.3], ...]},
   "status": {"state": "working", "task": "...", "since": 1728...},
   "activity": {"current": "Editing code",
                "entries": [{"timestamp":..., "activity_type":...,
                             "status":..., "title":..., "status_title":...,
                             "subtitle":...}]},
   "observed": {"working": true, "signals": ["browser running"]},
   "crons": [{"id": "slack-watch-boboe2", "last_run": "...", "status": "ok"}]}
"""

import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------- config: edit these ----------------
BIND_IP = os.environ.get("FLEET_BIND_IP", "100.97.2.40")  # Mac's Tailscale IP
PORT = 8787
# Shared secret the agents use to authenticate. NEVER commit this to git.
# Put it in a file named "token.txt" next to this script, or set FLEET_TOKEN.
def read_token():
    env = os.environ.get("FLEET_TOKEN")
    if env and env.strip():
        return env.strip()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "token.txt")) as f:
        return f.read().strip()

TOKEN = read_token()
# ----------------------------------------------------

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fleet_telemetry.json")
STALE_AFTER = 120   # seconds without a payload before an agent shows stale
MAX_HISTORY = 200   # heartbeats kept per agent
MAX_CRON_HISTORY = 100

store = {}  # agent -> {"latest","history","cron_history","first_seen","last_seen"}
bursts = {}  # agent -> epoch until which fast pushes were requested (live tail)
lock = threading.Lock()


def load():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                for agent, rec in json.load(f).items():
                    rec.setdefault("cron_history", [])
                    store[agent] = rec
        except Exception as e:
            print("note: could not load %s (%s), starting fresh" % (DATA_FILE, e))


def save():
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.replace(tmp, DATA_FILE)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path == "/api/burst":
            return self.do_POST_burst()
        if self.path != "/ingest":
            return self._send(404, '{"error":"not found"}')
        if not hmac.compare_digest(self.headers.get("X-Agent-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        try:
            payload = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))))
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        agent = str(payload.get("agent", "unknown"))
        now = time.time()
        with lock:
            rec = store.get(agent, {"history": [], "cron_history": [],
                                    "first_seen": now})
            rec["latest"] = payload
            rec["last_seen"] = now
            st = payload.get("status", {})
            act = payload.get("activity", {})
            rec["history"].append({"ts": now,
                                   "state": st.get("state"),
                                   "task": st.get("task"),
                                   "app": act.get("current"),
                                   "obs": (payload.get("observed", {})
                                           .get("working"))})
            rec["history"] = rec["history"][-MAX_HISTORY:]
            crons = payload.get("crons", [])
            last_c = (rec["cron_history"][-1]["crons"]
                      if rec["cron_history"] else None)
            if crons != last_c:
                rec["cron_history"].append({"ts": now, "crons": crons})
                rec["cron_history"] = rec["cron_history"][-MAX_CRON_HISTORY:]
            store[agent] = rec
            save()
        # live tail: if Jack asked for faster pushes from this agent, tell it
        # via the ingest response (the only channel the agent listens on).
        # The agent enforces its own caps (>=2s interval, <=5min duration).
        cmd = {}
        now2 = time.time()
        with lock:
            until = bursts.get(agent, 0)
            if until > now2:
                cmd = {"burst": True, "interval": 2, "until": until}
        self._send(200, json.dumps({"ok": True, "cmd": cmd}))

    def do_POST_burst(self):
        if not hmac.compare_digest(self.headers.get("X-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))))
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        agent = str(body.get("agent", ""))
        try:
            duration = max(0, min(300, int(body.get("duration", 120))))
        except (TypeError, ValueError):
            return self._send(400, '{"error":"bad duration"}')
        with lock:
            if duration > 0:
                bursts[agent] = time.time() + duration
            else:
                bursts.pop(agent, None)
        self._send(200, json.dumps({"ok": True,
                                    "burst_until": bursts.get(agent, 0)}))

    def do_GET(self):
        if self.path == "/api/agents":
            now = time.time()
            with lock:
                out = {a: {"latest": r["latest"],
                           "last_seen": r["last_seen"],
                           "first_seen": r.get("first_seen"),
                           "burst_until": bursts.get(a, 0),
                           "history": r.get("history", [])[-40:],
                           "cron_history": r.get("cron_history", [])[-50:]}
                       for a, r in store.items()}
            return self._send(200, json.dumps(out))
        if self.path in ("/", "/index.html"):
            return self._send(200,
                              DASHBOARD_HTML.replace("%%TOKEN%%", TOKEN),
                              "text/html")
        return self._send(404, "not found")


DASHBOARD_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Boboe Fleet</title>
<style>
body{font-family:-apple-system,Helvetica,Arial,sans-serif;background:#101418;color:#e8ecef;margin:0;padding:24px}
h1{font-size:22px;margin:0 0 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}
.card{background:#1a2027;border:1px solid #2a323b;border-radius:12px;padding:16px;cursor:pointer;transition:border-color .15s}
.card:hover{border-color:#4a5563}
.card h2{margin:0 0 10px;font-size:17px}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-left:8px}
.working{background:#123f2a;color:#4ade80}
.idle{background:#2a323b;color:#9aa4af}
.stale{background:#3f1d1d;color:#f87171}
.live{background:#4a1d1d;color:#ff6b6b;animation:pulse 1.6s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
.tailbtn{background:#243044;border:1px solid #37455a;color:#dbe4ee;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px;margin-left:8px}
.tailbtn:hover{background:#2e3d52}
.tailbtn.stop{background:#3a2222;border-color:#5a3535}
.row{display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:3px 0;color:#c6cdd4}
.row b{color:#e8ecef;font-weight:600;text-align:right}
.mut{color:#7d8892;font-size:12px;margin-top:8px}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:flex-start;justify-content:center;padding:32px 16px;z-index:10;overflow:auto}
.modal{background:#161c22;border:1px solid #2a323b;border-radius:14px;max-width:860px;width:100%;padding:24px;max-height:calc(100vh - 64px);overflow:auto}
.modal h2{margin:0 0 4px;font-size:20px}
.modal h3{font-size:14px;color:#9aa4af;margin:20px 0 8px;text-transform:uppercase;letter-spacing:.06em}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#7d8892;font-weight:600;padding:4px 8px;border-bottom:1px solid #2a323b}
td{padding:4px 8px;border-bottom:1px solid #1e242b;color:#c6cdd4}
.close{float:right;background:#2a323b;border:0;color:#e8ecef;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px}
.search{width:100%;box-sizing:border-box;background:#101418;border:1px solid #2a323b;color:#e8ecef;border-radius:8px;padding:8px 10px;font-size:13px;margin-bottom:8px}
.tl{font-size:12px;color:#9aa4af}
.tl div{padding:3px 0;border-bottom:1px dotted #232a32}
.src{font-size:11px;color:#5d6771}
</style></head><body>
<h1>Boboe Fleet <span id="upd" class="mut"></span></h1>
<div class="grid" id="grid"></div>
<div id="modal"></div>
<script>
const TOKEN="%%TOKEN%%";
let CACHE={};
let DETAIL_AGENT=null, detailTimer=null;
async function tick(){
  try{
    CACHE = await (await fetch('/api/agents')).json();
    const names = Object.keys(CACHE).sort();
    document.getElementById('upd').textContent =
      'updated ' + new Date().toLocaleTimeString() + ' · ' + names.length + ' agent(s) · click a card for details';
    document.getElementById('grid').innerHTML =
      names.map(n => card(n, CACHE[n])).join('') || '<p class="mut">No agents reporting yet.</p>';
  }catch(e){ document.getElementById('upd').textContent = 'receiver unreachable'; }
}
function ago(ts){ const s=Math.max(0,Math.floor(Date.now()/1000-ts));
  if(s<60) return s+'s ago'; const m=Math.floor(s/60);
  if(m<60) return m+'m ago'; return Math.floor(m/60)+'h ago'; }
function headline(p){
  const app=(p.activity||{}).current, self=(p.status||{}).task;
  if(app) return app;
  if(self) return self;
  return '—';
}
function isWorking(n,a){
  const p=a.latest||{};
  if((Date.now()/1000-a.last_seen)>120) return 'stale';
  if((p.activity||{}).current) return 'working';
  if((p.status||{}).state==='working') return 'working';
  if((p.observed||{}).working) return 'working';
  return 'idle';
}
function card(n,a){
  const p=a.latest||{}, st=isWorking(n,a),
        cpu=p.cpu||{}, d=p.disk||{}, files=p.files||{},
        mem=((p.mem||{}).top||[]).slice(0,3).map(m=>m[0]+' '+m[1]+'MB').join(', '),
        obs=(p.observed||{}).signals||[],
        live=(a.burst_until||0) > Date.now()/1000;
  return `<div class="card" onclick="openDetail('${n}')">
  <h2>${n}<span class="pill ${st}">${st}</span>${live?'<span class="pill live">live</span>':''}</h2>
  <div class="row"><span>status</span><b>${headline(p)}</b></div>
  <div class="row"><span>last seen</span><b>${ago(a.last_seen)}</b></div>
  <div class="row"><span>load (1m)</span><b>${cpu.load1??'—'}</b></div>
  <div class="row"><span>top procs</span><b>${mem||'—'}</b></div>
  <div class="row"><span>disk</span><b>${d.used_gb??'—'} / ${d.total_gb??'—'} GB</b></div>
  <div class="row"><span>files</span><b>${files.count??'—'} files · ${files.mb??'—'} MB</b></div>
  ${obs.length?`<div class="mut">signals: ${obs.join(' · ')}</div>`:''}
  </div>`;
}
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function openDetail(n){
  DETAIL_AGENT=n;
  renderDetail();
  if(detailTimer) clearInterval(detailTimer);
  detailTimer=setInterval(()=>{ if(DETAIL_AGENT) renderDetail(true); }, 2000);
}
async function renderDetail(preserve){
  const n=DETAIL_AGENT; if(!n) return;
  let filt='', sc=0;
  if(preserve){
    const inp=document.querySelector('.modal .search'); if(inp) filt=inp.value;
    const m=document.querySelector('.modal'); if(m) sc=m.scrollTop;
  }
  try{ CACHE = await (await fetch('/api/agents')).json(); }catch(e){}
  const a=CACHE[n]; if(!a){ closeDetail(); return; }
  const live=(a.burst_until||0) > Date.now()/1000,
        remain=live?Math.max(0,Math.ceil(a.burst_until-Date.now()/1000)):0;
  buildModal(n,a,live,remain);
  if(preserve){
    const inp=document.querySelector('.modal .search');
    if(inp){ inp.value=filt; inp.dispatchEvent(new Event('input')); }
    const m=document.querySelector('.modal'); if(m) m.scrollTop=sc;
  }
}
async function startTail(n){
  await fetch('/api/burst',{method:'POST',
    headers:{'Content-Type':'application/json','X-Token':TOKEN},
    body:JSON.stringify({agent:n,duration:120})});
  renderDetail();
}
async function stopTail(n){
  await fetch('/api/burst',{method:'POST',
    headers:{'Content-Type':'application/json','X-Token':TOKEN},
    body:JSON.stringify({agent:n,duration:0})});
  renderDetail();
}
function buildModal(n,a,live,remain){
  const p=a.latest||{}, act=p.activity||{}, obs=p.observed||{},
        files=p.files||{}, mem=p.mem||{};
  const actRows=(act.entries||[]).map(e=>
    `<tr><td>${esc(e.status_title||e.title)}</td><td>${e.status}</td><td>${e.activity_type||''}</td><td>${ago(Date.parse(e.timestamp)/1000)}</td></tr>`).join('');
  const tl=(a.history||[]).slice().reverse().map(h=>
    `<div>${new Date(h.ts*1000).toLocaleTimeString()} — ${esc(h.app||h.task||h.state||'—')}${h.obs?' <span class="src">(observed working)</span>':''}</div>`).join('');
  const procs=(mem.all||mem.top||[]).map(m=>`<tr><td>${esc(m[0])}</td><td>${m[1]} MB</td></tr>`).join('');
  const fentries=(files.entries||[]);
  const cronH=(a.cron_history||[]).slice().reverse().map(c=>
    `<div>${new Date(c.ts*1000).toLocaleString()} — ${(c.crons||[]).map(x=>`${esc(x.id)}: ${x.status}`).join(', ')||'no crons'}</div>`).join('') || '<div class="mut">no cron data yet</div>';
  document.getElementById('modal').innerHTML = `<div class="modal-bg" onclick="if(event.target===this)closeDetail()">
  <div class="modal">
    <button class="close" onclick="closeDetail()">Close</button>
    <h2>${n}${live?`<span class="pill live">live · ${Math.floor(remain/60)}:${String(remain%60).padStart(2,'0')}</span>`:''}
      ${live
        ? `<button class="tailbtn stop" onclick="stopTail('${n}')">Stop live tail</button>`
        : `<button class="tailbtn" onclick="startTail('${n}')">▶ Live tail</button>`}</h2>
    <div class="mut">first seen ${a.first_seen?new Date(a.first_seen*1000).toLocaleString():'—'} · boot ${esc(String(p.boot_id||'').slice(0,8))}${p.vm_replaced?' · VM was replaced':''} · uptime ${p.uptime_s!=null?Math.floor(p.uptime_s/3600)+'h '+Math.floor(p.uptime_s%3600/60)+'m':'—'}</div>
    <h3>Live status</h3>
    <div class="row"><span>app status</span><b>${esc(act.current||'—')}</b></div>
    <div class="row"><span>self-reported</span><b>${esc((p.status||{}).task||(p.status||{}).state||'—')}</b></div>
    <div class="row"><span>observed</span><b>${obs.working?'working':'idle'}${obs.signals&&obs.signals.length?' ('+esc(obs.signals.join('; '))+')':''}</b></div>
    <h3>Recent activity (app feed)</h3>
    <table><tr><th>Activity</th><th>Status</th><th>Type</th><th>When</th></tr>${actRows||'<tr><td colspan=4 class="mut">none</td></tr>'}</table>
    <h3>Status timeline</h3><div class="tl">${tl||'<span class="mut">none yet</span>'}</div>
    <h3>Processes (${(mem.all||[]).length})</h3>
    <table><tr><th>Process</th><th>RSS</th></tr>${procs||'<tr><td colspan=2 class="mut">none</td></tr>'}</table>
    <h3>Files (${files.count??0})</h3>
    <input class="search" placeholder="filter files…" oninput="document.querySelectorAll('.frow').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none')">
    <table><tr><th>Path</th><th>Size</th></tr>${fentries.map(f=>`<tr class="frow"><td>${esc(f[0])}</td><td>${f[1]} KB</td></tr>`).join('')||'<tr><td colspan=2 class="mut">none</td></tr>'}</table>
    <h3>Cron history</h3><div class="tl">${cronH}</div>
  </div></div>`;
}
function closeDetail(){
  DETAIL_AGENT=null;
  if(detailTimer){ clearInterval(detailTimer); detailTimer=null; }
  document.getElementById('modal').innerHTML='';
}
document.addEventListener('keydown',e=>{ if(e.key==='Escape') closeDetail(); });
tick(); setInterval(tick,10000);
</script></body></html>
"""


if __name__ == "__main__":
    load()
    srv = ThreadingHTTPServer((BIND_IP, PORT), Handler)
    print("fleet receiver listening on http://%s:%d  (dashboard + ingest)" % (BIND_IP, PORT))
    print("waiting for agents... (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
