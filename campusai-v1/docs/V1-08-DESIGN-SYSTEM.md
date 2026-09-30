# V1-08 — Design System (`frontend/styles.css`)

This is the exact stylesheet, complete. Save it verbatim as `frontend/styles.css`. Selectors match the ids/classes in `V1-06` §2 exactly — do not rename either side.

## 1. Concept
Dark, high-contrast, "small robot at an information desk" — calm chrome, one lively element (the robot). No gradients, no drop shadows beyond a 1px hairline border, flat colour fills only, so it stays legible under exhibition-hall lighting and on a projector.

## 2. Tokens → CSS custom properties

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0E1420` | page background |
| `--panel` | `#161D2B` | cards/panels |
| `--panel-2` | `#0A0F18` | recessed areas (robot's face plates) |
| `--text` | `#EDEFF2` | primary text |
| `--text-muted` | `#8B93A3` | secondary text |
| `--hairline` | `#232B3A` | borders/dividers |
| `--listening` | `#3E7BFA` | listening / Real tag |
| `--thinking` | `#E8A33D` | thinking |
| `--waiting` | `#37C6C0` | waiting for confirmation |
| `--speaking` | `#33C481` | speaking |
| `--error` | `#E5484D` | error |
| `--noticed` | `#FF8A5B` | noticed (presence) |
| `--demo-tag` | `#8B93A3` | Demo tag (muted, deliberately never brighter than Real) |
| `--web-tag` | `#9B6BFF` | Web tag |

## 3. Full stylesheet

```css
:root{
  --bg:#0E1420; --panel:#161D2B; --panel-2:#0A0F18;
  --text:#EDEFF2; --text-muted:#8B93A3; --hairline:#232B3A;
  --listening:#3E7BFA; --thinking:#E8A33D; --waiting:#37C6C0;
  --speaking:#33C481; --error:#E5484D; --noticed:#FF8A5B;
  --demo-tag:#8B93A3; --web-tag:#9B6BFF;
  --radius:10px;
}
*{box-sizing:border-box;}
html,body{height:100%;}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif;
  font-size:16px; line-height:1.45;
}
h1,h2{font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif; font-weight:600; margin:0 0 12px;}
h2{font-size:15px; color:var(--text-muted); text-transform:none; letter-spacing:0.2px;}
button, input{font-family:inherit; font-size:15px;}
:focus-visible{outline:2px solid var(--listening); outline-offset:2px;}

/* ---------- layout ---------- */
.topbar{
  display:flex; align-items:center; justify-content:space-between;
  padding:14px 24px; border-bottom:1px solid var(--hairline);
}
.brand{display:flex; align-items:baseline; gap:10px;}
.brand-name{font-size:20px; font-weight:700;}
.brand-tag{font-size:12px; color:var(--text-muted);}
.switch{display:flex; align-items:center; gap:8px; font-size:13px; color:var(--text-muted);}
.switch input{accent-color:var(--listening);}

.stage{
  display:grid; grid-template-columns:minmax(280px,38%) 1fr;
  gap:20px; padding:20px 24px;
}
.left{display:flex; flex-direction:column; align-items:center; gap:14px;}
.right{display:flex; flex-direction:column; gap:16px; min-width:0;}

#robotMount{width:100%; display:flex; justify-content:center; padding-top:8px;}
#robotMount svg{width:clamp(220px,26vw,360px); height:auto; display:block;}

.status-label{
  margin:0; font-size:15px; color:var(--text-muted); min-height:20px; text-align:center;
}
body[data-state="error"] .status-label{color:var(--error); font-weight:600;}

.hints{
  border:1px solid var(--hairline); border-radius:var(--radius);
  padding:12px 16px; width:100%; max-width:340px; background:var(--panel);
}
.hints-title{margin:0 0 6px; font-size:13px; color:var(--text-muted);}
.hints ul{margin:0; padding-left:18px; font-size:14px;}
.hints li{margin-bottom:4px;}
.hints-foot{margin:8px 0 0; font-size:12px; color:var(--text-muted);}

.controls{display:flex; gap:10px; flex-wrap:wrap; justify-content:center;}
.btn{
  min-height:44px; padding:0 18px; border-radius:999px; border:1px solid var(--hairline);
  background:var(--panel); color:var(--text); cursor:pointer;
}
.btn:disabled{opacity:0.4; cursor:not-allowed;}
.btn.primary{background:var(--listening); border-color:var(--listening); color:#08101F; font-weight:600;}
.btn.large{min-height:52px; padding:0 28px; font-size:16px;}

.textform{display:flex; gap:8px; width:100%; max-width:340px;}
#textInput{
  flex:1; min-height:44px; padding:0 14px; border-radius:999px;
  border:1px solid var(--hairline); background:var(--panel-2); color:var(--text);
}
#textInput:disabled{opacity:0.4;}

.camera{width:200px; border-radius:var(--radius); overflow:hidden; border:1px solid var(--hairline);}
.camera video{width:100%; display:block; transform:scaleX(-1); background:#000;}

.privacy{font-size:11px; color:var(--text-muted); max-width:340px; text-align:center; margin:0;}

.panel{
  border:1px solid var(--hairline); border-radius:var(--radius);
  background:var(--panel); padding:14px 16px; min-width:0;
}
.transcript{height:220px; overflow-y:auto; font-family:"IBM Plex Mono",monospace; font-size:13px;}
.line{margin-bottom:8px; padding-left:8px; border-left:2px solid var(--hairline);}
.line-agent{border-left-color:var(--listening);}
.line-user{border-left-color:var(--text-muted);}
.who{color:var(--text-muted); margin-right:4px;}
.txt{color:var(--text);}

.activity{list-style:none; margin:0; padding:0; font-size:13px; max-height:220px; overflow-y:auto;}
.activity li{
  display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid var(--hairline);
}
.activity li:last-child{border-bottom:none;}
.activity li.running{opacity:0.6;}
.activity .time{font-family:"IBM Plex Mono",monospace; color:var(--text-muted); font-size:11px; flex:0 0 auto;}
.activity .summary{flex:1; min-width:0;}
.tag{font-size:11px; padding:2px 8px; border-radius:999px; flex:0 0 auto;}
.tag-real{background:rgba(62,123,250,0.18); color:var(--listening);}
.tag-demo{background:rgba(139,147,163,0.18); color:var(--demo-tag);}
.tag-web{background:rgba(155,107,255,0.18); color:var(--web-tag);}

.records{margin:0 24px 24px;}
.records table{width:100%; border-collapse:collapse; font-size:13px;}
.records th{text-align:left; color:var(--text-muted); font-weight:500; padding:6px 8px; border-bottom:1px solid var(--hairline);}
.records td{padding:6px 8px; border-bottom:1px solid var(--hairline); font-family:"IBM Plex Mono",monospace;}
.records td:nth-child(2){font-family:inherit;}

.overlay{
  position:fixed; inset:0; background:var(--bg); display:flex; align-items:center; justify-content:center; z-index:50;
}
.overlay-card{text-align:center; max-width:420px; padding:32px;}
.overlay-card h1{font-size:30px; margin-bottom:10px;}
.overlay-card p{color:var(--text-muted); margin-bottom:20px;}
.start-note{color:var(--thinking); font-size:13px; min-height:18px;}

.toast{
  position:fixed; left:50%; bottom:24px; transform:translateX(-50%);
  background:var(--panel); border:1px solid var(--hairline); border-radius:999px;
  padding:10px 18px; font-size:13px; max-width:80vw; text-align:center; z-index:60;
}

/* ---------- responsive ---------- */
@media (max-width:900px){
  .stage{grid-template-columns:1fr;}
  .left{order:1;} .right{order:2;}
}

/* ---------- reduced motion ---------- */
@media (prefers-reduced-motion:reduce){
  *{animation-duration:0.001ms !important; transition-duration:0.001ms !important;}
}
```

## 4. Rules for anything added later
Any new UI element must reuse an existing token — do not introduce a new colour without adding it to §2 first. Keep the flat, no-gradient, no-drop-shadow style everywhere except the robot's own glow effects (handled in SVG, not CSS shadows).
