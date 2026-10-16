"""Watch a running simulation in the browser.

    python scripts/live_view.py <sim_code> [port]      # default port 8800

Read-only: it polls storage/<sim>/movement/ for whatever the backend has
written and draws it. It is NOT the environment stepper, so closing, hiding or
reloading this page cannot stall the run -- unlike the repo's own live mode at
localhost:8000, where the browser drives each step.
"""
import datetime
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SIM = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8800
STORE = ROOT / "environment/frontend_server/storage" / SIM
LOGS = ROOT / "runs" / SIM
BOARD = LOGS / "board.png"

COLORS = ["#e2524a", "#39a0b0", "#9b6cc4", "#e08a37", "#4e9a5a", "#c75fa0",
          "#7b8cde", "#b5a13c"]

_lock = threading.Lock()
_seen_chats = set()
_convos = []
_scanned = -1


def latest_step():
  try:
    return max(int(f[:-5]) for f in os.listdir(STORE / "movement") if f.endswith(".json"))
  except (FileNotFoundError, ValueError):
    return -1


def clock(step):
  meta = json.loads((STORE / "reverie/meta.json").read_text())
  start = datetime.datetime.strptime(meta["start_date"], "%B %d, %Y")
  return (start + datetime.timedelta(seconds=step * meta["sec_per_step"]),
          meta["persona_names"])


def scan_new_conversations(upto):
  """Incremental: only look at steps we have not read yet."""
  global _scanned
  for s in range(_scanned + 1, upto + 1):
    p = STORE / "movement" / f"{s}.json"
    if not p.exists():
      continue
    try:
      doc = json.loads(p.read_text()).get("persona", {})
    except (json.JSONDecodeError, OSError):
      continue
    for name, rec in doc.items():
      chat = rec.get("chat")
      if not chat:
        continue
      key = json.dumps(chat)
      if key in _seen_chats:
        continue
      _seen_chats.add(key)
      _convos.append({"step": s, "who": sorted({l[0] for l in chat}),
                      "turns": len(chat), "lines": chat})
  _scanned = upto


def tally(path, field=None, match=None):
  total, n = 0.0, 0
  try:
    for line in open(path):
      rec = json.loads(line)
      n += 1
      if field:
        total += rec.get(field, 0)
      if match and rec.get("outcome") != match:
        n -= 1
  except (OSError, json.JSONDecodeError):
    pass
  return total, n


def state():
  step = latest_step()
  if step < 0:
    return {"waiting": True}
  with _lock:
    scan_new_conversations(step)
    convos = [{k: v for k, v in c.items() if k != "lines"} for c in _convos]
    latest_convo = _convos[-1] if _convos else None
  when, names = clock(step)
  doc = json.loads((STORE / "movement" / f"{step}.json").read_text())["persona"]
  agents = []
  for i, n in enumerate(names):
    r = doc.get(n, {})
    desc = (r.get("description") or "").split(" @ ")
    agents.append({"name": n, "short": n.split()[0], "color": COLORS[i % len(COLORS)],
                   "x": r.get("movement", [0, 0])[0], "y": r.get("movement", [0, 0])[1],
                   "emoji": r.get("pronunciatio") or "", "doing": desc[0],
                   "where": desc[1].replace("the Ville:", "") if len(desc) > 1 else "",
                   "chatting": bool(r.get("chat"))})
  cost, calls = tally(LOGS / "cost_log.jsonl", "cost_usd")
  _, failsafes = tally(LOGS / "outcome_log.jsonl", match="fail_safe")
  return {"step": step, "time": when.strftime("%A %B %-d, %-I:%M %p"),
          "agents": agents, "cost": round(cost, 4), "calls": calls,
          "failsafes": failsafes, "convos": convos,
          "latest": latest_convo, "sim": SIM}


PAGE = """<!doctype html><meta charset=utf-8><title>__SIM__ — live</title>
<style>
:root{--bg:#10151a;--panel:#171e25;--line:#263038;--ink:#e7eef3;--muted:#8da0ad}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{display:grid;grid-template-columns:1fr 380px;gap:14px;padding:14px;height:100vh}
.map{position:relative;background:#0b0f13;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.map img{width:100%;display:block;image-rendering:pixelated}
.dot{position:absolute;width:16px;height:16px;border-radius:50%;translate:-50% -50%;
     border:2px solid #0b0f13;transition:left .4s linear,top .4s linear;box-shadow:0 0 0 1px rgba(255,255,255,.35)}
.tag{position:absolute;translate:-50% -185%;font:600 10px ui-monospace,monospace;color:#fff;
     padding:1px 5px;border-radius:3px;white-space:nowrap;transition:left .4s linear,top .4s linear}
.side{display:flex;flex-direction:column;gap:12px;overflow:hidden}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px}
.clock{font:700 26px ui-monospace,monospace;letter-spacing:-.5px}
.sub{color:var(--muted);font:12px ui-monospace,monospace}
.stats{display:flex;gap:16px;margin-top:8px;font:12px ui-monospace,monospace;color:var(--muted);flex-wrap:wrap}
.stats b{color:var(--ink);font-weight:600}
.agents{display:flex;flex-direction:column;gap:7px;overflow-y:auto}
.a{display:grid;grid-template-columns:auto 1fr;gap:9px;align-items:start;padding:8px 10px;
   background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--c);border-radius:5px}
.a .em{font-size:17px}
.a .nm{font-weight:600;font-size:13px}
.a .do{color:var(--muted);font-size:12px}
.a .wh{color:#5f7383;font:11px ui-monospace,monospace;margin-top:2px}
.a.talk{box-shadow:0 0 0 1px #e2524a inset}
.feed{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:6px}
.cv{background:var(--panel);border:1px solid var(--line);border-radius:5px;padding:9px 11px}
.cv .h{font:11px ui-monospace,monospace;color:var(--muted);display:flex;justify-content:space-between}
.cv .l{margin-top:5px;font-size:12.5px}
.cv .l b{color:#9fd0e0;font-weight:600}
h2{font:600 11px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:2px 0}
@media(max-width:900px){.wrap{grid-template-columns:1fr;height:auto}}
</style>
<div class=wrap>
  <div class=map id=map><img src="/board.png" alt="map of the Ville"></div>
  <div class=side>
    <div class=card>
      <div class=clock id=clock>connecting…</div>
      <div class=sub id=step></div>
      <div class=stats id=stats></div>
    </div>
    <h2>Agents</h2>
    <div class=agents id=agents></div>
    <h2>Conversations (<span id=ncv>0</span>)</h2>
    <div class=feed id=feed></div>
  </div>
</div>
<script>
const MAP_W=140, MAP_H=100;
let marks={};
async function tick(){
  let s; try{ s=await (await fetch('/state',{cache:'no-store'})).json(); }catch(e){ return; }
  if(s.waiting){ document.getElementById('clock').textContent='waiting for first step…'; return; }
  document.getElementById('clock').textContent=s.time;
  document.getElementById('step').textContent=`step ${s.step.toLocaleString()} · ${s.sim}`;
  document.getElementById('stats').innerHTML=
    `<span><b>$${s.cost.toFixed(3)}</b> spent</span><span><b>${s.calls}</b> calls</span>`+
    `<span><b>${s.failsafes}</b> fail-safes</span>`;
  const map=document.getElementById('map');
  for(const a of s.agents){
    let m=marks[a.name];
    if(!m){
      const d=document.createElement('div'); d.className='dot'; d.style.background=a.color;
      const t=document.createElement('div'); t.className='tag'; t.style.background=a.color; t.textContent=a.short;
      map.append(d,t); m=marks[a.name]={d,t};
    }
    const L=((a.x+0.5)/MAP_W*100)+'%', T=((a.y+0.5)/MAP_H*100)+'%';
    m.d.style.left=L; m.d.style.top=T; m.t.style.left=L; m.t.style.top=T;
  }
  document.getElementById('agents').innerHTML=s.agents.map(a=>
    `<div class="a ${a.chatting?'talk':''}" style="--c:${a.color}"><div class=em>${a.emoji||'·'}</div>
     <div><div class=nm>${a.short}</div><div class=do>${a.doing||''}</div><div class=wh>${a.where||''}</div></div></div>`).join('');
  document.getElementById('ncv').textContent=s.convos.length;
  const t=st=>{const x=st*10;return String(Math.floor(x/3600)%24).padStart(2,'0')+':'+String(Math.floor(x%3600/60)).padStart(2,'0')};
  document.getElementById('feed').innerHTML=s.convos.slice().reverse().map(c=>
    `<div class=cv><div class=h><span>${c.who.map(w=>w.split(' ')[0]).join(' & ')}</span><span>${t(c.step)} · ${c.turns} turns</span></div>
     ${s.latest&&s.latest.step===c.step?`<div class=l><b>${s.latest.lines[0][0].split(' ')[0]}:</b> ${s.latest.lines[0][1].slice(0,150)}…</div>`:''}</div>`).join('');
}
tick(); setInterval(tick,1500);
</script>"""


class Handler(BaseHTTPRequestHandler):
  def log_message(self, *a):
    pass

  def do_GET(self):
    if self.path.startswith("/state"):
      body = json.dumps(state()).encode()
      self.send_response(200)
      self.send_header("Content-Type", "application/json")
      self.send_header("Cache-Control", "no-store")
    elif self.path.startswith("/board.png"):
      body = BOARD.read_bytes()
      self.send_response(200)
      self.send_header("Content-Type", "image/png")
    else:
      body = PAGE.replace("__SIM__", SIM).encode()
      self.send_response(200)
      self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)


if __name__ == "__main__":
  LOGS.mkdir(parents=True, exist_ok=True)
  if not BOARD.exists():
    # The real Tiled artwork -- the same map Phaser composites at runtime, which
    # is what the paper's figures show. render_board.py draws a schematic from
    # the collision CSVs instead; keep it only as a fallback.
    try:
      from render_map import render as render_map
      render_map(BOARD, 0.5)
    except Exception as e:
      print(f"[live] tiled map unavailable ({type(e).__name__}); using schematic")
      from render_board import render as render_board
      render_board(BOARD)
  print(f"live view of {SIM} -> http://127.0.0.1:{PORT}  (read-only; cannot stall the run)")
  ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
