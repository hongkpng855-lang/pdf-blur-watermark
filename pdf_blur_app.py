#!/usr/bin/env python3
"""
PDF Blur + Watermark Tool — Web App
=====================================
Upload a PDF, blur regions, add watermarks, download the result.
"""
import os, uuid, io, base64, math, json as _json
from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import fitz  # PyMuPDF
from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = None


def get_session_paths(sid):
    """Get file paths for a session, supporting multi-worker gunicorn."""
    sess_dir = os.path.join(UPLOAD_FOLDER, sid)
    os.makedirs(sess_dir, exist_ok=True)
    return {
        'pdf': os.path.join(sess_dir, 'input.pdf'),
        'originals': os.path.join(sess_dir, 'originals'),
        'processed_dir': os.path.join(sess_dir, 'processed'),
        'meta': os.path.join(sess_dir, 'meta.json'),
    }


def pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()
    return images


def images_to_pdf(images, output_path):
    if not images: return
    if len(images) == 1:
        images[0].save(output_path, "PDF", resolution=150)
    else:
        images[0].save(output_path, "PDF", resolution=150, save_all=True,
                       append_images=images[1:])


def apply_blur(page_img, blur_regions, radius=25):
    img = page_img.copy()
    for region in blur_regions:
        x, y, w, h = region['x'], region['y'], region['w'], region['h']
        if w < 5 or h < 5: continue
        crop = img.crop((x, y, x + w, y + h))
        blurred = crop.filter(ImageFilter.GaussianBlur(radius=radius))
        img.paste(blurred, (x, y))
    return img


def apply_watermark(page_img, wm_config):
    """Apply watermark text tiled diagonally at max size."""
    if not wm_config or not wm_config.get('text'):
        return page_img

    img = page_img.copy()
    txt = wm_config['text']
    opacity = wm_config.get('opacity', 30) / 100.0
    user_size = wm_config.get('size', 80)
    spacing = wm_config.get('spacing', 2.0)
    color = wm_config.get('color', '#888888')

    # Parse color
    color = color.lstrip('#')
    r, g, b = int(color[0:2], 16) if len(color) >= 2 else 0, \
              int(color[2:4], 16) if len(color) >= 4 else 0, \
              int(color[4:6], 16) if len(color) >= 6 else 0

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = min(user_size, img.width // 2)
    try:
        font = ImageFont.truetype(FONT_PATH, font_size) if FONT_PATH else ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw < 10:
        font_size = img.width // 2
        try:
            font = ImageFont.truetype(FONT_PATH, font_size) if FONT_PATH else ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), txt, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Tiled diagonally (-30 deg) across the whole page
    angle = -30
    step_x = int(tw * spacing * 0.9)
    step_y = int(th * spacing * 1.25)

    for ty in range(-step_y, img.height + step_y, step_y):
        for tx in range(-step_x, img.width + step_x, step_x):
            txt_overlay = Image.new('RGBA', (step_x * 2, step_y), (0, 0, 0, 0))
            td = ImageDraw.Draw(txt_overlay)
            td.text((0, 0), txt, font=font, fill=(r, g, b, int(255 * opacity)))
            rotated = txt_overlay.rotate(angle, expand=True, center=(step_x, step_y // 2))
            overlay.paste(rotated, (tx, ty), rotated)

    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


# ══════════════════════════════════════════════════════════════
# HTML (embedded)
# ══════════════════════════════════════════════════════════════
HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDF Tools</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: #0d0d12; color: #e0e0f0;
  height: 100vh; display: flex; flex-direction: column;
}
.header {
  background: #15151e;
  border-bottom: 1px solid #2a2a3a;
}
.tab-bar {
  display: flex; border-bottom: 1px solid #2a2a3a;
}
.tab-bar .tab {
  padding: 8px 18px; font-size: 13px; cursor: pointer;
  color: #8888a0; border-bottom: 2px solid transparent;
  transition: all 0.15s; user-select: none;
}
.tab-bar .tab:hover { color: #e0e0f0; }
.tab-bar .tab.active {
  color: #6c5ce7; border-bottom-color: #6c5ce7;
}
.toolbar {
  padding: 8px 16px; display: flex; align-items: center;
  justify-content: space-between; gap: 10px; flex-wrap: wrap;
}
.toolbar-left { display: flex; align-items: center; gap: 6px; }
.toolbar-right { display: flex; align-items: center; gap: 6px; }

.btn, .toolbar-right button, .toolbar-right label {
  padding: 6px 12px; border-radius: 5px; border: 1px solid #2a2a3a;
  background: #1c1c2a; color: #e0e0f0; cursor: pointer; font-size: 12px;
}
.toolbar-right button:hover, .toolbar-right label:hover { border-color: #6c5ce7; }
.toolbar-right button.primary { background: #6c5ce7; border-color: #6c5ce7; color: #fff; }
.toolbar-right button.primary:disabled { opacity: 0.4; cursor: not-allowed; }
.toolbar-right input[type=file] { display: none; }

.main { flex: 1; display: flex; overflow: hidden; }
.canvas-panel {
  flex: 1; overflow: auto; display: flex;
  justify-content: center; align-items: flex-start; padding: 12px;
  position: relative;
}
.canvas-wrap { position: relative; display: inline-block; }
.canvas-wrap canvas { display: block; }
.canvas-wrap canvas.base { position: relative; }
.canvas-wrap canvas.overlay {
  position: absolute; top: 0; left: 0;
  cursor: crosshair; opacity: 0.4;
}

.sidebar {
  width: 290px; background: #15151e; border-left: 1px solid #2a2a3a;
  display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto;
}
.section { padding: 10px 12px; border-bottom: 1px solid #2a2a3a; }
.section h3 { font-size: 11px; color: #8888a0; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }

.region-list { padding: 6px; max-height: 180px; overflow-y: auto; }
.region-item {
  display: flex; align-items: center; gap: 5px;
  padding: 3px 6px; font-size: 11px; font-family: monospace;
  border-radius: 3px; cursor: pointer;
}
.region-item:hover { background: #1c1c2a; }
.region-item .num { color: #6c5ce7; width: 18px; }
.region-item .del { color: #fd79a8; cursor: pointer; margin-left: auto; padding: 0 4px; }
.region-item .del:hover { color: #ff5252; }

.wm-field { margin-bottom: 6px; }
.wm-field label { display: block; font-size: 11px; color: #8888a0; margin-bottom: 2px; }
.wm-field input, .wm-field select {
  width: 100%; padding: 4px 6px; background: #1c1c2a;
  border: 1px solid #2a2a3a; border-radius: 3px; color: #e0e0f0; font-size: 12px;
}
.wm-field input:focus, .wm-field select:focus { outline: none; border-color: #6c5ce7; }
.wm-row { display: flex; gap: 6px; }
.wm-row .wm-field { flex: 1; }
input[type=range] { width: 100%; height: 4px; -webkit-appearance: none; background: #2a2a3a; border-radius: 2px; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #6c5ce7; cursor: pointer; }
.range-label { display: flex; justify-content: space-between; font-size: 10px; color: #8888a0; }

.status-bar {
  padding: 5px 12px; background: #15151e; border-top: 1px solid #2a2a3a;
  font-size: 11px; color: #8888a0;
}
.toast {
  position: fixed; bottom: 50px; left: 50%; transform: translateX(-50%);
  background: #6c5ce7; color: #fff; padding: 7px 18px;
  border-radius: 5px; font-size: 12px; z-index: 200;
  display: none; box-shadow: 0 4px 16px rgba(108,92,231,0.4);
}
.toast.error { background: #fd79a8; }
.empty-msg { position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#444;font-size:20px;text-align:center;pointer-events:none; }
</style>
</head>
<body>

<div class="header">
  <div class="tab-bar">
    <div class="tab active" onclick="switchTab('blur')" id="tabBlur">🔒 Blur + Watermark</div>
    <div class="tab" onclick="switchTab('word')" id="tabWord">📄 PDF → Word</div>
  </div>
  <div class="toolbar">
    <div class="toolbar-left">
      <label for="fileInput" class="btn">📁 Open PDF</label>
      <input type="file" id="fileInput" accept=".pdf">
    </div>
    <div class="toolbar-right" id="toolbarBlur">
      <button onclick="analyzePDF()" id="analyzeBtn" disabled>🔍 Analyze</button>
      <button onclick="processPDF()" class="primary" id="processBtn" disabled>⚡ Process</button>
      <button onclick="downloadPDF()" id="downloadBtn" disabled>⬇ Download</button>
    </div>
    <div class="toolbar-right" id="toolbarWord" style="display:none">
      <button onclick="convertToWord()" class="primary" id="convertBtn" disabled>📄 Convert to Word</button>
    </div>
  </div>
</div>

<div class="main">
  <div class="canvas-panel" id="canvasPanel">
    <div class="canvas-wrap" id="canvasWrap">
      <canvas id="baseCanvas" class="base"></canvas>
      <canvas id="overlayCanvas" class="overlay"></canvas>
    </div>
    <div class="empty-msg" id="emptyMsg">📄<br>Upload a PDF</div>
  </div>

  <div class="sidebar" id="sidebar" style="display:none">
    <!-- Pages (shown in both modes) -->
    <div class="section" id="pagesSection">
      <h3>📄 Pages</h3>
      <div style="display:flex;gap:3px;flex-wrap:wrap;margin-top:4px" id="pageThumbs"></div>
    </div>

    <!-- Blur controls (shown in blur mode) -->
    <div id="sidebarBlur">
      <div class="section">
        <h3>🔍 Blur</h3>
        <p style="font-size:11px;color:#666;margin-bottom:4px">Drag on the image to add regions</p>
        <div style="margin-bottom:4px">
          <div class="range-label"><span>Intensity</span><span id="blurVal">25</span></div>
          <input type="range" id="blurIntensity" min="5" max="50" value="25">
        </div>
        <div class="region-list" id="regionList">
          <div style="color:#555;font-size:11px;text-align:center;padding:10px">No regions yet</div>
        </div>
      </div>

      <!-- Watermark -->
      <div class="section">
        <h3>💧 Watermark <span onclick="clearWatermark()" style="color:#fd79a8;cursor:pointer;font-size:12px;float:right">✖ Clear</span></h3>
      <div class="wm-field">
        <label>Text</label>
        <input type="text" id="wmText" value="ESGov">
      </div>
      <div class="wm-field">
        <label>Size: <span id="wmSizeVal" style="color:#6c5ce7">80</span></label>
        <input type="range" id="wmSize" min="20" max="200" value="80">
      </div>
      <div class="wm-field">
        <label>Spacing: <span id="wmSpacingVal" style="color:#6c5ce7">2.0</span></label>
        <input type="range" id="wmSpacing" min="0.5" max="5.0" step="0.1" value="2.0">
      </div>
      <div class="wm-row">
        <div class="wm-field">
          <label>Opacity</label>
          <select id="wmOpacity">
            <option value="10">10%</option>
            <option value="20">20%</option>
            <option value="30" selected>30%</option>
            <option value="50">50%</option>
            <option value="70">70%</option>
          </select>
        </div>
        <div class="wm-field">
          <label>Color</label>
          <div style="display:flex;gap:2px;flex-wrap:wrap">
            <span onclick="document.getElementById('wmColor').value='#888'" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#888;cursor:pointer;border:2px solid transparent"></span>
            <span onclick="document.getElementById('wmColor').value='#f00'" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#f00;cursor:pointer;border:2px solid transparent"></span>
            <span onclick="document.getElementById('wmColor').value='#00f'" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#00f;cursor:pointer;border:2px solid transparent"></span>
            <span onclick="document.getElementById('wmColor').value='#0a0'" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#0a0;cursor:pointer;border:2px solid transparent"></span>
            <input type="color" id="wmColor" value="#888" style="width:22px;height:18px;padding:0;border:1px solid #2a2a3a;background:#1c1c2a;cursor:pointer;border-radius:3px">
          </div>
        </div>
      </div>
    </div>

    <!-- PDF → Word controls (shown in word mode) -->
    <div id="sidebarWord" style="display:none">
      <div class="section">
        <h3>📄 PDF → Word</h3>
        <p style="font-size:12px;color:#aaa;margin-top:4px;line-height:1.5">
          Convert your PDF into an editable Word document (.docx).
        </p>
        <p style="font-size:12px;color:#888;margin-top:8px;line-height:1.5">
          ✅ Text content preserved with original fonts, sizes, bold/italic<br>
          ✅ Multi-column layout detection<br>
          ✅ Image extraction (where possible)<br>
          ✅ Page size maintained
        </p>
        <p style="font-size:11px;color:#666;margin-top:8px;font-style:italic">
          Complex layouts (tables, overlapping elements) may have variations.
        </p>
      </div>
    </div>
  </div>
</div>

<div class="status-bar"><span id="statusText">Open a PDF to get started</span></div>
<div class="toast" id="toast"></div>

<script>
const state = { sessionId: null, pages: [], currentPage: 0, regions: {}, scale: 1 };
const baseCanvas = document.getElementById('baseCanvas');
const overlayCanvas = document.getElementById('overlayCanvas');
const overlayCtx = overlayCanvas.getContext('2d');
let isDrawing = false, dx = 0, dy = 0;

document.getElementById('fileInput').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('pdf', f);
  try {
    const r = await fetch('/upload', { method:'POST', body:fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.sessionId = d.session_id; state.pages = d.pages;
    state.currentPage = 0; state.regions = {}; detectedBlocks = {};
    document.getElementById('emptyMsg').style.display = 'none';
    document.getElementById('sidebar').style.display = 'flex';
    document.getElementById('processBtn').disabled = false;
    document.getElementById('analyzeBtn').disabled = false;
    document.getElementById('convertBtn').disabled = false;
    renderThumbs(); renderPage(0);
    status(d.pages.length + ' pages loaded');
    toast('PDF loaded: ' + f.name);
  } catch(e) { toast('Error: ' + e.message, true); }
});

function renderPage(idx) {
  const page = state.pages[idx];
  if (!page) return;
  state.currentPage = idx;
  const panel = document.getElementById('canvasPanel');
  const s = Math.min((panel.clientWidth-24)/page.w, (panel.clientHeight-24)/page.h, 1.5);
  state.scale = s;
  baseCanvas.width = page.w; baseCanvas.height = page.h;
  baseCanvas.style.width = (page.w*s)+'px'; baseCanvas.style.height = (page.h*s)+'px';
  overlayCanvas.width = page.w; overlayCanvas.height = page.h;
  overlayCanvas.style.width = (page.w*s)+'px'; overlayCanvas.style.height = (page.h*s)+'px';
  const img = new Image();
  img.onload = () => { baseCanvas.getContext('2d').drawImage(img,0,0); redrawOverlay(); if (Object.keys(detectedBlocks).length) renderDetectedBlocks(); };
  img.src = page.dataUrl;
  status('Page '+(idx+1)+' of '+state.pages.length);
  updateRegionList();
  updateThumbs();
}

function renderThumbs() {
  const c = document.getElementById('pageThumbs');
  c.innerHTML = '';
  state.pages.forEach((p,i) => {
    const t = document.createElement('div');
    t.style.cssText = 'width:36px;height:48px;border:2px solid #2a2a3a;border-radius:3px;overflow:hidden;cursor:pointer;background-size:cover;background-position:center;background-image:url('+p.dataUrl+')';
    t.onclick = () => renderPage(i);
    t.dataset.idx = i;
    c.appendChild(t);
  });
}
function updateThumbs() {
  document.getElementById('pageThumbs').childNodes.forEach(t => {
    t.style.borderColor = parseInt(t.dataset.idx) === state.currentPage ? '#6c5ce7' : '#2a2a3a';
  });
}

// Region drawing
overlayCanvas.addEventListener('mousedown', e => {
  const r = overlayCanvas.getBoundingClientRect(), s = state.scale;
  dx = (e.clientX - r.left) / s; dy = (e.clientY - r.top) / s;
  isDrawing = true;
});
overlayCanvas.addEventListener('mousemove', e => {
  if (!isDrawing) return;
  const r = overlayCanvas.getBoundingClientRect(), s = state.scale;
  const cx = (e.clientX - r.left) / s, cy = (e.clientY - r.top) / s;
  const x = Math.min(dx,cx), y = Math.min(dy,cy), w = Math.abs(cx-dx), h = Math.abs(cy-dy);
  redrawOverlay();
  overlayCtx.strokeStyle = '#6c5ce7'; overlayCtx.lineWidth = 2/s;
  overlayCtx.setLineDash([4/s,4/s]);
  overlayCtx.strokeRect(x,y,w,h);
  overlayCtx.fillStyle = 'rgba(108,92,231,0.15)'; overlayCtx.fillRect(x,y,w,h);
});
overlayCanvas.addEventListener('mouseup', e => {
  if (!isDrawing) return; isDrawing = false; overlayCtx.setLineDash([]);
  const r = overlayCanvas.getBoundingClientRect(), s = state.scale;
  const ex = (e.clientX-r.left)/s, ey = (e.clientY-r.top)/s;
  const x = Math.min(dx,ex), y = Math.min(dy,ey), w = Math.abs(ex-dx), h = Math.abs(ey-dy);
  if (w < 10 || h < 10) { redrawOverlay(); return; }
  const pi = state.currentPage;
  if (!state.regions[pi]) state.regions[pi] = [];
  state.regions[pi].push({id:Date.now(), x:Math.round(x), y:Math.round(y), w:Math.round(w), h:Math.round(h)});
  redrawOverlay(); updateRegionList();
});

function redrawOverlay() {
  const s = state.scale;
  overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  const rs = state.regions[state.currentPage] || [];
  rs.forEach((r,i) => {
    overlayCtx.strokeStyle = '#ffd740'; overlayCtx.lineWidth = 2/s;
    overlayCtx.strokeRect(r.x, r.y, r.w, r.h);
    overlayCtx.fillStyle = 'rgba(255,215,64,0.12)'; overlayCtx.fillRect(r.x, r.y, r.w, r.h);
    overlayCtx.fillStyle = '#ffd740';
    overlayCtx.font = Math.max(9, 12/s)+'px monospace';
    overlayCtx.fillText('#'+(i+1), r.x+3/s, r.y+11/s);
  });
}

function updateRegionList() {
  const rs = state.regions[state.currentPage] || [];
  const el = document.getElementById('regionList');
  if (!rs.length) {
    el.innerHTML = '<div style="color:#555;font-size:11px;text-align:center;padding:8px">Drag on image to add</div>';
    return;
  }
  el.innerHTML = rs.map((r,i) =>
    '<div class="region-item"><span class="num">#'+(i+1)+'</span><span>('+r.x+','+r.y+') '+r.w+'\u00d7'+r.h+'</span><span class="del" onclick="delRegion('+i+')">\u2716</span></div>'
  ).join('');
}

function delRegion(i) {
  const pi = state.currentPage;
  if (state.regions[pi]) state.regions[pi].splice(i,1);
  redrawOverlay(); updateRegionList();
}

// Process (blur + watermark)
async function processPDF() {
  const btn = document.getElementById('processBtn');
  btn.disabled = true; btn.textContent = '⏳ Processing...';
  try {
    const intensity = parseInt(document.getElementById('blurIntensity').value);
    const wmList = [];
    const text = document.getElementById('wmText').value.trim();
    if (text) {
      wmList.push({
        text: text,
        size: parseInt(document.getElementById('wmSize').value),
        spacing: parseFloat(document.getElementById('wmSpacing').value),
        opacity: parseInt(document.getElementById('wmOpacity').value),
        color: document.getElementById('wmColor').value,
      });
    }
    const r = await fetch('/process', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        session_id: state.sessionId,
        regions: state.regions,
        radius: intensity,
        watermarks: wmList
      })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.pages = d.pages;
    renderPage(state.currentPage);
    document.getElementById('downloadBtn').disabled = false;
    toast('✅ Processed!');
  } catch(e) { toast('Error: '+e.message, true); }
  finally { btn.disabled = false; btn.textContent = '⚡ Process'; }
}

// Analyze PDF — detect text blocks
let detectedBlocks = {};

async function analyzePDF() {
  const btn = document.getElementById('analyzeBtn');
  btn.disabled = true; btn.textContent = '⏳ Analyzing...';
  try {
    const r = await fetch('/analyze', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: state.sessionId})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    detectedBlocks = d.blocks || {};
    renderDetectedBlocks();
    const total = Object.values(detectedBlocks).reduce((a,b) => a + b.length, 0);
    toast('🔍 ' + total + ' text blocks detected. Click a block to add to blur.');
    status(total + ' text blocks found');
  } catch(e) { toast('Error: '+e.message, true); }
  finally { btn.disabled = false; btn.textContent = '🔍 Analyze'; }
}

function renderDetectedBlocks() {
  const s = state.scale;
  const ctx = overlayCanvas.getContext('2d');
  const blocks = detectedBlocks[state.currentPage] || [];
  // Redraw blur regions first
  redrawOverlay();
  // Then draw detected blocks
  ctx.globalAlpha = 0.3;
  blocks.forEach((b, i) => {
    ctx.fillStyle = '#00ff88';
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.strokeStyle = '#00ff88';
    ctx.lineWidth = 1.5/s;
    ctx.setLineDash([]);
    ctx.strokeRect(b.x, b.y, b.w, b.h);
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = '#00ff88';
    ctx.font = Math.max(8, 10/s)+'px monospace';
    ctx.fillText('📄'+(i+1), b.x+2/s, b.y+10/s);
    ctx.globalAlpha = 0.3;
  });
  ctx.globalAlpha = 1.0;
  // Make blocks clickable via overlay click
}

// Intercept overlay click for detected blocks
overlayCanvas.addEventListener('click', e => {
  if (isDrawing) return;
  const r = overlayCanvas.getBoundingClientRect(), s = state.scale;
  const cx = (e.clientX - r.left) / s, cy = (e.clientY - r.top) / s;
  const blocks = detectedBlocks[state.currentPage] || [];
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (cx >= b.x && cx <= b.x + b.w && cy >= b.y && cy <= b.y + b.h) {
      // Add to blur regions
      const pi = state.currentPage;
      if (!state.regions[pi]) state.regions[pi] = [];
      state.regions[pi].push({id: Date.now(), x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h)});
      // Remove from detected blocks so it doesn't get added again
      blocks.splice(i, 1);
      redrawOverlay();
      renderDetectedBlocks();
      updateRegionList();
      toast('➕ Block added to blur');
      break;
    }
  }
});

async function downloadPDF() {
  try {
    const r = await fetch('/download', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: state.sessionId})
    });
    if (!r.ok) throw new Error('Download failed');
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'processed_output.pdf';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('✅ Downloaded!');
  } catch(e) { toast('Error: '+e.message, true); }
}

document.getElementById('blurIntensity').addEventListener('input', function() {
  document.getElementById('blurVal').textContent = this.value;
});

document.getElementById('wmSize').addEventListener('input', function() {
  document.getElementById('wmSizeVal').textContent = this.value;
});
document.getElementById('wmSpacing').addEventListener('input', function() {
  document.getElementById('wmSpacingVal').textContent = parseFloat(this.value).toFixed(1);
});

function clearWatermark() {
  document.getElementById('wmText').value = '';
  document.getElementById('wmSize').value = 80;
  document.getElementById('wmSizeVal').textContent = '80';
  document.getElementById('wmSpacing').value = 2.0;
  document.getElementById('wmSpacingVal').textContent = '2.0';
  document.getElementById('wmOpacity').value = '30';
  document.getElementById('wmColor').value = '#888';
}

function toast(msg, err) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = 'toast'+(err?' error':'');
  el.style.display = 'block';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.style.display = 'none', 2500);
}
function status(msg) { document.getElementById('statusText').textContent = msg; }

// Tab switching
let activeTab = 'blur';
function switchTab(tab) {
  activeTab = tab;
  document.getElementById('tabBlur').className = 'tab' + (tab === 'blur' ? ' active' : '');
  document.getElementById('tabWord').className = 'tab' + (tab === 'word' ? ' active' : '');
  document.getElementById('toolbarBlur').style.display = tab === 'blur' ? '' : 'none';
  document.getElementById('toolbarWord').style.display = tab === 'word' ? '' : 'none';
  document.getElementById('sidebarBlur').style.display = tab === 'blur' ? '' : 'none';
  document.getElementById('sidebarWord').style.display = tab === 'word' ? '' : 'none';
  // Show/hide overlay interactivity
  overlayCanvas.style.cursor = tab === 'blur' ? 'crosshair' : 'default';
  overlayCanvas.style.opacity = tab === 'blur' ? '0.4' : '0';
}

// PDF → Word conversion
async function convertToWord() {
  const btn = document.getElementById('convertBtn');
  btn.disabled = true; btn.textContent = '⏳ Converting...';
  try {
    const r = await fetch('/to-word', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: state.sessionId})
    });
    if (!r.ok) {
      const d = await r.json();
      throw new Error(d.error || 'Conversion failed');
    }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'converted.docx';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('✅ Word document downloaded!');
  } catch(e) { toast('Error: '+e.message, true); }
  finally { btn.disabled = false; btn.textContent = '📄 Convert to Word'; }
}

window.addEventListener('resize', () => { if (state.pages.length) renderPage(state.currentPage); });
</script>
</body>
</html>
'''


# ══════════════════════════════════════════════════════════════
# PDF → Word conversion
# ══════════════════════════════════════════════════════════════

def pdf_to_word(pdf_path, output_path):
    """Convert PDF to an editable Word document, preserving layout & formatting."""
    from collections import defaultdict

    doc = Document()

    # Set default font
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(11)

    pdf = fitz.open(pdf_path)

    for page_num in range(len(pdf)):
        page = pdf.load_page(page_num)

        # --- Page setup ---
        rect = page.rect
        if page_num > 0:
            doc.add_section()
        section = doc.sections[-1]
        section.page_width = Pt(rect.width)
        section.page_height = Pt(rect.height)
        section.top_margin = Pt(rect.y0) if rect.y0 > 0 else Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Pt(rect.x0) if rect.x0 > 0 else Cm(1.5)
        section.right_margin = Cm(1.5)

        # --- Extract images ---
        image_list = []
        try:
            for img_index in range(len(page.get_images())):
                xref = page.get_images()[img_index][0]
                base_image = pdf.extract_image(xref)
                img_data = base_image["image"]
                img_ext = base_image["ext"]
                # Save image temporarily
                img_path = os.path.join(os.path.dirname(output_path), f'_page{page_num}_img{img_index}.{img_ext}')
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                # Find where this image appears on the page
                for b in page.get_image_bbox(xref):
                    image_list.append({
                        'path': img_path,
                        'bbox': b  # [x0, y0, x1, y1]
                    })
                    break
        except:
            pass

        # --- Extract text blocks with formatting ---
        text_dict = page.get_text("dict")

        # Collect all spans with position info
        spans = []
        for block in text_dict.get("blocks", []):
            if block["type"] == 0:  # text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        bbox = span["bbox"]
                        spans.append({
                            'text': span["text"],
                            'x0': bbox[0], 'y0': bbox[1],
                            'x1': bbox[2], 'y1': bbox[3],
                            'font': span["font"],
                            'size': span["size"],
                            'flags': span["flags"],
                            'color': span.get("color", 0),
                        })

        if not spans:
            # Fallback: get plain text
            text = page.get_text("text")
            if text.strip():
                for line in text.split('\n'):
                    p = doc.add_paragraph()
                    p.add_run(line.strip() or ' ')
            continue

        # Sort spans by vertical position, then horizontal
        spans.sort(key=lambda s: (s['y0'], s['x0']))

        # Group spans into "lines" by close y-position (within 3pt tolerance)
        lines = []
        current_line = []
        current_y = None

        for s in spans:
            if current_y is None or abs(s['y0'] - current_y) <= 3:
                current_line.append(s)
                if current_y is None:
                    current_y = s['y0']
                else:
                    current_y = min(current_y, s['y0'])
            else:
                if current_line:
                    current_line.sort(key=lambda x: x['x0'])
                    lines.append(current_line)
                current_line = [s]
                current_y = s['y0']

        if current_line:
            current_line.sort(key=lambda x: x['x0'])
            lines.append(current_line)

        # --- Group lines into columns (if multi-column detected) ---
        # Simple column detection: check if there's a wide empty vertical strip
        if lines:
            all_x0 = [l[0]['x0'] for l in lines if l]
            if all_x0:
                min_x_all = min(all_x0)
                max_x_all = max(l[-1]['x1'] for l in lines if l)
                page_w = rect.width
                # If there are two clusters of x0 values with a large gap, it's multi-column
                x0_vals = sorted(set(int(x) for x in all_x0))
                gaps = [(x0_vals[i+1] - x0_vals[i]) for i in range(len(x0_vals)-1)]
                big_gaps = [g for g in gaps if g > page_w * 0.1]

                if big_gaps and len(x0_vals) > 2:
                    # Multi-column — group lines into columns
                    # Find column boundaries
                    col_threshold = page_w * 0.1
                    cols = []
                    current_col_lines = []
                    col_right = None
                    for line in lines:
                        lx0 = line[0]['x0']
                        if col_right is None or lx0 - col_right > col_threshold:
                            if current_col_lines:
                                cols.append(current_col_lines)
                            current_col_lines = [line]
                            col_right = max(s['x1'] for s in line)
                        else:
                            current_col_lines.append(line)
                            col_right = max(col_right, max(s['x1'] for s in line))
                    if current_col_lines:
                        cols.append(current_col_lines)

                    # Render columns side by side using a table
                    if len(cols) > 1:
                        n_cols = len(cols)
                        col_widths = []
                        for c in cols:
                            c_min_x = min(l[0]['x0'] for l in c if l)
                            c_max_x = max(l[-1]['x1'] for l in c if l)
                            col_widths.append(c_max_x - c_min_x)
                        total_col_w = sum(col_widths)
                        if total_col_w > 0:
                            # Normalise widths to percentage
                            col_pcts = [w / total_col_w for w in col_widths]
                        else:
                            col_pcts = [1.0 / n_cols] * n_cols

                        # Create table
                        max_rows = max(len(c) for c in cols)
                        table = doc.add_table(rows=max_rows, cols=n_cols)
                        table.style = 'Table Grid'

                        for ci, col_lines in enumerate(cols):
                            for ri, line in enumerate(col_lines):
                                cell = table.cell(ri, ci)
                                # Clear default paragraph
                                cell.paragraphs[0].clear()
                                p = cell.paragraphs[0]
                                for span in line:
                                    run = p.add_run(span['text'] + ' ')
                                    run.font.size = Pt(span['size'])
                                    try:
                                        run.font.name = span['font']
                                    except:
                                        pass
                                    if span['flags'] & 2:
                                        run.font.italic = True
                                    if span['flags'] & 4:
                                        run.font.bold = True
                                    if span.get('color', 0):
                                        c_val = span['color']
                                        r = (c_val >> 16) & 0xFF
                                        g = (c_val >> 8) & 0xFF
                                        b = c_val & 0xFF
                                        try:
                                            run.font.color.rgb = RGBColor(r, g, b)
                                        except:
                                            pass
                        continue  # skip regular paragraph rendering

        # --- Render lines as paragraphs ---
        for line in lines:
            if not line:
                continue
            p = doc.add_paragraph()

            # Calculate left indent from first span's x position
            min_x = min(s['x0'] for s in line)
            # Convert points to inches (1pt = 1/72 in)
            left_indent_inches = min_x / 72.0
            if left_indent_inches > 0:
                p.paragraph_format.left_indent = Inches(left_indent_inches)

            # Calculate line spacing based on font size
            max_size = max(s['size'] for s in line)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(max_size * 0.2)
            p.paragraph_format.line_spacing = Pt(max_size * 1.3)

            # Alignment detection: if text is centred, set center alignment
            page_center = rect.width / 2
            if min_x > page_center * 0.4 and min_x < page_center * 0.6:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Add spans as runs
            for span in line:
                run = p.add_run(span['text'])
                run.font.size = Pt(span['size'])
                try:
                    run.font.name = span['font']
                except:
                    pass
                if span['flags'] & 2:
                    run.font.italic = True
                if span['flags'] & 4:
                    run.font.bold = True
                # Superscript/subscript detection
                if span['flags'] & 1:
                    run.font.superscript = True

                # Color
                color_val = span.get('color', 0)
                if color_val and color_val != 0:
                    r = (color_val >> 16) & 0xFF
                    g = (color_val >> 8) & 0xFF
                    b = color_val & 0xFF
                    try:
                        run.font.color.rgb = RGBColor(r, g, b)
                    except:
                        pass

        # --- Insert images at approximate positions ---
        for img_info in image_list:
            img_path = img_info['path']
            bbox = img_info['bbox']
            try:
                # Insert image at the approximate location
                from docx.oxml.ns import qn
                p = doc.add_paragraph()
                run = p.add_run()
                # Position image at the right location using left_indent
                left_indent = bbox[0] / 72.0
                if left_indent > 0:
                    p.paragraph_format.left_indent = Inches(left_indent)

                inline_shape = run.add_picture(img_path,
                    width=Inches((bbox[2] - bbox[0]) / 72.0))
            except:
                pass

        # Clean up temp image files
        for img_info in image_list:
            try:
                os.remove(img_info['path'])
            except:
                pass

    pdf.close()

    # Clean up empty paragraphs at end
    for p in doc.paragraphs:
        if not p.text.strip() and not p.runs:
            p._element.getparent().remove(p._element)

    doc.save(output_path)


# ══════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return HTML


@app.route('/upload', methods=['POST'])
def upload():
    if 'pdf' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['pdf']
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files accepted'}), 400
    session_id = uuid.uuid4().hex[:12]
    paths = get_session_paths(session_id)
    file.save(paths['pdf'])
    images = pdf_to_images(paths['pdf'])
    pages = []
    for i, img in enumerate(images):
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        pages.append({
            'index': i,
            'dataUrl': f'data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}',
            'w': img.width, 'h': img.height
        })
    # Save meta
    with open(paths['meta'], 'w') as f:
        _json.dump({'original_name': file.filename}, f)

    # Save originals
    originals_dir = paths['originals']
    if os.path.exists(originals_dir):
        import shutil
        shutil.rmtree(originals_dir)
    os.makedirs(originals_dir, exist_ok=True)
    for i, img in enumerate(images):
        img.save(os.path.join(originals_dir, f'{i}.png'))

    # Save initial preview copies to processed dir
    processed_dir = paths['processed_dir']
    if os.path.exists(processed_dir):
        import shutil
        shutil.rmtree(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    for i, img in enumerate(images):
        img.save(os.path.join(processed_dir, f'{i}.png'))
    return jsonify({'session_id': session_id, 'pages': pages})


@app.route('/analyze', methods=['POST'])
def analyze():
    """Detect text blocks in the PDF."""
    data = request.json
    sid = data.get('session_id')
    paths = get_session_paths(sid)
    if not os.path.exists(paths['pdf']):
        return jsonify({'error': 'Session not found'}), 404

    doc = fitz.open(paths['pdf'])
    blocks_per_page = {}
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # Get text blocks with coordinates
        text_blocks = page.get_text("blocks")
        blocks = []
        for b in text_blocks:
            if b[6] == 0:  # type 0 = text block
                x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
                # Scale by 2x to match image coordinates
                x0 *= 2; y0 *= 2; x1 *= 2; y1 *= 2
                w = x1 - x0
                h = y1 - y0
                if w > 10 and h > 5:  # skip tiny fragments
                    blocks.append({
                        'x': round(x0), 'y': round(y0),
                        'w': round(w), 'h': round(h),
                        'text': b[4][:80]  # first 80 chars for reference
                    })
        blocks_per_page[str(page_num)] = blocks
    doc.close()
    return jsonify({'blocks': blocks_per_page})


@app.route('/process', methods=['POST'])
def process():
    data = request.json
    sid = data.get('session_id')
    paths = get_session_paths(sid)
    if not os.path.exists(paths['pdf']):
        return jsonify({'error': 'Session not found'}), 404
    radius = data.get('radius', 25)
    regions = data.get('regions', {})
    watermarks = data.get('watermarks', [])

    # Load original images (always from originals, so re-process doesn't stack)
    originals_dir = paths['originals']
    if not os.path.exists(originals_dir):
        return jsonify({'error': 'Session not found'}), 404

    images = []
    for f in sorted(os.listdir(originals_dir), key=lambda x: int(x.split('.')[0])):
        if f.endswith('.png'):
            images.append(Image.open(os.path.join(originals_dir, f)))

    if not images:
        return jsonify({'error': 'No images found'}), 404

    processed_dir = paths['processed_dir']
    os.makedirs(processed_dir, exist_ok=True)
    processed_images = []
    for pi, img in enumerate(images):
        img = img.copy()
        pr = regions.get(str(pi), [])
        if pr:
            img = apply_blur(img, pr, radius)
        for wm in watermarks:
            if wm.get('text'):
                img = apply_watermark(img, wm)
        img.save(os.path.join(processed_dir, f'{pi}.png'))
        processed_images.append(img)

    # Return previews
    pages = []
    for i, img in enumerate(processed_images):
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        pages.append({
            'index': i,
            'dataUrl': f'data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}',
            'w': img.width, 'h': img.height
        })
    return jsonify({'pages': pages})


@app.route('/download', methods=['POST'])
def download():
    data = request.json
    sid = data.get('session_id')
    paths = get_session_paths(sid)
    if not os.path.exists(paths['pdf']):
        return jsonify({'error': 'Session not found'}), 404

    # Load images from processed dir (always the latest version)
    processed_dir = paths['processed_dir']
    images = []
    if os.path.exists(processed_dir):
        for f in sorted(os.listdir(processed_dir), key=lambda x: int(x.split('.')[0])):
            if f.endswith('.png'):
                images.append(Image.open(os.path.join(processed_dir, f)))

    if not images:
        return jsonify({'error': 'No images found'}), 404

    # Get original filename for download name
    orig_name = 'processed_output.pdf'
    try:
        with open(paths['meta']) as f:
            meta = _json.load(f)
            orig_name = meta.get('original_name', 'processed_output.pdf')
            if orig_name.lower().endswith('.pdf'):
                orig_name = orig_name[:-4] + '_blur_watermark.pdf'
            else:
                orig_name = orig_name + '_blur_watermark.pdf'
    except:
        pass

    output = os.path.join(paths['processed_dir'], 'output.pdf')
    images_to_pdf(images, output)
    return send_file(output, as_attachment=True,
                     download_name=orig_name,
                     mimetype='application/pdf')


@app.route('/to-word', methods=['POST'])
def to_word():
    """Convert uploaded PDF to editable Word document."""
    data = request.json
    sid = data.get('session_id')
    paths = get_session_paths(sid)
    if not os.path.exists(paths['pdf']):
        return jsonify({'error': 'Session not found'}), 404

    # Get original filename for download name
    orig_name = 'converted.docx'
    try:
        with open(paths['meta']) as f:
            meta = _json.load(f)
            orig_name = meta.get('original_name', 'document.docx')
            if orig_name.lower().endswith('.pdf'):
                orig_name = orig_name[:-4] + '.docx'
            else:
                orig_name = orig_name + '.docx'
    except:
        pass

    try:
        output_path = os.path.join(paths['processed_dir'], 'converted.docx')
        pdf_to_word(paths['pdf'], output_path)
        if not os.path.exists(output_path):
            return jsonify({'error': 'Conversion failed - no output file'}), 500
        return send_file(output_path, as_attachment=True,
                         download_name=orig_name,
                         mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    except Exception as e:
        return jsonify({'error': f'Conversion error: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8777))
    print('╔══════════════════════════════════════╗')
    print('║  PDF Blur + Watermark Tool           ║')
    print(f'║  http://0.0.0.0:{port:<39}║')
    print('╚══════════════════════════════════════╝')
    app.run(host='0.0.0.0', port=port, debug=True)
