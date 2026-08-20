"""Interactive schematic canvas — pan/zoom a full schematic sheet in the browser.

WHY THIS EXISTS
---------------
The first attempt rendered server-side crops around an OCR'd label. That was the
wrong interaction model:
  * you saw a machine-chosen slice of the sheet with no surrounding context,
  * every zoom change was a full Streamlit rerun + re-render (slow and jarring),
  * if the label happened to sit in a pin list or title block, the crop was
    meaningless.

This replaces it with what an engineer actually expects from a schematic viewer:
the WHOLE sheet, fit to the pane, with free drag-to-pan and wheel-to-zoom handled
entirely client-side. Nets of interest are marked with labelled boxes that stay
locked to the drawing as you navigate, and a "jump" control centres the view on
them.

IMPLEMENTATION NOTES
--------------------
* Deliberately dependency-free vanilla JS (no OpenSeadragon/CDN). Corporate
  networks often block CDNs, and this tool may run offline; ~100 lines of JS
  removes that risk entirely.
* The image and the markers live inside one transformed <div>, with marker
  coordinates expressed in IMAGE pixels. One CSS transform then moves and scales
  both together, so overlays can never drift out of alignment with the drawing.
* The image is inlined as a base64 data URI because the component runs in a
  sandboxed iframe that cannot read local file paths.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import os

import streamlit as st
import streamlit.components.v1 as components

ROLE_STYLES = {
    "primary": ("#DC2663", "this rail"),
    "upstream": ("#7C3AED", "its source"),
    "downstream": ("#2563EB", "feeds"),
    "related": ("#059669", "related"),
    "note": ("#D97706", "note"),
}


def _data_uri(path: str) -> str | None:
    try:
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def render_canvas(image_path: str, markers: list | None = None, height: int = 720,
                  initial: str = "fit", key: str = "sc") -> bool:
    """Render an interactive pan/zoom canvas for one schematic sheet.

    markers: [{"box": [x0,y0,x1,y1], "role": "primary", "label": "VDD_DDR"}]
             with box in ORIGINAL image pixel coordinates.
    initial: "fit" (whole sheet) or "marker" (zoom to the first marker).

    Returns True if it rendered, False if the image couldn't be read.
    """
    uri = _data_uri(image_path)
    if not uri:
        return False

    marks = []
    for m in (markers or []):
        b = m.get("box") or []
        if len(b) != 4:
            continue
        color, _ = ROLE_STYLES.get(m.get("role", "primary"), ROLE_STYLES["primary"])
        marks.append({
            "x": float(b[0]), "y": float(b[1]),
            "w": max(6.0, float(b[2]) - float(b[0])),
            "h": max(6.0, float(b[3]) - float(b[1])),
            "color": color,
            "label": html.escape(str(m.get("label") or ""))[:40],
            "role": m.get("role", "primary"),
        })

    # json.dumps keeps the payload safely escaped for embedding in the script.
    marks_json = json.dumps(marks)
    init_mode = "marker" if (initial == "marker" and marks) else "fit"

    tpl = """
<div class="wrap">
  <div class="bar">
    <button id="zin" title="Zoom in">＋</button>
    <button id="zout" title="Zoom out">－</button>
    <button id="fit" title="Fit whole sheet">Fit sheet</button>
    <button id="one" title="Actual pixels (100%)">1:1</button>
    <button id="jump" title="Centre on the highlighted net">Jump to net</button>
    <span class="hint">drag to pan · scroll to zoom · double-click to zoom in</span>
    <span id="lvl" class="lvl">100%</span>
  </div>
  <div id="vp" class="vp">
    <div id="stage" class="stage">
      <img id="img" src="__URI__" draggable="false"/>
      <div id="ov"></div>
    </div>
  </div>
</div>
<style>
  .wrap{font-family:'DM Sans',system-ui,sans-serif;}
  .bar{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap;}
  .bar button{border:1px solid #E0DBF0;background:#F4F1FB;color:#211B33;border-radius:8px;
    padding:5px 11px;font-size:.85em;font-weight:600;cursor:pointer;font-family:inherit;}
  .bar button:hover{border-color:#059669;color:#059669;background:#05966914;}
  .hint{font-size:.76em;color:#8B84A0;margin-left:6px;}
  .lvl{margin-left:auto;font-size:.78em;color:#5B5470;font-variant-numeric:tabular-nums;
    background:#F4F1FB;border:1px solid #E0DBF0;border-radius:999px;padding:3px 9px;}
  .vp{position:relative;overflow:hidden;background:#fff;border:1px solid #E0DBF0;
    border-radius:10px;height:__H__px;cursor:grab;}
  .vp.grabbing{cursor:grabbing;}
  .stage{position:absolute;top:0;left:0;transform-origin:0 0;}
  .stage img{display:block;image-rendering:auto;user-select:none;-webkit-user-drag:none;}
  #ov{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;}
  .mk{position:absolute;box-sizing:border-box;border-radius:3px;}
  .mklab{position:absolute;transform:translateY(-100%);white-space:nowrap;
    font-size:11px;font-weight:700;color:#fff;padding:1px 5px;border-radius:3px;
    font-family:'DM Mono',monospace;}
</style>
<script>
(function(){
  var MARKS = __MARKS__, INIT = "__INIT__";
  var vp = document.getElementById('vp'), stage = document.getElementById('stage');
  var img = document.getElementById('img'), ov = document.getElementById('ov');
  var lvl = document.getElementById('lvl');
  var scale = 1, tx = 0, ty = 0, iw = 0, ih = 0, minScale = 0.02;

  function apply(){
    stage.style.transform = 'translate('+tx+'px,'+ty+'px) scale('+scale+')';
    lvl.textContent = Math.round(scale*100) + '%';
  }
  function fit(){
    if(!iw) return;
    var s = Math.min(vp.clientWidth/iw, vp.clientHeight/ih);
    scale = s; minScale = s*0.5;
    tx = (vp.clientWidth - iw*s)/2; ty = (vp.clientHeight - ih*s)/2;
    apply();
  }
  function centreOn(cx, cy, target){
    if(target) scale = target;
    tx = vp.clientWidth/2 - cx*scale;
    ty = vp.clientHeight/2 - cy*scale;
    apply();
  }
  function jump(){
    if(!MARKS.length){ fit(); return; }
    var m = MARKS.find(function(k){return k.role==='primary';}) || MARKS[0];
    centreOn(m.x + m.w/2, m.y + m.h/2, Math.max(scale, 1.1));
  }
  function zoomAt(px, py, factor){
    var ns = Math.max(minScale, Math.min(14, scale*factor));
    // keep the point under the cursor stationary
    tx = px - (px - tx) * (ns/scale);
    ty = py - (py - ty) * (ns/scale);
    scale = ns; apply();
  }

  function drawMarks(){
    ov.innerHTML = '';
    MARKS.forEach(function(m){
      var d = document.createElement('div');
      d.className = 'mk';
      d.style.left = m.x+'px'; d.style.top = m.y+'px';
      d.style.width = m.w+'px'; d.style.height = m.h+'px';
      // Border width is divided by scale so it stays visually constant
      d.style.border = (3/scale)+'px solid '+m.color;
      d.style.boxShadow = '0 0 0 '+(6/scale)+'px '+m.color+'22';
      ov.appendChild(d);
      if(m.label){
        var l = document.createElement('div');
        l.className = 'mklab';
        l.style.left = m.x+'px'; l.style.top = (m.y - 4/scale)+'px';
        l.style.background = m.color;
        l.style.fontSize = Math.max(9, 12/scale)+'px';
        l.style.padding = (1/scale)+'px '+(5/scale)+'px';
        l.textContent = m.label;
        ov.appendChild(l);
      }
    });
  }
  function refresh(){ drawMarks(); }

  img.onload = function(){
    iw = img.naturalWidth; ih = img.naturalHeight;
    ov.style.width = iw+'px'; ov.style.height = ih+'px';
    fit();
    if(INIT === 'marker') jump();
    refresh();
  };
  if(img.complete && img.naturalWidth) img.onload();

  // --- pan ---
  var dragging=false, sx=0, sy=0;
  vp.addEventListener('mousedown', function(e){
    dragging=true; sx=e.clientX-tx; sy=e.clientY-ty; vp.classList.add('grabbing');
  });
  window.addEventListener('mouseup', function(){ dragging=false; vp.classList.remove('grabbing'); });
  window.addEventListener('mousemove', function(e){
    if(!dragging) return;
    tx = e.clientX-sx; ty = e.clientY-sy; apply();
  });
  // --- zoom ---
  vp.addEventListener('wheel', function(e){
    e.preventDefault();
    var r = vp.getBoundingClientRect();
    zoomAt(e.clientX-r.left, e.clientY-r.top, e.deltaY<0 ? 1.15 : 1/1.15);
    refresh();
  }, {passive:false});
  vp.addEventListener('dblclick', function(e){
    var r = vp.getBoundingClientRect();
    zoomAt(e.clientX-r.left, e.clientY-r.top, 1.8); refresh();
  });
  // --- touch (pinch + drag) ---
  var pinch=null;
  vp.addEventListener('touchstart', function(e){
    if(e.touches.length===2){
      pinch = {d: Math.hypot(e.touches[0].clientX-e.touches[1].clientX,
                             e.touches[0].clientY-e.touches[1].clientY)};
    } else if(e.touches.length===1){
      dragging=true; sx=e.touches[0].clientX-tx; sy=e.touches[0].clientY-ty;
    }
  }, {passive:true});
  vp.addEventListener('touchmove', function(e){
    if(pinch && e.touches.length===2){
      var d = Math.hypot(e.touches[0].clientX-e.touches[1].clientX,
                         e.touches[0].clientY-e.touches[1].clientY);
      var r = vp.getBoundingClientRect();
      zoomAt((e.touches[0].clientX+e.touches[1].clientX)/2-r.left,
             (e.touches[0].clientY+e.touches[1].clientY)/2-r.top, d/pinch.d);
      pinch.d = d; refresh(); e.preventDefault();
    } else if(dragging && e.touches.length===1){
      tx = e.touches[0].clientX-sx; ty = e.touches[0].clientY-sy; apply();
    }
  }, {passive:false});
  vp.addEventListener('touchend', function(){ pinch=null; dragging=false; }, {passive:true});

  document.getElementById('zin').onclick=function(){ zoomAt(vp.clientWidth/2, vp.clientHeight/2, 1.4); refresh(); };
  document.getElementById('zout').onclick=function(){ zoomAt(vp.clientWidth/2, vp.clientHeight/2, 1/1.4); refresh(); };
  document.getElementById('fit').onclick=function(){ fit(); refresh(); };
  document.getElementById('one').onclick=function(){
    var cx=(vp.clientWidth/2-tx)/scale, cy=(vp.clientHeight/2-ty)/scale;
    centreOn(cx, cy, 1); refresh();
  };
  document.getElementById('jump').onclick=function(){ jump(); refresh(); };
  window.addEventListener('resize', function(){ fit(); refresh(); });
})();
</script>
"""
    payload = (tpl.replace("__URI__", uri)
                  .replace("__MARKS__", marks_json)
                  .replace("__INIT__", init_mode)
                  .replace("__H__", str(int(height))))
    components.html(payload, height=int(height) + 62, scrolling=False)
    return True


def legend_html(roles=("primary", "upstream", "downstream", "related")) -> str:
    """Small inline legend matching the marker colours."""
    parts = []
    for r in roles:
        color, label = ROLE_STYLES.get(r, ROLE_STYLES["primary"])
        parts.append(
            f'<span style="margin-right:14px;"><span style="display:inline-block;width:11px;'
            f'height:11px;background:{color};border-radius:2px;margin-right:5px;'
            f'vertical-align:middle;"></span><span style="font-size:.78em;color:#5B5470;">'
            f'{label}</span></span>')
    return '<div style="margin:2px 0 6px;">' + "".join(parts) + "</div>"
