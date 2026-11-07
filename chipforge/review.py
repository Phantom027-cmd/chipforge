"""Human feedback loop: a single local HTML page to audition renders and leave notes.

    chipforge review song.yml           # renders if needed, builds review.html, serves it, opens the browser

The page embeds the last few versions of the render (OGG, base64) so it works as one file, plays the
loop with Web Audio (true loop points from the sidecar), has a seam-audition button, A/B switching,
stem mutes, timestamped notes and a 1-5 rating. Notes are POSTed to the tiny local server, which
writes `feedback.json` next to the song; without the server the page downloads the file instead.
The agent reads `feedback.json` on its next iteration (MCP `read_feedback`).
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf

MAX_EMBED = 4            # versions embedded in the page


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")


def _peaks(path: Path, n: int = 1400) -> list[float]:
    x, sr = sf.read(str(path), always_2d=True)
    m = np.abs(x).max(axis=1)
    k = max(1, len(m) // n)
    cut = (len(m) // k) * k
    return [round(float(v), 3) for v in m[:cut].reshape(-1, k).max(axis=1)]


def snapshot_version(song_path: Path, out_dir: Path) -> dict:
    """Copy the current render into out_dir/versions/vN_* (if the song changed) and return its record."""
    vdir = out_dir / "versions"
    vdir.mkdir(parents=True, exist_ok=True)
    from .schema import load
    song = load(song_path)
    base = _slug(song.title)
    digest = hashlib.sha1(song_path.read_bytes()).hexdigest()[:10]
    index_p = vdir / "index.json"
    index = json.loads(index_p.read_text(encoding="utf-8")) if index_p.exists() else []
    for rec in index:
        if rec["hash"] == digest and (vdir / rec["audio"]).exists():
            return rec
    n = len(index) + 1
    src_audio = next((out_dir / f"{base}.{ext}" for ext in ("ogg", "wav", "mp3") if (out_dir / f"{base}.{ext}").exists()), None)
    if src_audio is None:
        raise FileNotFoundError(f"no render of {song.title!r} in {out_dir}; run `chipforge render` first")
    audio_name = f"v{n}_{base}.ogg"
    if src_audio.suffix == ".ogg":
        shutil.copy(src_audio, vdir / audio_name)
    else:
        from .export import write_audio
        x, sr = sf.read(str(src_audio), always_2d=True)
        write_audio(vdir / audio_name, x, sr)
    side = json.loads((out_dir / f"{base}.json").read_text(encoding="utf-8"))
    rec = {"version": f"v{n}", "hash": digest, "time": datetime.now().isoformat(timespec="seconds"),
           "audio": audio_name, "title": song.title, "loop": side.get("loop"), "sections": side.get("sections", []),
           "sample_rate": side.get("sample_rate"), "seconds": side.get("length_seconds"),
           "loudness": side.get("loudness", {}), "song_copy": f"v{n}_{song_path.name}"}
    shutil.copy(song_path, vdir / rec["song_copy"])
    stems = {}
    for k, p in side.get("stems", {}).items():
        p = Path(p)
        if p.exists() and k.startswith("stem_layer"):
            name = f"v{n}_{p.stem}.ogg"
            if p.suffix == ".ogg":
                shutil.copy(p, vdir / name)
            else:
                from .export import write_audio
                x, sr = sf.read(str(p), always_2d=True)
                write_audio(vdir / name, x, sr)
            stems[k.replace("stem_", "")] = name
    rec["stems"] = stems
    index.append(rec)
    index_p.write_text(json.dumps(index, indent=1), encoding="utf-8")
    return rec


def build_page(song_path: Path, out_dir: Path) -> Path:
    """Write out_dir/review.html with the latest versions embedded."""
    vdir = out_dir / "versions"
    index_p = vdir / "index.json"
    index = json.loads(index_p.read_text(encoding="utf-8")) if index_p.exists() else []
    versions = []
    for rec in index[-MAX_EMBED:]:
        ap = vdir / rec["audio"]
        if not ap.exists():
            continue
        v = {k: rec.get(k) for k in ("version", "time", "title", "loop", "sections", "seconds", "loudness")}
        v["audio"] = "data:audio/ogg;base64," + base64.b64encode(ap.read_bytes()).decode()
        v["peaks"] = _peaks(ap)
        v["stems"] = {}
        for name, fn in rec.get("stems", {}).items():
            sp = vdir / fn
            if sp.exists() and sp.stat().st_size < 6_000_000:
                v["stems"][name] = "data:audio/ogg;base64," + base64.b64encode(sp.read_bytes()).decode()
        versions.append(v)
    fb_p = out_dir / "feedback.json"
    feedback = json.loads(fb_p.read_text(encoding="utf-8")) if fb_p.exists() else {"song": str(song_path), "entries": []}
    html = TEMPLATE.replace("__DATA__", json.dumps({"song": str(song_path), "versions": versions, "feedback": feedback}))
    page = out_dir / "review.html"
    page.write_text(html, encoding="utf-8")
    return page


def save_feedback(out_dir: Path, song_path: Path, entries: list[dict]) -> Path:
    fb_p = out_dir / "feedback.json"
    data = json.loads(fb_p.read_text(encoding="utf-8")) if fb_p.exists() else {"song": str(song_path), "entries": []}
    seen = {(e.get("time"), e.get("note"), e.get("version")) for e in data["entries"]}
    for e in entries:
        key = (e.get("time"), e.get("note"), e.get("version"))
        if key not in seen:
            data["entries"].append(e)
            seen.add(key)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    fb_p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return fb_p


class _Handler(BaseHTTPRequestHandler):
    out_dir: Path
    song_path: Path

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/review.html"):
            body = (self.out_dir / "review.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif p == "/feedback.json":
            fb = self.out_dir / "feedback.json"
            body = fb.read_bytes() if fb.exists() else b'{"entries": []}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path != "/feedback":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            save_feedback(self.out_dir, self.song_path, payload.get("entries", []))
            body = b'{"ok": true}'
            self.send_response(200)
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def serve(out_dir: Path, song_path: Path, port: int = 8765, open_browser: bool = True, block: bool = True):
    handler = type("H", (_Handler,), {"out_dir": out_dir, "song_path": song_path})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/review.html"
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    print(f"review page: {url}   (Ctrl-C to stop; feedback is written to {out_dir / 'feedback.json'})")
    if block:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    else:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, url


def review(song_path: str | Path, out_dir: str | Path | None = None, *, serve_page: bool = True, port: int = 8765,
           open_browser: bool = True, render_if_needed: bool = True) -> Path:
    song_path = Path(song_path)
    out = Path(out_dir) if out_dir else Path(str(song_path.with_suffix("")) + "_out")
    if render_if_needed:
        from .schema import load
        song = load(song_path)
        base = _slug(song.title)
        if not (out / f"{base}.ogg").exists() and not (out / f"{base}.wav").exists():
            from .export import write_all
            from .render import render
            write_all(render(song), out, formats=("ogg",))
    snapshot_version(song_path, out)
    page = build_page(song_path, out)
    if serve_page:
        serve(out, song_path, port, open_browser)
    return page


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ChipForge review</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#141418;--panel:#1e1e25;--fg:#e8e8ec;--mut:#8a8a96;--acc:#ffd166;--ok:#06d6a0;--bad:#ef476f;--b:#ff9f1c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;background:var(--panel);flex-wrap:wrap}
h1{font-size:16px;margin:0 12px 0 0}button,select,input[type=text]{background:#2a2a33;color:var(--fg);border:1px solid #444;border-radius:6px;padding:6px 10px;font:inherit}
button:hover{border-color:#777;cursor:pointer}button.on{background:var(--acc);color:#111;border-color:var(--acc)}
button.big{font-size:15px;padding:8px 16px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 16px}
#wave{display:block;width:100%;height:150px;background:#0e0e12;cursor:crosshair}
.ab{display:flex;gap:6px}.ab button{min-width:44px}.kbd{color:var(--mut);font-size:12px}
#notes{padding:0 16px 16px}textarea{width:100%;min-height:60px;background:#2a2a33;color:var(--fg);border:1px solid #444;border-radius:6px;padding:8px;font:inherit}
.entry{display:flex;gap:10px;padding:6px 8px;border-bottom:1px solid #2a2a33;align-items:baseline}.entry .t{color:var(--acc);cursor:pointer;min-width:52px;font-variant-numeric:tabular-nums}
.entry .v{color:var(--mut);min-width:34px}.entry .r{color:var(--ok);min-width:40px}.entry .x{color:var(--mut);cursor:pointer;margin-left:auto}
.stars button{padding:4px 8px}.stems label{margin-right:10px;color:var(--mut)}.stat{color:var(--mut)}
#status{color:var(--mut);font-size:12px;margin-left:auto}.pill{background:#2a2a33;border-radius:12px;padding:2px 10px;color:var(--mut);font-size:12px}
</style></head><body>
<header><h1>ChipForge review</h1><span id="title" class="pill"></span><span id="meta" class="stat"></span><span id="status"></span></header>
<div class="row">
  <button id="play" class="big">&#9654; play</button>
  <button id="seam" title="jump to 2 s before the loop end and keep looping">&#8635; seam</button>
  <label><input type="checkbox" id="loop" checked> loop</label>
  <span id="time" class="stat">0.0 s</span>
  <span class="ab" id="ab"></span>
  <span class="kbd">space play · B = A/B · S = seam · N = note here · 1-5 rate · &larr;/&rarr; seek · click waveform to seek</span>
</div>
<canvas id="wave"></canvas>
<div class="row stems" id="stems"></div>
<div id="notes">
  <div class="row" style="padding-left:0">
    <span class="stars" id="stars"></span>
    <button id="verdictOk">&#10003; approve</button><button id="verdictRev">&#8634; revise</button>
    <span class="stat" id="savedAt"></span>
  </div>
  <textarea id="note" placeholder="Note at the current time (N jumps here). Enter = save note, Shift+Enter = newline. Examples: 'lead too loud here', 'break needs drums back at bar 7', 'bass muddy'"></textarea>
  <div class="row" style="padding-left:0"><label><input type="checkbox" id="stamp" checked> attach timestamp</label>
  <button id="add">add note</button><button id="save">save feedback.json</button><button id="dl">download feedback.json</button></div>
  <div id="list"></div>
</div>
<script>
const DATA = __DATA__;
const V = DATA.versions; let cur = V.length-1, other = Math.max(0, V.length-2);
const fb = DATA.feedback.entries || [];
let ctx, buf = {}, stemBufs = {}, src = null, stemSrcs = [], startAt = 0, offset = 0, playing = false, rating = 0, muted = {};
const $ = id => document.getElementById(id);
function fmt(s){return s.toFixed(1)+' s'}
function vinfo(i){const v=V[i]; return v ? `${v.version} · ${v.seconds?.toFixed(1)} s · ${v.loudness?.lufs_after ?? '?'} LUFS · ${v.time?.slice(0,16)}` : ''}
async function ensureCtx(){ if(!ctx){ ctx = new (window.AudioContext||window.webkitAudioContext)(); } if(ctx.state==='suspended') await ctx.resume(); }
async function decode(uri){ const r = await fetch(uri); const ab = await r.arrayBuffer(); return await ctx.decodeAudioData(ab); }
async function load(i){ await ensureCtx(); if(!buf[i]) buf[i] = await decode(V[i].audio);
  if(!stemBufs[i]){ stemBufs[i] = {}; for(const [n,u] of Object.entries(V[i].stems||{})) stemBufs[i][n] = await decode(u); } }
function loopPts(i){ const l = V[i].loop; const b = buf[i]; return l ? [l.start_seconds, l.end_seconds] : [0, b.duration]; }
function stop(){ if(src){ try{src.stop()}catch(e){} src.disconnect(); src=null; } stemSrcs.forEach(s=>{try{s.stop()}catch(e){}}); stemSrcs=[]; if(playing){ offset = pos(); } playing=false; $('play').innerHTML='&#9654; play'; }
function pos(){ if(!playing) return offset; let t = ctx.currentTime - startAt + offset; const [a,b] = loopPts(cur); const b0 = buf[cur];
  if($('loop').checked && t > b){ t = a + ((t - a) % (b - a)); } return Math.min(t, b0.duration); }
async function play(at){ await load(cur); stop(); if(at!==undefined) offset = at; const b = buf[cur]; const [a,e] = loopPts(cur); const useStems = Object.keys(stemBufs[cur]||{}).length && Object.values(muted).some(x=>x);
  const mk = (buffer, gain)=>{ const s = ctx.createBufferSource(); s.buffer = buffer; s.loop = $('loop').checked; s.loopStart = a; s.loopEnd = e; const g = ctx.createGain(); g.gain.value = gain; s.connect(g).connect(ctx.destination); s.start(0, Math.min(offset, buffer.duration-0.01)); return s; };
  if(useStems){ for(const [n,sb] of Object.entries(stemBufs[cur])) stemSrcs.push(mk(sb, muted[n]?0:1)); src = stemSrcs[0]; } else { src = mk(b, 1); }
  startAt = ctx.currentTime; playing = true; $('play').innerHTML='&#10074;&#10074; pause'; src.onended = ()=>{ if(playing && !$('loop').checked){ playing=false; offset=0; $('play').innerHTML='&#9654; play'; } }; }
function toggle(){ playing ? stop() : play(); }
function seam(){ const [a,e] = loopPts(cur); $('loop').checked = true; play(Math.max(a, e-2)); }
async function switchTo(i){ const p = playing; const o = pos(); await load(i); cur = i; if(p) play(o); else offset = o; draw(); renderAB(); $('title').textContent = V[i].title + ' ' + V[i].version; $('meta').textContent = vinfo(i); }
function renderAB(){ const el=$('ab'); el.innerHTML=''; V.forEach((v,i)=>{ const b=document.createElement('button'); b.textContent=v.version; b.className = i===cur?'on':''; b.title=vinfo(i); b.onclick=()=>switchTo(i); el.appendChild(b); }); }
function renderStems(){ const el=$('stems'); el.innerHTML=''; const st = V[cur]?.stems||{}; const names = Object.keys(st); if(!names.length){ el.style.display='none'; return; } el.style.display='flex';
  el.innerHTML = '<span class="stat">stems:</span>'; names.forEach(n=>{ const l=document.createElement('label'); const c=document.createElement('input'); c.type='checkbox'; c.checked=!muted[n]; c.onchange=()=>{ muted[n]=!c.checked; if(playing) play(pos()); }; l.appendChild(c); l.appendChild(document.createTextNode(' '+n)); el.appendChild(l); }); }
function draw(){ const c=$('wave'); const W=c.width=c.clientWidth*devicePixelRatio, H=c.height=150*devicePixelRatio; const g=c.getContext('2d'); g.fillStyle='#0e0e12'; g.fillRect(0,0,W,H);
  const v=V[cur]; if(!v) return; const pk=v.peaks, dur=v.seconds||1; const n=pk.length; const mx=Math.max(...pk)||1; g.fillStyle='#4a4a58';
  for(let i=0;i<n;i++){ const h=pk[i]/mx*H*0.9; g.fillRect(i*W/n, H/2-h/2, Math.max(1,W/n-0.5), h); }
  (v.sections||[]).forEach(s=>{ const x=s.start/dur*W; g.strokeStyle='rgba(255,255,255,.35)'; g.setLineDash([4,4]); g.beginPath(); g.moveTo(x,0); g.lineTo(x,H); g.stroke(); g.setLineDash([]); g.fillStyle='#ccc'; g.font=`${11*devicePixelRatio}px system-ui`; g.fillText(s.label, x+4, 14*devicePixelRatio); (s.exits||[]).forEach(e=>{ const ex=e/dur*W; g.fillStyle='rgba(255,209,102,.5)'; g.fillRect(ex, H-6*devicePixelRatio, 2, 6*devicePixelRatio); }); });
  if(v.loop){ const x=v.loop.start_seconds/dur*W; g.strokeStyle='#06d6a0'; g.lineWidth=2*devicePixelRatio; g.beginPath(); g.moveTo(x,0); g.lineTo(x,H); g.stroke(); g.lineWidth=1; }
  fb.filter(e=>e.version===v.version && typeof e.at==='number').forEach(e=>{ const x=e.at/dur*W; g.fillStyle='#ffd166'; g.beginPath(); g.moveTo(x,0); g.lineTo(x-5*devicePixelRatio,10*devicePixelRatio); g.lineTo(x+5*devicePixelRatio,10*devicePixelRatio); g.fill(); });
  const x=pos()/dur*W; g.strokeStyle='#fff'; g.beginPath(); g.moveTo(x,0); g.lineTo(x,H); g.stroke(); }
function tick(){ draw(); $('time').textContent = fmt(pos()); requestAnimationFrame(tick); }
$('wave').onclick = e=>{ const r=e.target.getBoundingClientRect(); const t=(e.clientX-r.left)/r.width*(V[cur].seconds||1); playing ? play(t) : (offset=t, draw()); };
$('play').onclick = toggle; $('seam').onclick = seam; $('loop').onchange = ()=>{ if(playing) play(pos()); };
function renderStars(){ const el=$('stars'); el.innerHTML=''; for(let i=1;i<=5;i++){ const b=document.createElement('button'); b.textContent=i<=rating?'★':'☆'; b.onclick=()=>{ rating=i; renderStars(); }; el.appendChild(b);} }
function addNote(text, extra){ text=(text||$('note').value).trim(); if(!text && !extra) return; const e={ time:new Date().toISOString().slice(0,19), version:V[cur]?.version, at: $('stamp').checked ? Math.round(pos()*10)/10 : null, note:text, rating: rating||null, ...(extra||{}) }; fb.push(e); $('note').value=''; renderList(); draw(); save(); }
function renderList(){ const el=$('list'); el.innerHTML=''; [...fb].reverse().forEach((e,j)=>{ const d=document.createElement('div'); d.className='entry';
  d.innerHTML = `<span class="t" title="seek">${typeof e.at==='number'?e.at.toFixed(1)+'s':'—'}</span><span class="v">${e.version||''}</span><span class="r">${e.verdict?('['+e.verdict+']'):(e.rating?'★'.repeat(e.rating):'')}</span><span>${(e.note||'').replace(/</g,'&lt;')}</span><span class="x" title="remove">✕</span>`;
  d.querySelector('.t').onclick=()=>{ if(typeof e.at==='number'){ const vi=V.findIndex(v=>v.version===e.version); if(vi>=0&&vi!==cur) switchTo(vi).then(()=>play(e.at)); else play(e.at);} };
  d.querySelector('.x').onclick=()=>{ fb.splice(fb.length-1-j,1); renderList(); draw(); save(); }; el.appendChild(d); }); }
async function save(){ try{ const r = await fetch('/feedback', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entries: fb})}); if(!r.ok) throw new Error(r.status); $('status').textContent='saved feedback.json'; $('savedAt').textContent='saved '+new Date().toLocaleTimeString(); } catch(e){ $('status').textContent='no local server: use "download feedback.json"'; } }
function download(){ const blob=new Blob([JSON.stringify({song: DATA.song, entries: fb}, null, 1)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='feedback.json'; a.click(); }
$('add').onclick=()=>addNote(); $('save').onclick=save; $('dl').onclick=download;
$('verdictOk').onclick=()=>addNote($('note').value||'approved', {verdict:'approve', at:null}); $('verdictRev').onclick=()=>addNote($('note').value||'needs revision', {verdict:'revise', at:null});
$('note').addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); addNote(); } e.stopPropagation(); });
document.addEventListener('keydown', e=>{ if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT') return; const k=e.key;
  if(k===' '){ e.preventDefault(); toggle(); } else if(k==='b'||k==='B'){ if(V.length>1){ const o=cur; switchTo(other); other=o; } } else if(k==='s'||k==='S'){ seam(); }
  else if(k==='n'||k==='N'){ e.preventDefault(); $('stamp').checked=true; $('note').focus(); $('note').placeholder=`note at ${fmt(pos())}`; }
  else if(k>='1'&&k<='5'){ rating=+k; renderStars(); } else if(k==='ArrowLeft'){ play(Math.max(0,pos()-2)); } else if(k==='ArrowRight'){ play(pos()+2); } });
if(V.length){ $('title').textContent=V[cur].title+' '+V[cur].version; $('meta').textContent=vinfo(cur); renderAB(); renderStems(); renderStars(); renderList(); draw(); tick(); load(cur).then(renderStems); } else { $('title').textContent='no versions found - run chipforge render first'; }
</script></body></html>
"""
