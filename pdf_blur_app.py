#!/usr/bin/env python3
"""
PDF Blur + Watermark Tool — Web App
=====================================
Upload a PDF, blur regions, add watermarks, download the result.
"""
import os, uuid, io, base64, math
from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import fitz  # PyMuPDF

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
        'processed_dir': os.path.join(sess_dir, 'processed'),
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
    color = wm_config.get('color', '#888888')

    # Parse color
    color = color.lstrip('#')
    r, g, b = int(color[0:2], 16) if len(color) >= 2 else 0, \
              int(color[2:4], 16) if len(color) >= 4 else 0, \
              int(color[4:6], 16) if len(color) >= 6 else 0

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Max font size that fits the page width
    font_size = max(48, img.width // 3)
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
    step_x = int(tw * 1.8)
    step_y = int(th * 2.5)

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
<title>PDF Blur + Watermark</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: #0d0d12; color: #e0e0f0;
  height: 100vh; display: flex; flex-direction: column;
}
.header {
  background: #15151e; padding: 10px 16px;
  border-bottom: 1px solid #2a2a3a;
  display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
}
.header h1 { font-size: 16px; white-space: nowrap; }
.header h1 span { color: #6c5ce7; }
.actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.actions button, .actions label {
  padding: 6px 12px; border-radius: 5px; border: 1px solid #2a2a3a;
  background: #1c1c2a; color: #e0e0f0; cursor: pointer; font-size: 12px;
}
.actions button:hover, .actions label:hover { border-color: #6c5ce7; }
.actions button.primary { background: #6c5ce7; border-color: #6c5ce7; color: #fff; }
.actions button.primary:disabled { opacity: 0.4; cursor: not-allowed; }
.actions input[type=file] { display: none; }

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
  <h1>🔒 <span>PDF Blur + Watermark</span></h1>
  <div class="actions">
    <label for="fileInput">📁 Open PDF</label>
    <input type="file" id="fileInput" accept=".pdf">
    <button onclick="processPDF()" class="primary" id="processBtn" disabled>⚡ Process</button>
    <button onclick="downloadPDF()" id="downloadBtn" disabled>⬇ Download</button>
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
    <!-- Pages -->
    <div class="section">
      <h3>📄 Pages</h3>
      <div style="display:flex;gap:3px;flex-wrap:wrap;margin-top:4px" id="pageThumbs"></div>
    </div>

    <!-- Blur -->
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
      <h3>💧 Watermark</h3>
      <div id="wmList"></div>
      <button onclick="addWatermark()" style="width:100%;padding:5px;margin-top:6px;border-radius:4px;border:1px dashed #2a2a3a;background:transparent;color:#6c5ce7;cursor:pointer;font-size:12px">+ Add Watermark</button>
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

let wmCounter = 0;

function wmTemplate(idx) {
  return '<div class="wm-entry" data-idx="'+idx+'" style="border:1px solid #2a2a3a;border-radius:4px;padding:6px;margin-bottom:6px">'+
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'+
      '<span style="font-size:11px;color:#6c5ce7;font-weight:bold">#'+(idx+1)+'</span>'+
      '<span onclick="removeWatermark('+idx+')" style="color:#fd79a8;cursor:pointer;font-size:13px">✖</span>'+
    '</div>'+
    '<div class="wm-field"><label>Text</label><input type="text" class="wm-text" value="CONFIDENTIAL"></div>'+
    '<div style="display:flex;gap:6px">'+
      '<div class="wm-field" style="flex:1"><label>Opacity</label><select class="wm-opacity">'+
        '<option value="10">10%</option><option value="20">20%</option><option value="30" selected>30%</option>'+
        '<option value="50">50%</option><option value="70">70%</option>'+
      '</select></div>'+
      '<div class="wm-field" style="flex:1"><label>Color</label>'+
        '<div style="display:flex;gap:2px;flex-wrap:wrap">'+
          '<span onclick="setWmIdx('+idx+',\'#888\')" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#888;cursor:pointer;border:2px solid transparent"></span>'+
          '<span onclick="setWmIdx('+idx+',\'#f00\')" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#f00;cursor:pointer;border:2px solid transparent"></span>'+
          '<span onclick="setWmIdx('+idx+',\'#00f\')" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#00f;cursor:pointer;border:2px solid transparent"></span>'+
          '<span onclick="setWmIdx('+idx+',\'#0a0\')" style="display:inline-block;width:18px;height:18px;border-radius:3px;background:#0a0;cursor:pointer;border:2px solid transparent"></span>'+
          '<input type="color" class="wm-color" value="#888" style="width:20px;height:18px;padding:0;border:1px solid #2a2a3a;background:#1c1c2a;cursor:pointer;border-radius:3px">'+
        '</div>'+
      '</div>'+
    '</div>'+
  '</div>';
}

function addWatermark() {
  const el = document.getElementById('wmList');
  el.insertAdjacentHTML('beforeend', wmTemplate(wmCounter));
  wmCounter++;
}

function removeWatermark(idx) {
  const el = document.querySelector('.wm-entry[data-idx="'+idx+'"]');
  if (el) el.remove();
}

function setWmIdx(idx, color) {
  const entry = document.querySelector('.wm-entry[data-idx="'+idx+'"]');
  if (entry) entry.querySelector('.wm-color').value = color;
}

// Add first watermark by default
addWatermark();

document.getElementById('fileInput').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('pdf', f);
  try {
    const r = await fetch('/upload', { method:'POST', body:fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.sessionId = d.session_id; state.pages = d.pages;
    state.currentPage = 0; state.regions = {};
    document.getElementById('emptyMsg').style.display = 'none';
    document.getElementById('sidebar').style.display = 'flex';
    document.getElementById('processBtn').disabled = false;
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
  img.onload = () => { baseCanvas.getContext('2d').drawImage(img,0,0); redrawOverlay(); };
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
    document.querySelectorAll('.wm-entry').forEach(el => {
      const text = el.querySelector('.wm-text').value.trim();
      if (!text) return;
      wmList.push({
        text: text,
        opacity: parseInt(el.querySelector('.wm-opacity').value),
        color: el.querySelector('.wm-color').value,
      });
    });
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

function toast(msg, err) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = 'toast'+(err?' error':'');
  el.style.display = 'block';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.style.display = 'none', 2500);
}
function status(msg) { document.getElementById('statusText').textContent = msg; }
window.addEventListener('resize', () => { if (state.pages.length) renderPage(state.currentPage); });
</script>
</body>
</html>
'''


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
    # Remove existing processed images from previous runs
    processed_dir = paths['processed_dir']
    if os.path.exists(processed_dir):
        import shutil
        shutil.rmtree(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    # Save originals as processed reference
    for i, img in enumerate(images):
        img.save(os.path.join(processed_dir, f'{i}.png'))
    return jsonify({'session_id': session_id, 'pages': pages})


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

    # Load original images from processed dir
    processed_dir = paths['processed_dir']
    if not os.path.exists(processed_dir):
        return jsonify({'error': 'Session not found'}), 404

    # Load images
    images = []
    for f in sorted(os.listdir(processed_dir), key=lambda x: int(x.split('.')[0])):
        if f.endswith('.png'):
            images.append(Image.open(os.path.join(processed_dir, f)))

    if not images:
        return jsonify({'error': 'No images found'}), 404

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

    output = os.path.join(paths['processed_dir'], 'output.pdf')
    images_to_pdf(images, output)
    return send_file(output, as_attachment=True,
                     download_name='processed_output.pdf',
                     mimetype='application/pdf')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8777))
    print('╔══════════════════════════════════════╗')
    print('║  PDF Blur + Watermark Tool           ║')
    print(f'║  http://0.0.0.0:{port:<39}║')
    print('╚══════════════════════════════════════╝')
    app.run(host='0.0.0.0', port=port, debug=True)
