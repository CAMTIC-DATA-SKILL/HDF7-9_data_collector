import csv
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

import data_collector as dc

# ==========================================
# [설정]
# ==========================================
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 4100

app = Flask(__name__)
app.json.sort_keys = False      # JSON 키 순서 유지 (Meta, Status, Joint, Errors)

DATA_DIR = Path(__file__).resolve().parent / "data"
RECORD_INTERVAL = 1.0           # CSV 기록 간격 (초)

_latest: dict = {}
_lock = threading.Lock()

# ==========================================
# [CSV 기록]
# ==========================================
_rec_lock = threading.Lock()
_rec = {"on": False, "rows": 0, "file": "", "last_t": 0.0, "last_seq": None}

CSV_COLUMNS = (["Timestamp", "Seq", "Model", "Online",
                "Playback", "RemoteMode", "MotorState", "EmergencyStop"]
               + [f"J{i}_{k}" for i in range(1, 7) for k in ("Position", "Velocity")]
               + ["X", "Y", "Z", "Rx", "Ry", "Rz", "LastError"])


def _flatten(p: dict) -> dict:
    row = {}
    row.update(p.get("Meta", {}))
    row.update(p.get("Status", {}))
    for j, v in p.get("Joint", {}).items():
        row[f"{j}_Position"] = v.get("Position")
        row[f"{j}_Velocity"] = v.get("Velocity")
    cart = p.get("Cartesian", {})
    row.update(cart.get("Position", {}))
    row.update(cart.get("Orientation", {}))
    row.update(p.get("Errors", {}))
    return row


def _record_row(p: dict):
    """기록 중이면 RECORD_INTERVAL 간격으로 data/YYYY-MM-DD-data.csv 에 1행 추가"""
    with _rec_lock:
        if not _rec["on"]:
            return
        now = time.monotonic()
        seq = p.get("Meta", {}).get("Seq")
        if now - _rec["last_t"] < RECORD_INTERVAL or seq == _rec["last_seq"]:
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now():%Y-%m-%d}-data.csv"   # 자정 넘으면 자동으로 새 파일
        path = DATA_DIR / name
        new = not path.exists()
        try:
            with path.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(_flatten(p))
        except OSError as e:
            print(f"[record] write failed: {e}", file=sys.stderr)
            return
        _rec.update(last_t=now, last_seq=seq, file=name, rows=_rec["rows"] + 1)


def upload(payload: dict):
    """data_collector가 0.1초마다 호출 → 최신 JSON을 서버 메모리에 업로드"""
    global _latest
    with _lock:
        _latest = payload
    _record_row(payload)


def _rec_status():
    with _rec_lock:
        return {"on": _rec["on"], "file": _rec["file"], "rows": _rec["rows"]}


@app.get("/api/record")
def record_status():
    return jsonify(_rec_status())


@app.post("/api/record")
def record_toggle():
    on = bool((request.get_json(silent=True) or {}).get("on"))
    with _rec_lock:
        if on and not _rec["on"]:
            _rec.update(rows=0, last_t=0.0, last_seq=None,
                        file=f"{datetime.now():%Y-%m-%d}-data.csv")
        _rec["on"] = on
    return jsonify(_rec_status())


@app.get("/api/data")
def get_data():
    with _lock:
        data = _latest
    if not data:
        return jsonify({"error": "no data yet"}), 503
    return jsonify(data)


@app.get("/health")
def health():
    return jsonify({"ok": True})


# ==========================================
# [/api/data_update] 실시간 뷰어
# ==========================================
_INLINE_TOP = {"Meta", "Errors"}   # 최상위에서 한 줄로 표시할 키


def _c(v) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def format_payload(d: dict) -> str:
    """요청된 줄바꿈 형식으로 JSON 문자열 생성"""
    top = []
    for k, v in d.items():
        if k in _INLINE_TOP or not isinstance(v, dict):
            top.append(f' {_c(k)}:{_c(v)}')
        else:
            inner = ",\n".join(f'  {_c(k2)}:{_c(v2)}' for k2, v2 in v.items())
            top.append(f' {_c(k)}:{{\n{inner}\n }}')
    return "{\n" + ",\n".join(top) + "\n}"


@app.get("/api/data_update/raw")
def get_data_update_raw():
    with _lock:
        data = _latest
    if not data:
        return Response("no data yet", status=503, mimetype="text/plain")
    seq = str(data.get("Meta", {}).get("Seq", ""))
    if request.args.get("seq") == seq:
        return Response(status=204)
    resp = Response(format_payload(data), mimetype="text/plain; charset=utf-8")
    resp.headers["X-Seq"] = seq
    resp.headers["Cache-Control"] = "no-store"
    return resp


_VIEWER_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>HDF7-9 Live Data</title>
<meta name="description" content="Hyundai HDF7-9 real-time robot data viewer">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
 body{margin:0;background:#f5f7fb;color:#1f2937;font-family:Consolas,Menlo,monospace}
 header{padding:12px 20px;background:#fff;border-bottom:1px solid #e5e7eb;box-shadow:0 1px 3px rgba(0,0,0,.04);display:flex;gap:16px;align-items:center}
 h1{font-size:16px;margin:0}
 #st{font-size:13px;padding:2px 10px;border-radius:10px;background:#9ca3af;color:#fff}
 #st.ok{background:#16a34a}#st.err{background:#dc2626}
 #ts{font-size:13px;color:#6b7280}
 #rec{margin-left:auto;display:flex;align-items:center;gap:8px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:16px;padding:4px 12px;cursor:pointer;font-family:inherit;font-size:13px;transition:all .15s}
 #rec:hover{border-color:#ef4444}
 #rec .dot{width:10px;height:10px;border-radius:50%;background:#9ca3af}
 #rec.on{background:#fef2f2;border-color:#ef4444;color:#b91c1c}
 #rec.on .dot{background:#ef4444;animation:blink 1s infinite}
 @keyframes blink{50%{opacity:.25}}
 #win{background:#fff;color:#1f2937;border:1px solid #d1d5db;border-radius:6px;padding:4px 8px;font-family:inherit}
 pre{margin:20px;padding:16px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;font-size:15px;line-height:1.5}
 .charts{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:0 20px 20px}
 @media(max-width:1000px){.charts{grid-template-columns:1fr}}
 .panel{background:#fff;border:1px solid #e5e7eb;box-shadow:0 1px 3px rgba(0,0,0,.05);border-radius:8px;padding:14px}
 .panel h2{font-size:14px;margin:0 0 10px;color:#4b5563}
 .ctrl{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;font-size:13px}
 .jbtn{background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:6px;padding:4px 12px;cursor:pointer;font-family:inherit}
 .jbtn:hover{border-color:#3b5bdb}.jbtn.on{background:#3b5bdb;border-color:#3b5bdb;color:#fff}
 .ctrl label{display:flex;align-items:center;gap:4px;padding:3px 8px;border-radius:6px;background:#f3f4f6;cursor:pointer;font-weight:bold}
 .box{height:340px;position:relative}
</style></head><body>
<header><h1>HDF7-9 /api/data_update</h1><span id="st">connecting</span><span id="ts"></span>
 <button id="rec" title="CSV record (data/YYYY-MM-DD-data.csv)"><span class="dot"></span><span id="rectxt">REC</span></button>
 <select id="win" title="time window">
  <option value="60">최근 60초</option><option value="600">최근 10분</option>
  <option value="1800">최근 30분</option><option value="3600">최근 1시간</option>
 </select></header>
<pre id="out">waiting...</pre>
<section class="charts">
 <div class="panel"><h2>Joint Position / Velocity</h2><div class="ctrl" id="jsel"></div><div class="box"><canvas id="cj"></canvas></div></div>
 <div class="panel"><h2>Cartesian Position / Orientation</h2><div class="ctrl" id="csel"></div><div class="box"><canvas id="cc"></canvas></div></div>
</section>
<script>
let seq="";const out=document.getElementById("out"),st=document.getElementById("st"),ts=document.getElementById("ts");
const MAX_KEEP=3600e3, MAX_PTS=1000;           // 1시간 보관, 화면엔 최대 1000점
const hist=[];                                  // {t, j:{J1:[pos,vel]..}, c:[x,y,z,rx,ry,rz]}
let winSec=60, curJ="J1";
const CK=["X","Y","Z","Rx","Ry","Rz"], CC=["#ff6b6b","#51cf66","#4dabf7","#fcc419","#cc5de8","#20c997"];
const fmt=v=>new Date(v).toLocaleTimeString("ko-KR",{hour12:false});
const grid={color:"#e5e7eb"}, tk={color:"#4b5563"};
function opts(y1,y2){return{animation:false,responsive:true,maintainAspectRatio:false,parsing:false,normalized:true,
 interaction:{mode:"index",intersect:false},elements:{point:{radius:0},line:{borderWidth:1.5}},
 plugins:{legend:{labels:{color:"#374151"}},tooltip:{callbacks:{title:i=>i.length?fmt(i[0].parsed.x):""}}},
 scales:{x:{type:"linear",grid,ticks:{...tk,maxTicksLimit:8,callback:fmt}},
  y:{position:"left",title:{display:true,text:y1,color:"#4b5563"},grid,ticks:tk},
  y2:{position:"right",title:{display:true,text:y2,color:"#4b5563"},grid:{drawOnChartArea:false},ticks:tk}}}}
const cj=new Chart(document.getElementById("cj"),{type:"line",options:opts("Position (deg)","Velocity"),data:{datasets:[
 {label:"Position",borderColor:"#4dabf7",yAxisID:"y",data:[]},{label:"Velocity",borderColor:"#ff922b",yAxisID:"y2",data:[]}]}});
const cc=new Chart(document.getElementById("cc"),{type:"line",options:opts("X / Y / Z (mm)","Rx / Ry / Rz (deg)"),
 data:{datasets:CK.map((k,i)=>({label:k,borderColor:CC[i],yAxisID:i<3?"y":"y2",data:[]}))}});
cc.options.plugins.legend.display=false;
// 조인트 선택 버튼
const jsel=document.getElementById("jsel");
["J1","J2","J3","J4","J5","J6"].forEach(j=>{const b=document.createElement("button");b.className="jbtn"+(j===curJ?" on":"");
 b.id="btn-"+j;b.textContent=j;b.onclick=()=>{curJ=j;jsel.querySelectorAll(".jbtn").forEach(x=>x.classList.toggle("on",x===b));redraw();};jsel.appendChild(b);});
// Cartesian 체크박스
const csel=document.getElementById("csel");
CK.forEach((k,i)=>{const l=document.createElement("label");l.style.color=CC[i];
 l.innerHTML=`<input type="checkbox" id="chk-${k}" checked>${k}`;
 l.querySelector("input").onchange=e=>{cc.data.datasets[i].hidden=!e.target.checked;cc.update("none");};csel.appendChild(l);});
document.getElementById("win").onchange=e=>{winSec=+e.target.value;redraw();};
// Record 토글 (서버에서 1초 간격 CSV 기록)
const recBtn=document.getElementById("rec"), recTxt=document.getElementById("rectxt");
function showRec(s){recBtn.classList.toggle("on",s.on);recTxt.textContent=s.on?`REC ${s.file} (${s.rows})`:"REC";}
async function recReq(body){try{const r=await fetch("/api/record",body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{cache:"no-store"});showRec(await r.json());}catch(e){}}
recBtn.onclick=()=>recReq({on:!recBtn.classList.contains("on")});
recReq(); setInterval(()=>recReq(),1000);
function push(d){
 const t=Date.now(), j={};
 for(const k in (d.Joint||{}))j[k]=[d.Joint[k].Position,d.Joint[k].Velocity];
 const p=(d.Cartesian||{}).Position||{}, o=(d.Cartesian||{}).Orientation||{};
 hist.push({t,j,c:[p.X,p.Y,p.Z,o.Rx,o.Ry,o.Rz]});
 while(hist.length&&hist[0].t<t-MAX_KEEP)hist.shift();
}
function redraw(){
 const now=Date.now(), from=now-winSec*1000;
 let s=hist.findIndex(h=>h.t>=from); if(s<0)s=hist.length;
 const v=hist.slice(s), step=Math.max(1,Math.ceil(v.length/MAX_PTS)), pts=v.filter((_,i)=>i%step===0||i===v.length-1);
 cj.data.datasets[0].data=pts.filter(h=>h.j[curJ]).map(h=>({x:h.t,y:h.j[curJ][0]}));
 cj.data.datasets[1].data=pts.filter(h=>h.j[curJ]).map(h=>({x:h.t,y:h.j[curJ][1]}));
 cc.data.datasets.forEach((ds,i)=>ds.data=pts.map(h=>({x:h.t,y:h.c[i]})));
 for(const c of [cj,cc]){c.options.scales.x.min=from;c.options.scales.x.max=now;c.update("none");}
}
async function tick(){
 try{
  const r=await fetch("/api/data_update/raw?seq="+encodeURIComponent(seq),{cache:"no-store"});
  if(r.status===200){seq=r.headers.get("X-Seq")||"";const txt=await r.text();out.textContent=txt;
   try{push(JSON.parse(txt));}catch(e){}
   ts.textContent="updated "+new Date().toLocaleTimeString();}
  else if(r.status===503){out.textContent="no data yet";}
  st.textContent="online";st.className="ok";
 }catch(e){st.textContent="disconnected";st.className="err";}
 setTimeout(tick,200);
}
setInterval(redraw,500);
tick();
</script></body></html>"""


@app.get("/api/data_update")
def data_update_view():
    return Response(_VIEWER_HTML, mimetype="text/html")


def main():
    robot_ip = sys.argv[1] if len(sys.argv) > 1 else dc.ROBOT_IP
    robot_port = int(sys.argv[2]) if len(sys.argv) > 2 else dc.ROBOT_PORT

    worker = dc.ModbusWorker(robot_ip, robot_port, dc.load_map(dc.MAP_FILE),
                             on_payload=upload, echo=False)
    worker.start()
    try:
        # use_reloader=False: 리로더가 켜지면 수집기가 2번 실행됨
        app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True, use_reloader=False)
    finally:
        worker.shutdown()


if __name__ == "__main__":
    main()