"""First real UI — the day browser, served by heimdall itself.

Grew out of the v3 day-browser prototype (heimdall-ui/prototypes/day-browser).
A same-origin single page: it reads the day's frames, watch sessions, search
hits and frame images straight from this API, so the data is always the live
DB — no embedded snapshot. The recap card is synthesized from watch sessions
client-side; the LLM day-recap pipe plugs in later.

Route: GET / serves the page; the JSON API lives under /frames, /sessions,
/search, /status, /pipes.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter()

DAY_BROWSER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>heimdall · day browser</title>
<style>
/* ============================================================
   DESIGN SYSTEM — Heimdall
   ============================================================
   COLOR
     bg          #0c0f14  app background
     surface     #131926  panels
     surface-2   #1a2131  raised cards
     line        #222c40  hairline borders
     text        #e9edf5
     text-dim    #9aa4ba  secondary
     text-faint  #5e6a82  tertiary
     accent      #5b8cff  primary action
     ok          #3ecf8e  alive / playing
     warn        #f0b456
     danger      #ff6b6b
   TYPE (system-ui stack)
     .t-xs  11px  labels
     .t-sm  12px  captions
     .t-bd  13px  body
     .t-tl  15px  titles
     .t-hd  20px  section headers
     .t-he  30px  hero
   SPACE  4 · 8 · 12 · 16 · 20 · 24 · 32 · 40
   RADIUS sm 6 · md 10 · lg 14 · pill 999
   ELEV   shadow[0]=0 1px 2px rgb(0 0 0/.4)
          shadow[1]=0 4px 12px rgb(0 0 0/.45)
          shadow[2]=0 12px 32px rgb(0 0 0/.55)
   MOTION 150ms ease-out (interactions), 200ms ease (panels)
   ============================================================ */
  :root{
    --bg:#0c0f14; --surface:#131926; --surface-2:#1a2131; --line:#222c40;
    --text:#e9edf5; --text-dim:#9aa4ba; --text-faint:#5e6a82;
    --accent:#5b8cff; --ok:#3ecf8e; --warn:#f0b456; --danger:#ff6b6b;
    --r-sm:6px; --r-md:10px; --r-lg:14px; --r-pill:999px;
    --e0:0 1px 2px rgb(0 0 0/.4);
    --e1:0 4px 12px rgb(0 0 0/.45);
    --e2:0 12px 32px rgb(0 0 0/.55);
    --m-fast:150ms ease-out; --m-panel:200ms ease;
    --ff:system-ui,-apple-system,"Segoe UI",sans-serif;
  }
  *{box-sizing:border-box; margin:0; padding:0}
  html,body{height:100%}
  body{font-family:var(--ff); background:var(--bg); color:var(--text); font-size:13px; line-height:1.45; overflow:hidden}
  img{display:block}
  button{font:inherit; cursor:pointer}
  ::-webkit-scrollbar{width:9px;height:9px}
  ::-webkit-scrollbar-thumb{background:#2b3550; border-radius:99px}
  ::-webkit-scrollbar-track{background:transparent}

  /* --- type scale --- */
  .t-xs{font-size:11px; letter-spacing:.3px}
  .t-sm{font-size:12px}
  .t-bd{font-size:13px}
  .t-tl{font-size:15px; font-weight:650}
  .t-hd{font-size:20px; font-weight:800}
  .t-he{font-size:30px; font-weight:800; letter-spacing:-.5px}
  .muted{color:var(--text-dim)}
  .faint{color:var(--text-faint)}

  /* --- buttons --- */
  .btn{display:inline-flex; align-items:center; gap:8px; background:var(--surface-2);
    border:1px solid var(--line); color:var(--text); border-radius:var(--r-md);
    padding:8px 14px; transition:border-color var(--m-fast), background var(--m-fast)}
  .btn:hover{border-color:var(--accent)}
  .btn.primary{background:var(--accent); border-color:var(--accent); color:#0b1220; font-weight:650}
  .btn.primary:hover{filter:brightness(1.08)}
  .btn.ghost{background:transparent; border-color:transparent; color:var(--text-dim)}
  .btn.ghost:hover{color:var(--text)}
  .btn.icon{width:34px; height:34px; padding:0; border-radius:50%; justify-content:center; font-size:16px}
  .btn:disabled{opacity:.4; cursor:default; pointer-events:none}

  /* --- inputs --- */
  .input{font:inherit; background:var(--surface); color:var(--text); border:1px solid var(--line);
    border-radius:var(--r-md); padding:9px 14px; outline:none; width:100%; transition:border-color var(--m-fast)}
  .input:focus{border-color:var(--accent); box-shadow:0 0 0 3px rgb(91 140 255/.18)}

  /* --- chips --- */
  .chip{display:inline-flex; align-items:center; gap:6px; font-size:11px; letter-spacing:.2px;
    color:var(--text-dim); border:1px solid var(--line); border-radius:var(--r-pill); padding:3px 10px; white-space:nowrap}
  .chip.ok{color:var(--ok); border-color:rgb(62 207 142/.35)}
  .chip.warn{color:var(--warn); border-color:rgb(240 180 86/.35)}
  .chip.mus{color:var(--ok); border-color:rgb(62 207 142/.35); background:rgb(62 207 142/.08)}
  .chip.dim{color:var(--text-faint)}

  /* --- top bar --- */
  .topbar{display:flex; align-items:center; gap:16px; padding:12px 20px;
    background:var(--surface); border-bottom:1px solid var(--line)}
  .brand{display:flex; align-items:center; gap:10px; font-weight:800; font-size:15px; letter-spacing:.4px}
  .brand .dot{width:10px; height:10px; border-radius:50%; background:var(--ok); box-shadow:0 0 10px var(--ok)}
  .brand .dot.dead{background:var(--danger); box-shadow:0 0 10px var(--danger)}
  .daynav{display:flex; align-items:center; gap:4px}
  .daynav .date{font-weight:650; font-size:14px; min-width:150px; text-align:center}
  .searchwrap{flex:1; max-width:420px; margin-left:auto; position:relative}
  .searchwrap .input{padding-left:36px}
  .searchwrap .mag{position:absolute; left:12px; top:50%; transform:translateY(-50%); color:var(--text-faint); font-size:14px; pointer-events:none}

  /* --- layout --- */
  .stage{display:grid; grid-template-columns:minmax(0,1fr) 360px; height:calc(100vh - 64px)}
  .main{display:flex; flex-direction:column; min-width:0; min-height:0}
  .side{border-left:1px solid var(--line); background:var(--surface); overflow-y:auto; padding:20px}
  .side h2{font-size:11px; text-transform:uppercase; letter-spacing:1.2px; color:var(--text-faint); margin:24px 0 10px}
  .side h2:first-child{margin-top:0}

  /* --- preview --- */
  .preview{flex:1; min-height:0; display:flex; align-items:center; justify-content:center; position:relative; overflow:hidden; background:var(--bg)}
  .preview img{max-width:96%; max-height:calc(100% - 44px); object-fit:contain; border-radius:var(--r-md); box-shadow:var(--e1); transition:opacity var(--m-fast)}
  .preview img.loading{opacity:.3}
  .preview .cap{position:absolute; bottom:14px; left:50%; transform:translateX(-50%);
    background:rgb(8 11 16/.85); border:1px solid var(--line); border-radius:var(--r-pill);
    padding:7px 16px; display:flex; gap:12px; align-items:center; font-size:12px; white-space:nowrap; backdrop-filter:blur(6px)}
  .preview .cap b{color:var(--text)}
  .preview .empty{color:var(--text-faint)}

  /* --- scrubber --- */
  .scrubwrap{background:var(--surface); border-top:1px solid var(--line); padding:14px 20px 16px}
  .ruler{position:relative; color:var(--text-faint); font-size:10px;
    font-variant-numeric:tabular-nums; padding:0 2px 6px; letter-spacing:.5px; height:14px}
  .ruler span{position:absolute; top:0; transform:translateX(-50%)}
  .track{position:relative; height:56px; background:var(--surface-2); border:1px solid var(--line);
    border-radius:var(--r-md); overflow:hidden; cursor:pointer; touch-action:none; user-select:none}
  .track.panning{cursor:grabbing}
  .track .hours{position:absolute; inset:0; pointer-events:none}
  .track .hours div{position:absolute; top:0; bottom:0; width:1px; background:var(--line); opacity:.7}
  .track .off{position:absolute; inset:0; pointer-events:none}
  .track .off div{position:absolute; top:0; bottom:0; background:rgb(0 0 0/.38); border-left:1px solid rgb(255 255 255/.07)}
  .track .segs{position:absolute; inset:0}
  .track .seg{position:absolute; top:0; bottom:0; opacity:.6; border-right:1px solid rgb(0 0 0/.3); transition:opacity var(--m-fast)}
  .track .dots{position:absolute; inset:0; pointer-events:none}
  .track .dot{position:absolute; width:4px; height:4px; border-radius:50%; background:rgb(233 237 245/.55);
    top:50%; transform:translate(-50%,-50%); transition:background var(--m-fast)}
  .track .dot.hit{background:var(--warn); box-shadow:0 0 6px var(--warn); width:6px; height:6px}
  .track .dot.src-a11y{background:#3ecf8e; box-shadow:0 0 6px rgb(62 207 142/.6); width:6px; height:6px}
  .track .dot.src-none{background:var(--line); opacity:.45}
  .track .playhead{position:absolute; top:0; bottom:0; width:3px; background:var(--accent);
    box-shadow:0 0 10px var(--accent); pointer-events:none}
  .track .playhead::after{content:""; position:absolute; top:-2px; left:50%; transform:translateX(-50%);
    width:16px; height:9px; border-radius:4px 4px 2px 2px; background:var(--accent); box-shadow:0 0 10px var(--accent)}
  /* cursor caret + live time pill while scrubbing */
  .track .caret{position:absolute; top:0; bottom:0; width:2px; background:var(--text); opacity:0;
    pointer-events:none; transition:opacity var(--m-fast)}
  .track .caret.show{opacity:.9}
  .track .caret .pill{position:absolute; top:4px; left:50%; transform:translateX(-50%); white-space:nowrap;
    font-size:11px; font-weight:650; font-variant-numeric:tabular-nums; letter-spacing:.3px; color:var(--text);
    background:var(--bg); border:1px solid var(--line); border-radius:var(--r-pill); padding:2px 8px;
    box-shadow:var(--e0)}
  /* YouTube-style preview peeking up from the timeline bar */
  .peek{position:fixed; z-index:90; pointer-events:none; width:300px; opacity:0;
    transform:translateY(10px); transition:opacity 120ms ease-out, transform 120ms ease-out}
  .peek.show{opacity:1; transform:translateY(0)}
  .peek .frame{position:relative; background:#000; border:1px solid var(--line); border-radius:var(--r-md);
    overflow:hidden; box-shadow:var(--e2); aspect-ratio:16/9}
  .peek .frame img{width:100%; height:100%; object-fit:cover}
  .peek .time{position:absolute; left:8px; bottom:8px; font-size:11px; font-weight:700; color:#fff;
    font-variant-numeric:tabular-nums; letter-spacing:.4px; background:rgb(0 0 0/.72);
    border-radius:var(--r-pill); padding:3px 9px; backdrop-filter:blur(4px)}
  .peek .app{margin-top:6px; font-size:11px; color:var(--text-dim); white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis}
  .peek .caret{position:absolute; top:100%; width:0; height:0; border:7px solid transparent;
    border-top-color:var(--accent); filter:drop-shadow(0 1px 2px rgb(0 0 0/.5))}
  .scrubbar{display:flex; align-items:center; gap:14px; margin-top:12px}
  .scrubbar .time{font-variant-numeric:tabular-nums; font-size:13px; font-weight:650; min-width:96px}
  .scrubbar .range{margin-left:auto; color:var(--text-faint); font-size:11px; font-variant-numeric:tabular-nums}
  .scrubbar .zoom{display:flex; align-items:center; gap:6px}
  .scrubbar .zoombtn{cursor:pointer; border:none; background:var(--surface-2); color:var(--text-dim);
    font-size:14px; line-height:1; width:22px; height:22px; border-radius:6px; border:1px solid var(--line)}
  .scrubbar .zoombtn:hover{color:var(--text)}
  .scrubbar .zoom input[type=range]{width:110px; accent-color:var(--accent); cursor:pointer}
  .scrubbar .zoomval{font-size:10px; color:var(--text-faint); font-variant-numeric:tabular-nums; min-width:46px; text-align:right}

  /* --- cards --- */
  .card{background:var(--surface-2); border:1px solid var(--line); border-radius:var(--r-lg); padding:16px}
  .recap-card{background:linear-gradient(160deg,var(--surface-2),var(--surface)); border:1px solid var(--line);
    border-radius:var(--r-lg); padding:16px}
  .recap-card .t{font-weight:750; font-size:14px; margin-bottom:8px; display:flex; align-items:center; gap:8px}
  .recap-card p{color:var(--text-dim); font-size:12.5px; white-space:pre-wrap}
  .recap-card .foot{margin-top:12px; padding-top:10px; border-top:1px dashed var(--line); color:var(--text-faint); font-size:11px}

  /* --- frame details --- */
  .frame-meta{display:flex; flex-wrap:wrap; gap:6px; margin:10px 0}
  .textbox{border:1px solid var(--line); border-radius:var(--r-md); overflow:clip}
  .tb-head{display:flex; align-items:center; gap:8px; padding:6px 10px; background:var(--surface-2); border-bottom:1px solid var(--line)}
  .src-tag{font-size:10.5px; font-weight:750; letter-spacing:.06em; text-transform:uppercase; padding:2px 8px; border-radius:var(--r-pill)}
  .src-a11y{background:rgb(62 207 142/.12); color:#3ecf8e; border:1px solid rgb(62 207 142/.4)}
  .src-ocr{background:rgb(91 140 255/.12); color:#7ea3ff; border:1px solid rgb(91 140 255/.4)}
  .src-none{background:var(--surface-2); color:var(--text-faint); border:1px solid var(--line)}
  .textbox .ocr{border:0; border-radius:0}
  .ocr{background:var(--bg); border:1px solid var(--line); border-radius:var(--r-md); padding:12px;
    font-size:12px; color:var(--text-dim); max-height:200px; overflow-y:auto; white-space:pre-wrap; word-break:break-word}

  /* --- search dropdown --- */
  .results{position:absolute; top:calc(100% + 6px); left:0; right:0; z-index:80;
    background:var(--surface-2); border:1px solid var(--line); border-radius:var(--r-md); box-shadow:var(--e2);
    max-height:420px; overflow-y:auto; display:none}
  .results.show{display:block}
  .results .r{display:grid; grid-template-columns:64px 1fr auto; gap:10px; padding:8px 10px; cursor:pointer; align-items:center}
  .results .r:hover{background:var(--surface)}
  .results .r img{width:64px; height:40px; object-fit:cover; border-radius:var(--r-sm)}
  .results .r .ttl{font-weight:600; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
  .results .r .snip{font-size:11px; color:var(--text-dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
  .results .r .tm{font-size:11px; color:var(--text-faint); font-variant-numeric:tabular-nums}
  .results .none{padding:16px; text-align:center; color:var(--text-faint); font-size:12px}

  /* --- dialog --- */
  dialog{border:1px solid var(--line); border-radius:var(--r-lg); background:var(--surface); color:var(--text);
    padding:0; box-shadow:var(--e2); width:420px; max-width:92vw}
  dialog::backdrop{background:rgb(0 0 0/.55); backdrop-filter:blur(3px)}
  .dlg-head{display:flex; align-items:center; justify-content:space-between; padding:16px 18px 12px; border-bottom:1px solid var(--line)}
  .dlg-head h3{font-size:15px; font-weight:750}
  .dlg-body{max-height:60vh; overflow-y:auto; padding:8px 0}
  .dlg-row{display:flex; align-items:center; gap:12px; padding:10px 18px; border-bottom:1px dashed var(--line)}
  .dlg-row .eq{width:8px; height:8px; border-radius:2px; background:var(--ok); flex:0 0 auto; animation:pulse 1.2s infinite}
  .dlg-row .song{font-weight:650; font-size:13px}
  .dlg-row .art{font-size:11px; color:var(--text-faint)}
  .dlg-row .tm{margin-left:auto; font-size:11px; color:var(--text-faint); font-variant-numeric:tabular-nums}
  @keyframes pulse{0%,100%{opacity:.25}50%{opacity:1}}
  .kbd{display:inline-flex; align-items:center; justify-content:center; min-width:22px; height:22px; padding:0 6px;
    border:1px solid var(--line); border-bottom-width:2px; border-radius:var(--r-sm); font-size:11px; color:var(--text-dim); font-family:var(--ff)}

  /* --- view toggle (timeline / grid) --- */
  .viewtoggle{display:flex; gap:2px; background:var(--surface-2); border:1px solid var(--line); border-radius:var(--r-pill); padding:2px}
  .viewtoggle .btn{border:0; border-radius:var(--r-pill); padding:6px 14px; font-size:12px; color:var(--text-dim); background:transparent}
  .viewtoggle .btn:hover{border:0; color:var(--text)}
  .viewtoggle .btn.active{background:var(--accent); color:#0b1220; font-weight:650}
  .timelineview{flex:1; display:flex; flex-direction:column; min-height:0}
  .timelineview.hidden{display:none}
  .gridview{flex:1; display:none; flex-direction:column; min-height:0}
  .gridview.show{display:flex}
  .gridhead{display:flex; align-items:center; gap:10px; padding:12px 20px 0}
  .gridlist{flex:1; overflow-y:auto; padding:16px 20px; display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:14px; align-content:start}
  .griditem{cursor:pointer; border-radius:var(--r-md); overflow:clip; border:1px solid var(--line); background:var(--surface-2); transition:border-color var(--m-fast), transform var(--m-fast)}
  .griditem:hover{border-color:var(--accent); transform:translateY(-2px)}
  .griditem img{width:100%; aspect-ratio:16/9; object-fit:cover; display:block}
  .griditem .gi-meta{padding:8px 10px}
  .griditem .gi-t{font-size:11px; font-weight:650; font-variant-numeric:tabular-nums; display:flex; align-items:center; justify-content:space-between}
  .griditem .gi-a{font-size:11px; color:var(--text-dim); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}

  /* --- app breakdown --- */
  .apps{display:flex; flex-direction:column; gap:6px}
  .approw{display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid transparent; border-radius:var(--r-md); cursor:pointer; transition:border-color var(--m-fast), background var(--m-fast)}
  .approw:hover{background:var(--surface-2)}
  .approw.active{border-color:var(--accent); background:var(--surface-2)}
  .approw .sw{width:10px; height:10px; border-radius:3px; flex:0 0 auto}
  .approw .nm{font-size:12px; font-weight:600; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
  .approw .pct{font-size:11px; color:var(--text-faint); font-variant-numeric:tabular-nums; margin-left:8px}
  .approw .bar{height:4px; border-radius:2px; background:var(--surface); overflow:hidden; margin-top:4px}
  .approw .bar i{display:block; height:100%; border-radius:2px}
  .track .seg.dim{opacity:.12}
  .track .dot.muted{opacity:.15}

  /* --- fullscreen overlay --- */
  .fs{position:fixed; inset:0; z-index:200; background:rgb(5 7 10/.96); display:none; align-items:center; justify-content:center; cursor:zoom-out}
  .fs.show{display:flex}
  .fs img{max-width:94vw; max-height:94vh; object-fit:contain; border-radius:var(--r-md); box-shadow:var(--e2)}
  .fs .cap{position:absolute; bottom:22px; left:50%; transform:translateX(-50%); background:rgb(8 11 16/.85); border:1px solid var(--line); border-radius:var(--r-pill); padding:7px 16px; font-size:12px; display:flex; gap:12px; align-items:center}

  /* --- parallel watch-session lane (time-linear, synced with the scrubber) --- */
  .tape{overflow-x:auto; overflow-y:hidden; scrollbar-width:thin; margin-top:8px}
  .tape::-webkit-scrollbar{height:8px}
  .tape::-webkit-scrollbar-thumb{background:var(--line); border-radius:4px}
  .canvas{position:relative; min-width:100%}
  .pl-head{display:flex; align-items:center; justify-content:space-between; font-size:10px; font-weight:650;
    letter-spacing:1px; text-transform:uppercase; color:var(--text-faint); margin-bottom:4px}
  .pl-legend{display:flex; gap:10px; letter-spacing:0; text-transform:none; font-weight:500}
  .pl-legend i{display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:4px; vertical-align:-1px}
  .pl-shell{position:relative; background:var(--surface-2); border:1px solid var(--line);
    border-radius:var(--r-md); overflow:hidden; cursor:pointer; touch-action:none; padding:2px 0}
  .pl-off{position:absolute; inset:0; pointer-events:none}
  .pl-off div{position:absolute; top:0; bottom:0;
    background:repeating-linear-gradient(-45deg, rgb(0 0 0/.3) 0 6px, rgb(0 0 0/.1) 6px 12px);
    border-left:1px solid rgb(255 255 255/.05)}
  .pl-row{position:relative; height:24px}
  .pl-row + .pl-row{margin-top:2px}
  .pl-hours{position:absolute; inset:0; pointer-events:none}
  .pl-hours div{position:absolute; top:0; bottom:0; width:1px; background:var(--line); opacity:.5}
  .pl-block{position:absolute; top:0; bottom:0; border-radius:4px; opacity:.85; cursor:pointer; overflow:hidden;
    background:var(--pc,#5b8cff); box-shadow:inset 0 0 0 1px rgb(255 255 255/.07); transition:opacity var(--m-fast)}
  .pl-block:hover{opacity:1; box-shadow:0 0 0 1.5px var(--text-dim)}
  .pl-block.active{opacity:1; box-shadow:0 0 0 2px var(--warn)}
  .pl-block.hit{box-shadow:0 0 0 2px var(--warn)}
  .pl-block .lbl{display:block; font-size:10px; color:#0b1220; font-weight:650; padding:0 6px; line-height:24px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
  .pl-more{height:24px; display:flex; align-items:center; padding:0 10px; font-size:10px; letter-spacing:.5px;
    text-transform:uppercase; color:var(--text-faint)}
  .pl-caret{position:absolute; top:0; bottom:0; width:2px; background:var(--text); opacity:0; pointer-events:none; z-index:3}
  .pl-caret.show{opacity:.85}

  /* --- capture density strip (capture frequency only) --- */
  .density{height:14px; margin-top:8px; display:flex; align-items:flex-end; gap:1px}
  .density .b{flex:1; background:var(--accent); opacity:.35; border-radius:1px 1px 0 0}
  .density .b.hot{opacity:.9}

  /* --- v3: watched strip + media cards --- */
  .chip.vid{color:#ff9d9d; border-color:rgb(255 109 109/.35); background:rgb(255 109 109/.08)}
  .nowwatch{margin-top:12px; background:var(--surface-2); border:1px solid var(--line); border-radius:var(--r-md); padding:10px 12px}
  .nowwatch .t-tl{font-weight:600; font-size:12px; color:#ffd6d6; line-height:1.4}
  .nowwatch .tx{color:var(--text-faint); font-size:11px; margin:6px 0; line-height:1.45; display:-webkit-box;
    -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden}
  .gridsess{display:flex; gap:8px; overflow-x:auto; padding:12px 20px 0}
  .gsess{flex:0 0 auto; background:var(--surface-2); border:1px solid var(--line); border-left:3px solid var(--pc,#5b8cff);
    border-radius:var(--r-md); padding:6px 10px; font-size:12px; cursor:pointer; color:var(--text); white-space:nowrap; transition:border-color var(--m-fast), background var(--m-fast)}
  .gsess:hover{border-color:var(--text-dim); background:var(--surface)}
  #sessdlg{width:600px; max-width:94vw}
  .sess-title{font-size:16px; font-weight:750; line-height:1.3}
  .sess-meta{display:flex; flex-wrap:wrap; gap:6px; margin:10px 0}
  .sess-src{color:var(--text-faint); font-size:11px; word-break:break-all}
  .sess-tx{color:var(--text-dim); font-size:13px; line-height:1.6; max-height:180px; overflow:auto;
    background:var(--bg); border:1px solid var(--line); border-radius:var(--r-md); padding:10px; margin-bottom:10px}
  .sess-segs{border-top:1px solid var(--line); padding-top:8px}
  .sess-seg{display:flex; gap:10px; padding:7px 2px; border-bottom:1px dashed var(--line)}
  .ss-t{color:var(--accent); font-size:11px; white-space:nowrap; width:86px; font-variant-numeric:tabular-nums}
  .ss-d{color:var(--text-dim); font-size:11px; white-space:nowrap; width:78px}
  .ss-tx{color:var(--text-faint); font-size:11px; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
  .results .r .rk{font-size:12px; text-align:center}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand"><span class="dot" id="capdot"></span>Heimdall</div>
  <div class="daynav">
    <button class="btn icon" id="prevday" title="previous day">‹</button>
    <span class="date" id="curdate"></span>
    <button class="btn icon" id="nextday" title="next day">›</button>
  </div>
  <div class="searchwrap">
    <span class="mag">⌕</span>
    <input class="input" id="q" type="text" placeholder="Search frames + transcripts…" autocomplete="off" spellcheck="false">
    <div class="results" id="results"></div>
  </div>
  <div class="viewtoggle" id="viewtoggle">
    <button class="btn active" data-view="timeline">Timeline</button>
    <button class="btn" data-view="grid">Grid</button>
  </div>
  <button class="btn ghost" id="musbtn" title="Today's soundtrack">♪ <span>Soundtrack</span></button>
</div>

<div class="stage">
  <div class="main">
    <div class="timelineview" id="timelineview">
      <div class="preview" id="preview"><span class="empty muted">loading…</span></div>
      <div class="scrubwrap">
        <div class="pl-head">
          <span>Watch timeline</span>
          <span class="pl-legend"><i style="background:#ff6b6b"></i>chromium&nbsp;<i style="background:#f0a65b"></i>brave&nbsp;<i style="background:#3ecf8e"></i>sidra</span>
        </div>
        <div class="tape" id="tape">
          <div class="canvas" id="canvas">
            <div class="ruler" id="ruler"></div>
            <div class="track" id="track">
              <div class="off" id="off"></div>
              <div class="hours"></div>
              <div class="segs" id="segs"></div>
              <div class="dots" id="dots"></div>
              <div class="caret" id="caret"><span class="pill" id="caretpill"></span></div>
              <div class="playhead" id="playhead"></div>
            </div>
            <div class="pl-shell" id="plshell"></div>
          </div>
        </div>
        <div class="density" id="density"></div>
        <div class="scrubbar">
          <span class="time" id="ctime">–:––</span>
          <span class="muted t-sm" id="cmeta">drag or click to scrub</span>
          <span class="zoom" title="stretch the timeline (or scroll over it)">
            <button class="zoombtn" id="zo" aria-label="zoom out">−</button>
            <input type="range" id="zoom" min="2" max="120" step="1" value="5" aria-label="zoom">
            <button class="zoombtn" id="zi" aria-label="zoom in">+</button>
            <span class="zoomval" id="zoomval"></span>
          </span>
          <span class="range" id="crange"></span>
        </div>
      </div>
    </div>

    <div class="gridview" id="gridview">
      <div class="gridsess" id="gridsess"></div>
      <div class="gridhead"><span class="muted t-sm" id="gridinfo"></span></div>
      <div class="gridlist" id="gridlist"></div>
    </div>
  </div>

  <div class="side">
    <h2>How your day went</h2>
    <div class="recap-card" id="recap"></div>

    <h2>Apps</h2>
    <div class="apps" id="apps"></div>

    <h2 style="display:flex; align-items:center; justify-content:space-between">Now
      <button class="btn ghost" id="copyocr" title="copy this frame's extracted text">⧉ Copy</button></h2>
    <div class="t-tl" id="wintitle">—</div>
    <div class="frame-meta" id="winmeta"></div>
    <div class="textbox">
      <div class="tb-head">
        <span class="src-tag" id="src">—</span>
        <span class="muted t-sm" id="srcextra"></span>
      </div>
      <div class="ocr" id="ocr">—</div>
    </div>

    <h2>Watching</h2>
    <div class="nowwatch" id="nowwatch"><div class="muted t-sm">no media playing at this moment</div></div>

    <h2>About the scrubber</h2>
    <p class="muted t-sm" style="line-height:1.7">
      Click the strip to jump. <span class="kbd">←</span><span class="kbd">→</span> step one frame.
      Hover or drag to open a frame preview that peeks up from the bar, like a video scrubber.
      Colored bands = apps; dots = captures — <span style="color:#3ecf8e">teal</span> = a11y
      tree text, <span style="color:#5b8cff">blue</span> = OCR, faint = nothing extracted;
      <span class="chip dim">hits</span> = your search —
      everything sits on a single true time axis, so dots, app bands, and the media blocks line up.
      No-capture stretches compress into small hatched markers, so the timeline only shows real
      activity; drag the tape sideways and it auto-follows the selected frame.
      The <b>Watch timeline</b> lane (<span style="color:#ff9d9d">chromium</span>,
      <span style="color:#f0a65b">brave</span>, <span style="color:#3ecf8e">sidra</span>)
      mirrors your media as contiguous runs (a gap longer than 5 min splits a run);
      click a block to jump there; the short bars underneath show capture frequency.
      Diagonal hatching marks stretches with no captures — laptop off or idle.
    </p>
  </div>
</div>

<dialog id="musdlg">
  <div class="dlg-head">
    <h3>♪ Today's soundtrack</h3>
    <button class="btn ghost icon" id="musclose">✕</button>
  </div>
  <div class="dlg-body" id="muslist"></div>
</dialog>

<dialog id="sessdlg">
  <div class="dlg-head">
    <h3 id="sessh">Media session</h3>
    <button class="btn ghost icon" id="sessclose">✕</button>
  </div>
  <div class="dlg-body" id="sessbody"></div>
</dialog>

<div class="peek" id="peek">
  <div class="frame"><img id="peekimg" alt=""><span class="time" id="peektime">–:––:––</span></div>
  <div class="app" id="peekapp">—</div>
  <div class="caret"></div>
</div>

<div class="fs" id="fs"><img id="fsimg" alt=""><div class="cap" id="fscap"></div></div>

<script>
/* same-origin API: the UI is served by heimdall itself, so all fetches are relative */
const API = '';

/* ---------- helpers ---------- */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = ts => new Date(ts).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
const fmtS = ts => new Date(ts).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
const imgOf = f => `${API}/frames/${f.id}/image`;
/* extracted-text helpers: a11y wins over OCR when present (v2 routing rule) */
const textOf = f => (f.a11y_text||'').trim() || (f.ocr_text||'').trim() || '';
const srcOf = f => (f.a11y_text||'').trim() ? 'a11y' : (f.ocr_text||'').trim() ? 'ocr' : 'none';

/* ---------- data ---------- */
let frames = [];
let t0 = 0, t1 = 0;
let dur = 0;
let dayStr = '';
/* a gap longer than this between captures means the laptop was off/idle:
   it splits app chapters and media runs, and marks the off stretch */
const OFF_MIN = 8*60*1000;

function chapters(){
  const out = [];
  for (const f of frames){
    const last = out[out.length-1];
    if (last && last.cls === f.window_class && new Date(f.ts) - new Date(last.frames[last.frames.length-1].ts) <= OFF_MIN)
      last.frames.push(f);
    else out.push({cls:f.window_class, frames:[f]});
  }
  return out;
}
function clsColor(cls){
  const pal=['#5b8cff','#3ecf8e','#f0b456','#c07bff','#ff7b9c','#37c2d6','#b0c2ff'];
  let h=0; for(const ch of cls) h=(h*31+ch.charCodeAt(0))>>>0;
  return pal[h%pal.length];
}
let sessions = [];
let media = [];
let musicSessions = sessions.filter(s=>s.player==='sidra');
function watchedMin(s){ return (s.ranges||[]).reduce((a,[b,e])=>a+Math.max(0,(e-b)),0)/1e6/60; }
function fmtDur(sec){ sec=Math.round(sec||0); if(sec>=3600) return `${Math.floor(sec/3600)}h ${Math.round((sec%3600)/60)}m`; return `${Math.max(1,Math.round(sec/60))}m`; }
function playerColor(p){ return ({chromium:'#ff6b6b',brave:'#f0a65b',sidra:'#3ecf8e',vlc:'#37c2d6'}[String(p).split('.')[0]]) || '#5b8cff'; }
function sessionAt(ts){
  const d = new Date(ts).getTime();
  for(const s of sessions){
    if(new Date(s.ts0).getTime() > d) break;
    const a = new Date(s.ts0).getTime(), b = s.ts1 ? new Date(s.ts1).getTime() : d;
    if(d >= a && d <= b) return s;
  }
  return null;
}
function mediaOf(s){ return media.find(m=>m.player===s.player && m.title===s.title) || null; }
function playingAt(ts){
  let hit = null;
  for(const s of musicSessions){ if(new Date(s.ts0).getTime() > new Date(ts).getTime()) break; hit = s; }
  return hit;
}
const playingStarts = musicSessions;
const musicBlock = t => t.title || '(untitled)';
const posOf = f => axisOf(f.ts);
const fracT = ts => (new Date(ts)-new Date(t0))/dur;   // linear day fraction (grid, density layout)
/* collapsed time axis: active stretches keep px-per-minute scale; off gaps
   (no captures for > OFF_MIN) compress to a small fixed-width marker, so the
   timeline only shows real activity like a video editor leaves out silence */
const GAP_W = 14;
let ppm = 5;                     // px per active minute (zoom)
function buildAxis(){
  const spans = [];
  let x = 0;
  for(let i=0;i<frames.length-1;i++){
    const a = new Date(frames[i].ts).getTime(), b = new Date(frames[i+1].ts).getTime();
    const off = b-a > OFF_MIN;
    const w = off ? GAP_W : (b-a)/60000*ppm;
    spans.push({a, b, off, x0:x, x1:x+w});
    x += w;
  }
  return spans;
}
let axis = buildAxis();
let AXIS_W = 0;
function axisOf(ts){
  const t = new Date(ts).getTime();
  let lo=0, hi=axis.length;
  while(lo<hi){ const mid=(lo+hi)>>1; if(axis[mid].a<=t) lo=mid+1; else hi=mid; }
  const s = axis[Math.max(0, lo-1)];
  if(t <= s.a) return s.x0;
  if(t >= s.b) return s.x1;
  return s.x0 + (t-s.a)/(s.b-s.a)*(s.x1-s.x0);
}
function tsOf(x){
  x = Math.max(0, Math.min(x, AXIS_W));
  let lo=0, hi=axis.length;
  while(lo<hi){ const mid=(lo+hi)>>1; if(axis[mid].x1<=x) lo=mid+1; else hi=mid; }
  const s = axis[Math.min(Math.max(lo,0), axis.length-1)];
  return new Date(s.a + (x - s.x0)/(s.x1-s.x0)*(s.b-s.a)).getTime();
}
function frameNear(ts){
  let best = frames[0], bd = Infinity;
  for(const f of frames){ const d = Math.abs(new Date(f.ts) - new Date(ts)); if(d < bd){ bd = d; best = f; } }
  return best;
}

/* ---------- watch sessions (v3) ---------- */
function openSession(s){
  $('#sessdlg').showModal();
  const m = mediaOf(s);
  const segs = sessions.filter(x=>x.player===s.player && x.title===s.title);
  $('#sessh').textContent = 'Media session';
  $('#sessbody').innerHTML = `
    <div class="sess-title">▶ ${esc(s.title)}</div>
    <div class="sess-meta">
      <span class="chip">${esc(s.player.split('.')[0])}</span>
      ${s.src?`<span class="chip dim">${esc(s.src)}</span>`:''}
      <span class="chip">${segs.length} segment${segs.length>1?'s':''}</span>
      ${m?`<span class="chip">${fmtDur(m.watched_s)} watched</span>`:''}
      <span class="chip dim">${fmt(s.ts0)} – ${s.ts1?fmt(s.ts1):'now'}</span>
    </div>
    ${(m && m.tx)?`<div class="sess-tx">${esc(m.tx)}</div>`:'<div class="muted t-sm" style="margin-bottom:8px">no transcript captured (captions unavailable for this media)</div>'}
    <div class="sess-segs">${segs.slice(0,16).map(x=>`
      <div class="sess-seg"><span class="ss-t">${fmt(x.ts0)}</span><span class="ss-d">${fmtDur(watchedMin(x)*60)}</span><span class="ss-tx">${esc((x.tx||'').slice(0,95))}</span></div>`).join('')}</div>`;
}
function openSessionByTitle(t){
  const s = sessions.find(x=>x.title===t);
  if(s) openSession(s);
}
function paintNowWatch(f){
  const s = sessionAt(f.ts);
  const m = s ? mediaOf(s) : null;
  $('#nowwatch').innerHTML = s ? `
    <div class="t-tl">▶ ${esc(s.title)}</div>
    <div class="frame-meta">
      <span class="chip">${esc(s.player.split('.')[0])}</span>
      ${m?`<span class="chip">${fmtDur(m.watched_s)}</span>`:''}
    </div>
    <div class="tx">${esc((s.tx||(m&&m.tx)||'').slice(0,150))}</div>
    <button class="btn ghost" id="nowsess">open session</button>`
    : '<div class="muted t-sm">no media playing at this moment</div>';
  const b = document.getElementById('nowsess');
  if(b) b.addEventListener('click', ()=>openSession(s));
}
function paintSessHits(titles){
  document.querySelectorAll('.pl-block').forEach(b=>b.classList.toggle('hit', !!(titles && titles.has(b.dataset.title))));
}

/* ---------- synthesized recap ---------- */
function renderRecap(){
  const c={}; for(const f of frames) c[f.window_class]=(c[f.window_class]||0)+1;
  const top=Object.entries(c).sort((a,b)=>b[1]-a[1]).slice(0,3).map(([k,n])=>`${k} (${n} captures)`);
  const tot=media.reduce((a,m)=>a+m.watched_s,0);
  const topVids=media.slice(0,3).map(m=>m.title);
  $('#recap').innerHTML =
    `<div class="t"><span>▶</span> ${tot?`You watched ${fmtDur(tot)} of media`:'A quiet screen'}</div>
     <p>${tot?`Across ${media.length} videos — the big ones: ${esc(topVids.join(', '))}. `:''}Most time was spent in ${esc(top.join(', '))}.${musicSessions.length?` ${musicSessions.length} music segments played on sidra.`:''}</p>
     <div class="foot">synthesized from live watch sessions</div>`;
}
renderRecap();

/* ---------- app breakdown (click to filter the timeline) ---------- */
let appFilter = null;
function renderApps(){
  if(!frames.length){ $('#apps').innerHTML = '<div class="none">no captures this day</div>'; return; }
  const c = {};
  for(const f of frames) c[f.window_class] = (c[f.window_class]||0) + 1;
  const rows = Object.entries(c).sort((a,b)=>b[1]-a[1]);
  const max = rows[0][1];
  $('#apps').innerHTML = rows.map(([cls,n])=>`
    <div class="approw" data-app="${esc(cls)}">
      <span class="sw" style="background:${clsColor(cls)}"></span>
      <div style="flex:1; min-width:0">
        <div style="display:flex; align-items:baseline">
          <span class="nm">${esc(cls)}</span>
          <span class="pct">${Math.round(n/frames.length*100)}% · ${n}</span>
        </div>
        <div class="bar"><i style="width:${n/max*100}%;background:${clsColor(cls)}"></i></div>
      </div>
    </div>`).join('');
}
$('#apps').addEventListener('click', e => {
  const row = e.target.closest('.approw');
  if(!row) return;
  const app = row.dataset.app;
  appFilter = appFilter === app ? null : app;
  document.querySelectorAll('.approw').forEach(r=>r.classList.toggle('active', r.dataset.app===appFilter));
  applyAppFilter();
});
applyAppFilter();
function applyAppFilter(){
  document.querySelectorAll('.seg').forEach(s=>s.classList.toggle('dim', !!appFilter && s.title !== appFilter));
  document.querySelectorAll('.track .dot').forEach(d=>{
    const f = frames[+d.dataset.i];
    d.classList.toggle('hit', !!appFilter && f.window_class === appFilter);
    d.classList.toggle('muted', !!appFilter && f.window_class !== appFilter);
  });
}

/* ---------- capture density (along the collapsed axis, shows where captures cluster) ---------- */
function renderDensity(){
  const NB = 48;
  const bins = new Array(NB).fill(0);
  for(const f of frames) bins[Math.min(Math.floor(axisOf(f.ts)/AXIS_W*NB), NB-1)]++;
  const max = Math.max(...bins, 1);
  $('#density').innerHTML = bins.map(n=>
    `<div class="b" style="height:${Math.max(n? n/max*100 : 4, 4)}%"></div>`).join('');
}
renderDensity();

/* ---------- parallel watch-session lane (time-linear, synced to the scrubber) ---------- */
const plShell = $('#plshell');
const tape = $('#tape'), canvasEl = $('#canvas');
function fitCanvas(){
  canvasEl.style.width = Math.max(tape.clientWidth, AXIS_W) + 'px';
}
fitCanvas();
const PL_MAX_ROWS = 5;
/* contiguous runs of one media/player; a gap > GAP_MIN (laptop off) splits a run */
const GAP_MIN = 8*60*1000;
let runsCache = null;
function buildRuns(){
  if(runsCache) return runsCache;
  const runs=[];
  const sorted = [...sessions].sort((a,b)=>new Date(a.ts0)-new Date(b.ts0));
  for(const s of sorted){
    const st=new Date(s.ts0).getTime();
    const en=s.ts1?new Date(s.ts1).getTime():st;
    if(en<st) continue;
    let hit=null;
    for(let j=runs.length-1;j>=0;j--){
      const r=runs[j];
      if(r.player===s.player && r.title===s.title && st-r.end<=GAP_MIN){ hit=r; break; }
    }
    if(hit){ hit.end=Math.max(hit.end,en); hit.watched+=watchedMin(s)*60; }
    else runs.push({player:s.player, title:s.title, start:st, end:en, watched:watchedMin(s)*60});
  }
  return runsCache = runs;
}
/* stretches where the laptop captured nothing (no frames), i.e. likely asleep/off */
function offSpans(){
  return axis.filter(s=>s.off);
}
const offMarkup = ()=>offSpans().map(s=>
  `<div title="no captures — laptop off or idle" style="left:${s.x0}px;width:${Math.max(s.x1-s.x0,1)}px"></div>`).join('');
function renderLane(){
  const marks=[];
  const hrs = new Set(frames.map(f=>new Date(f.ts).getHours()));
  [...hrs].sort((a,b)=>a-b).forEach(h=>{
    const m=new Date(t0); m.setHours(h,0,0,0);
    if(m>=new Date(t0)) marks.push(m);
  });
  const hours = marks.map(m=>`<div style="left:${axisOf(m).toFixed(1)}px"></div>`).join('');

  /* interval coloring: greedy-sort by start, assign each block to the
     lowest row whose last block has ended */
  const spans = buildRuns().map(r=>({
    title:r.title, player:r.player, start:r.start, end:r.end, watched:r.watched,
    a:axisOf(new Date(r.start)), b:axisOf(new Date(r.end))
  })).filter(s=>s.b-s.a>0.5)
     .sort((x,y)=>x.start-y.start || y.end-x.end);
  const rows=[], rowEnds=[];
  for(const s of spans){
    let ri=rowEnds.findIndex(e=>e<=s.start);
    if(ri<0){ ri=rows.length; rows.push([]); rowEnds.push(-Infinity); }
    rowEnds[ri]=s.end;
    rows[ri].push(s);
  }
  const shown=rows.slice(0,PL_MAX_ROWS);
  const extra=rows.length-shown.length;
  const rowHtml=shown.map(row=>`
    <div class="pl-row">${row.map(s=>{
      const w=s.b-s.a;
      return `<div class="pl-block" data-title="${esc(s.title)}" data-t="${s.start}" style="left:${s.a.toFixed(1)}px;width:${Math.max(w,1).toFixed(1)}px;--pc:${playerColor(s.player)}" title="${esc(s.title)} · ${s.player.split('.')[0]} · ${fmt(new Date(s.start))}–${fmt(new Date(s.end))} · ${fmtDur(s.watched)}"><span class="lbl">${w>70?esc(s.title):''}</span></div>`;
    }).join('')}</div>`).join('');
  plShell.innerHTML = `<div class="pl-off">${offMarkup()}</div><div class="pl-hours">${hours}</div>${rowHtml}
    ${extra?`<div class="pl-row"><div class="pl-more">+${extra} more row${extra>1?'s':''} of simultaneous media</div></div>`:''}
    <div class="pl-caret" id="plcaret"></div>`;
  plCaretEl = document.getElementById('plcaret');
}
plShell.addEventListener('click', e=>{
  const b = e.target.closest('.pl-block');
  if(!b) return;
  select(frameNear(new Date(+b.dataset.t)));
  openSessionByTitle(b.dataset.title);
});
let plCaretEl = null;
function syncLane(f){
  const t = new Date(f.ts).getTime();
  const runs = buildRuns();
  document.querySelectorAll('.pl-block').forEach(b=>{
    const r = runs.find(x=>x.title===b.dataset.title);
    b.classList.toggle('active', !!(r && t>=r.start && t<=r.end));
  });
  if(plCaretEl){
    plCaretEl.style.left = `${axisOf(f.ts).toFixed(1)}px`;
    plCaretEl.classList.add('show');
  }
}
renderLane();

/* ---------- render scrubber ---------- */
$('#curdate').textContent = dayStr;
const rulerEl = $('#ruler');
function renderRuler(){
  const marks=[];
  const hrs = new Set(frames.map(f=>new Date(f.ts).getHours()));
  [...hrs].sort((a,b)=>a-b).forEach(h=>{
    const m=new Date(t0); m.setHours(h,0,0,0);
    if(m>=new Date(t0)) marks.push(m);
  });
  rulerEl.innerHTML = marks.map(m=>`<span style="left:${axisOf(new Date(m)).toFixed(1)}px">${m.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>`).join('');
  $('#track .hours').innerHTML = marks.map(m=>`<div style="left:${axisOf(new Date(m)).toFixed(1)}px"></div>`).join('');
  $('#crange').textContent = `${fmt(t0)} – ${fmt(t1)}`;
  $('#off').innerHTML = offMarkup();
}
renderRuler();

/* colored segment bands (app runs along the capture axis, tiled by frame count) */
function renderSegs(){
  const chs = chapters();
  $('#segs').innerHTML = chs.map((ch,i)=>{
    const a = axisOf(new Date(ch.frames[0].ts));
    /* pad to the next chapter's first frame, but stop at the last frame when
       the laptop was off in between (no captures) so the gap stays open */
    let endTs;
    if(i+1<chs.length){
      const gap = new Date(chs[i+1].frames[0].ts) - new Date(ch.frames[ch.frames.length-1].ts);
      endTs = gap > OFF_MIN ? new Date(ch.frames[ch.frames.length-1].ts) : new Date(chs[i+1].frames[0].ts);
    } else endTs = new Date(ch.frames[ch.frames.length-1].ts);
    const b = axisOf(endTs);
    return `<div class="seg" data-app="${esc(ch.cls)}" style="left:${a.toFixed(1)}px;width:${Math.max(b-a,1).toFixed(1)}px;background:${clsColor(ch.cls)}" title="${esc(ch.cls)}"></div>`;
  }).join('');
}
renderSegs();

/* capture dots + search hits */
function paintDots(hits){
  $('#dots').innerHTML = frames.map((f,i)=>{
    const h = hits && hits.has(f.id);
    const src = srcOf(f);
    return `<div class="dot${h?' hit':''}${src!=='ocr' ? ' src-'+src : ''}" data-i="${i}" style="left:${axisOf(f.ts).toFixed(1)}px"></div>`;
  }).join('');
}
paintDots(null);

/* ---------- zoom / re-layout (stretch the collapsed timeline) ---------- */
function rebuildAxis(){
  if(!frames.length) return;
  axis = buildAxis();
  AXIS_W = axis[axis.length-1].x1;
  fitCanvas();
  renderRuler();
  renderDensity();
  renderSegs();
  paintDots(hits);
  renderLane();
  $('#playhead').style.left = `${axisOf(sel.ts).toFixed(1)}px`;
  $('#zoomval').textContent = `${Math.round(ppm)}px/min`;
}
function setZoom(v, anchorVp){
  /* content x under the anchor before the zoom */
  const oldX = anchorVp!=null ? anchorVp + tape.scrollLeft : tape.scrollLeft + tape.clientWidth/2;
  /* the span list never reorders on zoom (only widths change), so anchor by
     span index + local fraction for an exact keep-in-place */
  let lo=0, hi=axis.length;
  while(lo<hi){ const mid=(lo+hi)>>1; if(axis[mid].x1<=oldX) lo=mid+1; else hi=mid; }
  const idx = Math.min(lo, axis.length-1);
  const s = axis[idx];
  const f = s.x1-s.x0 ? (oldX-s.x0)/(s.x1-s.x0) : 0;
  ppm = Math.max(2, Math.min(120, +v||5));
  $('#zoom').value = ppm;
  rebuildAxis();
  const ns = axis[idx];
  const newX = ns.x0 + f*(ns.x1-ns.x0);
  const keep = anchorVp!=null ? anchorVp : tape.clientWidth/2;
  tape.scrollLeft = Math.max(0, Math.min(newX - keep, Math.max(0, AXIS_W - tape.clientWidth)));
}
$('#zoom').addEventListener('input', e=>setZoom(+e.target.value));
$('#zo').addEventListener('click', ()=>setZoom(Math.round(ppm/1.5)));
$('#zi').addEventListener('click', ()=>setZoom(Math.round(ppm*1.5)));
$('#zoomval').textContent = `${Math.round(ppm)}px/min`;
tape.addEventListener('wheel', e=>{
  e.preventDefault();
  let dx = e.deltaX, dy = e.deltaY;
  if(e.deltaMode === 1){ dx*=16; dy*=16; }        // line -> px
  if(e.shiftKey && dy && !dx){ dx = dy; dy = 0; } // shift+wheel = horizontal pan
  if(dx){                                          // horizontal scroll pans the view
    tape.scrollLeft = Math.max(0, Math.min(tape.scrollLeft + dx, Math.max(0, AXIS_W - tape.clientWidth)));
  }
  if(dy){                                          // vertical wheel stretches the timeline
    const rect = tape.getBoundingClientRect();
    setZoom(ppm*(dy<0?1.25:0.8), e.clientX - rect.left);
  }
}, {passive:false});

/* ---------- selection state ---------- */
let sel = frames[frames.length-1];
let selId = null;         // null forces first render
let didInit = false;      // first render done (skip initial auto-scroll)
let hits = null;          // Set of frame ids matching current search
let query = '';

/* persistent preview img + caption (no DOM teardown while scrubbing) */
const previewEl = $('#preview');
const pimg = document.createElement('img');
pimg.alt = 'frame';
const pcap = document.createElement('div');
pcap.className = 'cap';
previewEl.innerHTML = '';
previewEl.append(pimg, pcap);
pimg.onload = () => pimg.classList.remove('loading');

const warmCache = new Map();   // frame id -> Image (background preload)
function warm(f){
  if(!f || warmCache.has(f.id)) return;
  const im = new Image(); im.src = imgOf(f); warmCache.set(f.id, im);
}

function ensurePlayheadInView(f){
  const x = axisOf(f.ts);
  if(x < tape.scrollLeft || x > tape.scrollLeft + tape.clientWidth){
    tape.scrollLeft = Math.max(0, Math.min(x - tape.clientWidth/3, tape.scrollWidth - tape.clientWidth));
  }
}

function select(f, rapid){
  const changed = f.id !== selId;
  sel = f;
  if(changed){
    selId = f.id;
    $('#wintitle').textContent = f.window_title || '(untitled window)';
    $('#winmeta').innerHTML = `
      <span class="chip">${fmt(f.ts)}</span>
      <span class="chip">${esc(f.window_class)}</span>
      ${f.fullscreen?'<span class="chip dim">fullscreen</span>':''}`;
    const src = srcOf(f);
    $('#src').textContent = src;
    $('#src').className = 'src-tag src-' + src;
    $('#srcextra').textContent = src==='a11y' ? 'accessibility tree'
      : src==='ocr' ? (f.ocr_engine || 'OCR fallback') : 'nothing extracted';
    $('#ocr').textContent = textOf(f) || 'no text captured';
    $('#copyocr').textContent = '⧉ Copy ' + src.toUpperCase();
    const mus = playingAt(f.ts);
    const capMus = mus ? `<span class="chip mus">♪ ${esc(musicBlock(mus))}</span>` : '';
    const sess = sessionAt(f.ts);
    const capVid = sess ? `<span class="chip vid">▶ ${esc(sess.title.slice(0,42))}</span>` : '';
    paintNowWatch(f);
    syncLane(f);
    pimg.classList.add('loading');
    pimg.src = imgOf(f);
    pcap.innerHTML = `<b>${fmt(f.ts)}</b> <span class="muted">${esc(f.window_class)}</span>${capMus}${capVid}`;
    const i = frames.findIndex(x=>x.id===f.id);
    warm(frames[i-1]); warm(frames[i+1]);
  }
  if(changed && didInit && !rapid && !dragging) ensurePlayheadInView(f);
  $('#ctime').textContent = fmtS(f.ts);
  $('#cmeta').textContent = `${f.window_class}${f.window_title?' · '+esc(f.window_title):''}`.slice(0,70);
  $('#playhead').style.left = `${axisOf(f.ts).toFixed(1)}px`;
  didInit = true;
}

/* ---------- scrubber interactions ---------- */
const track = $('#track');
const peek = $('#peek'), peekImgEl = $('#peekimg'), peekTime = $('#peektime'), peekApp = $('#peekapp');
const caret = $('#caret'), caretPill = $('#caretpill');
let dragging = false;
let tipFrame = null;
const PEEK_W = 300;

function frameAtX(clientX){
  /* rect.left already reflects horizontal scroll, so a plain offset is the
     canvas-local x; map it back through the collapsed axis */
  const r = track.getBoundingClientRect();
  const x = Math.min(Math.max(clientX - r.left, 0), AXIS_W);
  const ts = tsOf(x);
  return {f: frameNear(new Date(ts)), x, ts: new Date(ts)};
}
function seek(clientX){
  const {f} = frameAtX(clientX);
  select(f, true);
}
function positionPeek(clientX){
  const {f, ts} = frameAtX(clientX);
  const r = track.getBoundingClientRect();
  const left = Math.max(8, Math.min(clientX - PEEK_W/2, window.innerWidth - PEEK_W - 8));
  peek.style.left = left + 'px';
  peek.style.top = (r.top - 8 - peek.offsetHeight) + 'px';
  if(f.id !== (tipFrame && tipFrame.id)){
    tipFrame = f;
    peekImgEl.src = imgOf(f);
    peekTime.textContent = fmtS(f.ts);
    peekApp.textContent = `${f.window_class}${f.window_title?' · '+f.window_title:''}`.slice(0,48);
  }
  peek.querySelector('.caret').style.left = (clientX - left - 7) + 'px';
  peek.classList.add('show');
  caret.style.left = `${axisOf(f.ts).toFixed(1)}px`;
  caretPill.textContent = fmtS(ts);
  caret.classList.add('show');
}
function hidePeek(){
  peek.classList.remove('show');
  caret.classList.remove('show');
  tipFrame = null;
}
peekImgEl.onload = () => peekImgEl.classList.remove('loading');
/* middle-button drag pans the timeline view (left button still scrubs) */
let panning = false, panX = 0, panScroll = 0;
track.addEventListener('mousedown', e => { if(e.button===1) e.preventDefault(); });   // kill native autoscroll
track.addEventListener('pointerdown', e => {
  if(e.button === 1){
    panning = true;
    panX = e.clientX;
    panScroll = tape.scrollLeft;
    hidePeek();
    try{ track.setPointerCapture(e.pointerId); }catch(_){}
    track.classList.add('panning');
    return;
  }
  dragging = true;
  try{ track.setPointerCapture(e.pointerId); }catch(_){}
  seek(e.clientX);
});
track.addEventListener('pointermove', e => {
  if(panning){
    e.preventDefault();
    tape.scrollLeft = Math.max(0, Math.min(panScroll - (e.clientX - panX), Math.max(0, AXIS_W - tape.clientWidth)));
    return;
  }
  positionPeek(e.clientX);
  if(dragging) seek(e.clientX);
});
track.addEventListener('pointerup', e => {
  if(panning){ panning = false; track.classList.remove('panning'); return; }
  dragging = false;
  const r = track.getBoundingClientRect();
  const inside = e.clientX>=r.left && e.clientX<=r.right && e.clientY>=r.top && e.clientY<=r.bottom;
  if(!inside) hidePeek();
});
track.addEventListener('pointerleave', () => { if(!dragging && !panning) hidePeek(); });
track.addEventListener('pointercancel', () => { dragging = false; panning = false; track.classList.remove('panning'); hidePeek(); });

/* keyboard stepping */
window.addEventListener('keydown', e => {
  if(e.key==='Escape'){ fs.classList.remove('show'); return; }
  const tag = document.activeElement.tagName;
  if(tag==='INPUT' || tag==='TEXTAREA' || document.activeElement.isContentEditable) return;
  const idx = frames.findIndex(f=>f.id===sel.id);
  if(e.key==='ArrowLeft' && idx>0) select(frames[idx-1]);
  if(e.key==='ArrowRight' && idx<frames.length-1) select(frames[idx+1]);
});

/* ---------- search ---------- */
const qEl = $('#q'), resEl = $('#results');
function runSearch(){
  query = qEl.value.trim();
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if(!terms.length){
    hits = null; paintDots(null); paintSessHits(null); resEl.classList.remove('show');
    return;
  }
  const matched = frames.filter(f =>
    terms.every(t => textOf(f).toLowerCase().includes(t)
      || (f.window_title||'').toLowerCase().includes(t)
      || (f.window_class||'').toLowerCase().includes(t)));
  const sMatches = sessions.filter(s =>
    terms.every(t => (s.title||'').toLowerCase().includes(t)
      || (s.tx||'').toLowerCase().includes(t)
      || (s.player||'').toLowerCase().includes(t)
      || ((s.src||'')).toLowerCase().includes(t)));
  hits = new Set(matched.map(f=>f.id));
  paintDots(hits);
  paintSessHits(new Set(sMatches.map(s=>s.title)));
  const sessRows = sMatches.slice(0,8).map(s=>`
        <div class="r" data-title="${esc(s.title)}">
          <span class="rk" style="color:${playerColor(s.player)}">▶</span>
          <div><div class="ttl">${esc(s.title)}</div>
          <div class="snip">${esc((s.tx||s.src||'').slice(0,90))}</div></div>
          <span class="tm">${fmt(s.ts0)}</span>
        </div>`).join('');
  resEl.innerHTML = (sessRows + matched.slice(0,50).map(f=>`
        <div class="r" data-id="${f.id}">
          <img src="${imgOf(f)}" alt="" loading="lazy">
          <div><div class="ttl">${esc(f.window_title||'(untitled)')}</div>
          <div class="snip">${esc((textOf(f)).slice(0,90))}</div></div>
          <span class="tm">${fmt(f.ts)}</span>
        </div>`).join('')) || '<div class="none">nothing matches — try a different word</div>';
  resEl.classList.add('show');
  resEl.querySelectorAll('.r').forEach(r=>r.addEventListener('click',()=>{
    if(r.dataset.title){ openSessionByTitle(r.dataset.title); resEl.classList.remove('show'); return; }
    select(frames.find(f=>f.id===+r.dataset.id));
    resEl.classList.remove('show');
    setView('timeline');
  }));
}
qEl.addEventListener('input', runSearch);
qEl.addEventListener('keydown', e => { if(e.key==='Escape'){ qEl.value=''; runSearch(); } });
document.addEventListener('click', e => { if(!e.target.closest('.searchwrap')) resEl.classList.remove('show'); });

/* ---------- soundtrack dialog ---------- */
const dlg = $('#musdlg');
$('#musbtn').addEventListener('click', () => {
  $('#muslist').innerHTML = musicSessions.map(s=>`
    <div class="dlg-row">
      <span class="eq"></span>
      <div><div class="song">${esc(musicBlock(s))}</div>
      <div class="art">sidra · ${fmtDur(watchedMin(s)*60)} · ${fmtS(s.ts0)}</div></div>
      <span class="tm">${fmtS(s.ts0)}</span>
    </div>`).join('') || '<div class="none">no music captured — /tracks serving lands with the API extension (#25)</div>';
  dlg.showModal();
});
$('#musclose').addEventListener('click', ()=>dlg.close());
dlg.addEventListener('click', e => { if(e.target===dlg) dlg.close(); });
const sessdlg = document.getElementById('sessdlg');
$('#sessclose').addEventListener('click', ()=>sessdlg.close());
sessdlg.addEventListener('click', e => { if(e.target===sessdlg) sessdlg.close(); });

/* ---------- storyboard grid ---------- */
const gridlist = $('#gridlist');
function renderGrid(){
  gridlist.innerHTML = frames.map((f,i)=>`
    <div class="griditem" data-i="${i}">
      <img src="${imgOf(f)}" alt="" loading="lazy">
      <div class="gi-meta">
        <div class="gi-t"><span>${fmtS(f.ts)}</span><span style="color:${clsColor(f.window_class)}">●</span></div>
        <div class="gi-a">${esc(f.window_class)}${f.window_title?' · '+esc(f.window_title):''}</div>
      </div>
    </div>`).join('');
  $('#gridinfo').textContent = `${frames.length} captures · ${fmt(t0)} – ${fmt(t1)}`;
  $('#gridsess').innerHTML = media.slice(0,10).map(m=>
    `<div class="gsess" data-title="${esc(m.title)}" style="--pc:${playerColor(m.player)}">▶ ${esc(m.title.slice(0,30))} <span class="muted">${fmtDur(m.watched_s)}</span></div>`).join('');
}
gridlist.addEventListener('click', e => {
  const item = e.target.closest('.griditem');
  if(!item) return;
  select(frames[+item.dataset.i]);
  setView('timeline');
});
$('#gridsess').addEventListener('click', e=>{
  const g = e.target.closest('.gsess');
  if(g) openSessionByTitle(g.dataset.title);
});

/* ---------- view toggle ---------- */
function setView(v){
  $('#timelineview').classList.toggle('hidden', v!=='timeline');
  $('#gridview').classList.toggle('show', v==='grid');
  document.querySelectorAll('#viewtoggle .btn').forEach(b=>b.classList.toggle('active', b.dataset.view===v));
}
document.querySelectorAll('#viewtoggle .btn').forEach(b=>b.addEventListener('click', ()=>setView(b.dataset.view)));

/* ---------- fullscreen frame ---------- */
const fs = $('#fs'), fsimg = $('#fsimg'), fscap = $('#fscap');
previewEl.addEventListener('click', e => {
  if(e.target !== pimg && e.target !== pcap) return;
  fsimg.src = pimg.src;
  fscap.innerHTML = pcap.innerHTML;
  fs.classList.add('show');
});
fs.addEventListener('click', ()=>fs.classList.remove('show'));

/* ---------- copy OCR ---------- */
function copyText(txt, done){
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(txt).then(done, ()=>fallbackCopy(txt, done));
  } else fallbackCopy(txt, done);
}
function fallbackCopy(txt, done){
  const ta = document.createElement('textarea');
  ta.value = txt; ta.setAttribute('readonly',''); ta.style.cssText = 'position:fixed;opacity:0';
  document.body.appendChild(ta); ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  done();
}
$('#copyocr').addEventListener('click', () => {
  const txt = textOf(sel);
  if(!txt) return;
  copyText(txt, () => {
    const b = $('#copyocr');
    b.textContent = '✓ Copied';
    setTimeout(()=>{ b.textContent = '⧉ Copy ' + srcOf(sel).toUpperCase(); }, 1200);
  });
});

/* ---------- live day loading (replaces the embedded snapshot once fetched) ---------- */
const p2 = n => String(n).padStart(2,'0');
const dayStrOf = d => `${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}`;
const localISO = d => {
  const off = -d.getTimezoneOffset(), sg = off >= 0 ? '+' : '-', oa = Math.abs(off);
  return `${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}${sg}${p2(Math.floor(oa/60))}:${p2(oa%60)}`;
};
const shiftDay = (s, n) => { const d = new Date(s+'T12:00:00'); d.setDate(d.getDate()+n); return dayStrOf(d); };
function aggregateMedia(list){
  const map = new Map();
  for(const s of list){
    const k = s.player + '|' + s.title;
    let m = map.get(k);
    if(!m){ m = {player:s.player, title:s.title, src:s.src, watched_s:0, tx:''}; map.set(k, m); }
    m.watched_s += (s.ranges||[]).reduce((a,[b,e])=>a+Math.max(0,e-b),0)/1e6;
    m.tx += (s.tx||'').slice(0,20000);
  }
  return [...map.values()].sort((a,b)=>b.watched_s-a.watched_s).slice(0,30);
}
function renderDay(data){
  if(!data.frames.length) return false;
  frames.length = 0; frames.push(...data.frames);
  sessions.length = 0; sessions.push(...data.sessions);
  media.length = 0; media.push(...data.media);
  musicSessions = sessions.filter(s=>s.player==='sidra');
  t0 = frames[0].ts; t1 = frames[frames.length-1].ts;
  dur = new Date(t1) - new Date(t0);
  dayStr = new Date(t1).toLocaleDateString([], {weekday:'short', month:'short', day:'numeric', year:'numeric'});
  runsCache = null;
  appFilter = null; hits = null; qEl.value = '';
  $('#curdate').textContent = dayStr;
  sel = frames[frames.length-1];
  rebuildAxis();
  renderRecap();
  renderApps();
  renderGrid();
  applyAppFilter();
  paintSessHits(null);
  sel = frames[frames.length-1];
  select(sel);
  return true;
}
let curDay = null, navBusy = false;
/* /frames and /sessions cap limit at 100 — page through with offset */
async function fetchAll(url, q){
  const out = [];
  let offset = 0, total = Infinity;
  while(offset < total){
    const r = await fetch(`${url}?${q}&offset=${offset}&limit=100`).then(r=>r.json());
    const items = r.items || [];
    out.push(...items);
    total = r.total ?? out.length;
    if(!items.length) break;
    offset += items.length;
  }
  return out;
}
async function loadDay(dateStr){
  if(navBusy) return;
  navBusy = true;
  document.getElementById('prevday').disabled = document.getElementById('nextday').disabled = true;
  const [y,m,d] = dateStr.split('-').map(Number);
  const start = new Date(y, m-1, d, 0,0,0,0), end = new Date(y, m-1, d+1, 0,0,0,0);
  const q = `start=${encodeURIComponent(localISO(start))}&end=${encodeURIComponent(localISO(end))}`;
  try{
    const [fr, sr] = await Promise.all([
      fetchAll(`${API}/frames`, `${q}&order=asc`),
      fetchAll(`${API}/sessions`, q),
    ]);
    const frm = fr.map(f=>({...f, ts:+new Date(f.ts)}));
    const ses = sr.map(s=>({
      id:s.id, player:s.player, title:s.media_title, src:s.media_source,
      ts0:+new Date(s.ts_start), ts1:s.ts_end?+new Date(s.ts_end):+new Date(s.ts_start),
      ranges:s.ranges||[], tx:s.transcript||'', live:!!s.live,
    }));
    if(!frm.length){ navBusy = false; document.getElementById('prevday').disabled = document.getElementById('nextday').disabled = false; alert(`no captures on ${dateStr}`); return; }
    if(renderDay({frames:frm, sessions:ses, media:aggregateMedia(ses)})) curDay = dateStr;
  }catch(err){
    console.error('loadDay failed', err);
    if(curDay) alert('could not reach the heimdall API — showing the embedded snapshot');
  }
  navBusy = false;
  document.getElementById('prevday').disabled = document.getElementById('nextday').disabled = false;
}
$('#prevday').addEventListener('click', ()=>loadDay(shiftDay(curDay, -1)));
$('#nextday').addEventListener('click', ()=>loadDay(shiftDay(curDay, 1)));
loadDay(dayStrOf(new Date()));

</script>
</body>
</html>
"""


@ui_router.get("/", response_class=HTMLResponse)
def day_browser() -> HTMLResponse:
    return HTMLResponse(DAY_BROWSER_HTML)
