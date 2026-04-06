#!/usr/bin/env python3
"""
mac_server.py – Filament-Waage Mac-Server
==========================================
Der Mac übernimmt: Web-UI, Live-Chart, Messlog.
Der ESP liefert nur noch Rohdaten via JSON-API.

Installation (einmalig):
    pip3 install flask requests

Konfiguration:
    config.json im selben Ordner anlegen (wird beim ersten Start auto-erstellt):
    {
      "esp_ip": "192.168.1.XXX",   <-- IP des ESP aus Serial-Monitor ablesen
      "port": 8080
    }

Start:
    python3 mac_server.py
    Browser: http://localhost:8080
"""

import json, os, datetime, sys
from flask import Flask, request, jsonify, Response
import requests

app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
LOG_FILE    = os.path.join(os.path.dirname(__file__), "filament_log.json")
MAX_LOG     = 500   # Viel mehr Einträge als auf dem ESP möglich

def load_config():
    defaults = {"esp_ip": "192.168.1.100", "port": 8080}
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        defaults.update(cfg)
    except FileNotFoundError:
        with open(CONFIG_FILE, "w") as f:
            json.dump(defaults, f, indent=2)
        print("=" * 55)
        print("  config.json wurde erstellt.")
        print("  Bitte ESP-IP eintragen und neu starten!")
        print(f"  Datei: {CONFIG_FILE}")
        print("=" * 55)
    return defaults

config   = load_config()
ESP_BASE = f"http://{config['esp_ip']}"
PORT     = int(config.get("port", 8080))

# ═══════════════════════════════════════════════════════
# LOG-VERWALTUNG (läuft auf dem Mac)
# ═══════════════════════════════════════════════════════
def load_log():
    try:
        with open(LOG_FILE) as f:
            return json.load(f)
    except:
        return []

def save_log(entries):
    with open(LOG_FILE, "w") as f:
        json.dump(entries[-MAX_LOG:], f, indent=2)

log_entries = load_log()

# ═══════════════════════════════════════════════════════
# ESP-PROXY HILFSFUNKTION
# ═══════════════════════════════════════════════════════
def esp_get(path, timeout=5):
    """Holt JSON vom ESP. Gibt None zurück bei Fehler."""
    try:
        r = requests.get(ESP_BASE + path, timeout=timeout)
        return r.json()
    except Exception as e:
        print(f"[ESP] Fehler bei {path}: {e}")
        return None

# ═══════════════════════════════════════════════════════
# MATERIALIEN (aus openprinttag – auf dem Mac dupliziert)
# ═══════════════════════════════════════════════════════
MATERIAL_TYPES = sorted([
    "PLA", "PLA+", "PETG", "ABS", "ASA", "TPU", "TPE",
    "Nylon", "PA6", "PA12", "PC", "POM", "HIPS", "PVA",
    "PEEK", "PEI", "PP", "PVDF", "SBS", "FLEX",
    "Wood", "Metal", "Carbon", "Glow", "Silk", "Matte",
    "High Speed", "Other"
])
MATERIAL_OPTIONS = "\n".join(f"<option>{m}</option>" for m in MATERIAL_TYPES)

# ═══════════════════════════════════════════════════════
# HTML-TEMPLATE (identisch mit dem Original-ESP-Script)
# ═══════════════════════════════════════════════════════
HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="apple-touch-icon" sizes="180x180" href="/icon_waage9.png">
<link rel="icon" type="image/png" href="/icon_waage9.png">
<meta name="apple-mobile-web-app-title" content="Filament-Waage">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Filament-Waage</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;padding:14px}
h1{font-size:1.3rem;color:#7dd3fc;margin-bottom:14px;text-align:center}
.card{background:#1e2535;border-radius:12px;padding:14px;margin-bottom:12px;border:1px solid #2d3748}
.big{font-size:3.2rem;font-weight:700;text-align:center;color:#34d399;line-height:1}
.sub{font-size:0.8rem;text-align:center;color:#94a3b8;margin-top:2px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.stat{flex:1;min-width:90px;background:#162032;border-radius:8px;padding:8px;text-align:center}
.stat .v{font-size:1.3rem;font-weight:700;color:#7dd3fc}
.stat .l{font-size:0.72rem;color:#64748b;margin-top:1px}
button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:9px 14px;
       font-size:0.85rem;cursor:pointer;flex:1;min-width:110px;margin:3px}
button.red{background:#dc2626} button.green{background:#16a34a} button.orange{background:#d97706}
button.sm{flex:0;padding:5px 10px;font-size:0.78rem;min-width:auto}
input,select{background:#162032;border:1px solid #2d3748;color:#e2e8f0;border-radius:6px;
             padding:7px 9px;width:100%;margin:3px 0;font-size:0.85rem}
label{font-size:0.78rem;color:#94a3b8;margin-top:5px;display:block}
.tag-box{background:#162032;border-radius:8px;padding:10px;font-size:0.8rem;color:#94a3b8}
.alarm{color:#f87171} .ok{color:#34d399}
.badge{display:inline-block;background:#1e40af;color:#bfdbfe;border-radius:4px;
       padding:2px 7px;font-size:0.72rem;margin-left:5px}
#status{text-align:center;padding:7px;border-radius:8px;margin-bottom:8px;
        font-size:0.82rem;display:none}
.log-entry{font-size:0.76rem;padding:3px 0;border-bottom:1px solid #1e2535;color:#94a3b8}
.hint{font-size:0.76rem;color:#34d399;margin-top:3px;display:none}
.temps{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.temps input{flex:1;min-width:60px}
#chartCanvas{width:100%;border-radius:8px;display:block;background:#0f1117}
.chart-meta{display:flex;justify-content:space-between;font-size:0.72rem;color:#64748b;margin-top:4px}
.esp-badge{background:#0d3b1e;color:#34d399;border:1px solid #166534;border-radius:6px;
           font-size:0.72rem;padding:3px 8px;display:inline-block;margin-bottom:10px}
</style>
</head>
<body>
<h1>Filament-Waage <span class="badge">PN5180 OpenPrintTag</span></h1>
<div class="esp-badge" id="esp_status">&#x25CF; ESP verbunden</div>
<div id="status"></div>

<!-- GEWICHT -->
<div class="card">
  <div class="big" id="weight">{WEIGHT}</div>
  <div class="sub">Gramm Gesamtgewicht</div>
  <div class="row">
    <div class="stat"><div class="v" id="filament">{FILAMENT}</div><div class="l">Filament (g)</div></div>
    <div class="stat"><div class="v" id="spool_disp">{SPOOL}</div><div class="l">Spule leer (g)</div></div>
    <div class="stat"><div class="v {ALARM_CLASS}" id="pct_disp">{PCT}</div><div class="l">Restmenge</div></div>
    <div class="stat"><div class="v" id="remaining_disp">{REMAINING}</div><div class="l">Rest (g)</div></div>
  </div>
  <div class="row" style="margin-top:10px">
    <button onclick="action('tare')">Tara</button>
    <button class="green" onclick="logMeasurement()">Messen und loggen</button>
  </div>
</div>

<!-- LIVE GRAPH -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:8px;color:#7dd3fc;display:flex;align-items:center;justify-content:space-between">
    <span>Live-Gewichtsverlauf</span>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
      <select id="chart_range" style="width:auto;padding:4px 8px;font-size:0.75rem" onchange="chartRangeChanged()">
        <option value="0">10 min</option>
        <option value="1">30 min</option>
        <option value="2">1 Stunde</option>
        <option value="3">3 Stunden</option>
        <option value="4">8 Stunden</option>
        <option value="5">24 Stunden</option>
        <option value="6">72 Stunden</option>
      </select>
      <select id="chart_mode" style="width:auto;padding:4px 8px;font-size:0.75rem" onchange="chartModeChanged()">
        <option value="filament">Filament (g)</option>
        <option value="total">Gesamt (g)</option>
      </select>
      <button class="sm red" onclick="resetChart()" style="margin:0">Reset</button>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;background:#162032;border-radius:8px;padding:8px 10px">
    <label class="nfc-toggle" style="position:relative;display:inline-block;width:40px;height:22px;margin:0;cursor:pointer">
      <input type="checkbox" id="nfc_only_toggle" onchange="nfcOnlyChanged()" style="opacity:0;width:0;height:0;position:absolute">
      <span style="position:absolute;inset:0;background:#2d3748;border-radius:11px;transition:.3s" id="nfc_tog_bg"></span>
      <span style="position:absolute;left:3px;top:3px;width:16px;height:16px;background:#fff;border-radius:50%;transition:.3s" id="nfc_tog_knob"></span>
    </label>
    <div>
      <div style="font-size:0.82rem;color:#e2e8f0">Nur bei NFC-Schreibvorgang plotten</div>
      <div style="font-size:0.72rem;color:#64748b" id="nfc_only_hint">Aus &ndash; plottet kontinuierlich</div>
    </div>
  </div>
  <canvas id="chartCanvas" height="180"></canvas>
  <div class="chart-meta">
    <span id="chart_min_label">Min: --</span>
    <span id="chart_points">0 Messpunkte</span>
    <span id="chart_max_label">Max: --</span>
  </div>
  <div style="font-size:0.72rem;color:#475569;margin-top:4px;text-align:center" id="chart_range_hint">
    Speichert alle 5s einen Punkt &bull; Puffer: 1000 Punkte &bull; Reset bei Tara automatisch
  </div>
</div>

<!-- SPULENGEWICHT -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:6px;color:#7dd3fc">Spulengewicht leer</div>
  <div style="font-size:0.75rem;color:#64748b;margin-bottom:8px">
    Typisch: Bambu ~250g, Prusament ~200g, Generic 100-160g.
  </div>
  <div class="row" style="margin-bottom:6px">
    <button class="sm orange" onclick="quickSpool(100)">100g</button>
    <button class="sm orange" onclick="quickSpool(130)">130g</button>
    <button class="sm orange" onclick="quickSpool(160)">160g</button>
    <button class="sm orange" onclick="quickSpool(200)">200g</button>
    <button class="sm orange" onclick="quickSpool(250)">250g</button>
  </div>
  <div style="display:flex;gap:6px">
    <input id="spool_g" type="number" min="0" max="1000" placeholder="Gramm..." value="{SPOOL}" style="flex:1">
    <button class="orange" onclick="setSpool()" style="flex:0;width:auto">Speichern</button>
    <button class="green"  onclick="measureSpool()" style="flex:0;width:auto">Jetzt wiegen</button>
  </div>
  <div id="spool_hint" class="hint"></div>
</div>

<!-- OpenPrintTag -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:6px;color:#7dd3fc">
    OpenPrintTag (ISO 15693 / ICODE SLIX)
  </div>
  <div id="taginfo" class="tag-box">{TAG_INFO}</div>
  <div class="row" style="margin-top:8px">
    <button class="orange" onclick="action('nfc_read')">Tag lesen</button>
    <button class="green"  onclick="writeTag()">Tag schreiben</button>
    <button onclick="action('nfc_update')" title="Verbrauchten Anteil aktualisieren">Verbrauch updaten</button>
    <hr style="margin:10px 0;border:0;border-top:1px solid #2d3748">
    <label>Auto-Update bei Verbrauchsänderung (g)</label>
    <div style="display:flex;gap:6px">
      <input id="auto_thr" type="number" min="1" max="100" value="{AUTO_THR}" style="flex:1">
      <button class="green" onclick="setAutoThr()" style="flex:0;width:auto">Speichern</button>
    </div>
  </div>
  <label>Hersteller / Brand</label>
  <input id="brand" type="text" placeholder="z.B. Prusament, Bambu, Polymaker" value="{TAG_BRAND}">
  <label>Material</label>
  <select id="material">{MATERIAL_OPTIONS}</select>
  <label>Farbe (HEX)</label>
  <input id="color" type="color" value="{TAG_COLOR_HEX}" style="height:36px;padding:2px">
  <label>Farb-Name</label>
  <input id="color_name" type="text" placeholder="z.B. Galaxy Black" value="{TAG_COLOR_NAME}">
  <label>Drucktemperaturen Nozzle / Bett</label>
  <div class="temps">
    <input id="nozzle_min" type="number" placeholder="Nozzle min" value="{NOZZLE_MIN}">
    <input id="nozzle_max" type="number" placeholder="Nozzle max" value="{NOZZLE_MAX}">
    <input id="bed_min"    type="number" placeholder="Bett min"   value="{BED_MIN}">
    <input id="bed_max"    type="number" placeholder="Bett max"   value="{BED_MAX}">
  </div>
  <label>Durchmesser (mm)</label>
  <input id="diameter" type="number" step="0.01" value="{DIAMETER}" placeholder="1.75">
  <label>Ursprüngliches Gewicht der Spule mit Filament (g)</label>
  <input id="full_weight" type="number" placeholder="z.B. 1000" value="{FULL_WEIGHT}">
</div>

<!-- KALIBRIERUNG -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:6px;color:#7dd3fc">Kalibrierung</div>
  <div style="font-size:0.75rem;color:#64748b;margin-bottom:6px">
    Leere Waage tarieren, dann bekanntes Gewicht auflegen und Wert eingeben.
  </div>
  <div style="display:flex;gap:6px">
    <input id="cal_weight" type="number" placeholder="Bekanntes Gewicht (g)" style="flex:1">
    <button onclick="calibrate()" style="flex:0;width:auto">Kalibrieren</button>
  </div>
  <div style="margin-top:6px;font-size:0.78rem;color:{CAL_COLOR}" id="cal_status_disp">{CAL_STATUS}</div>
</div>

<!-- ALARM -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:6px;color:#7dd3fc">Alarm</div>
  <div style="display:flex;gap:6px">
    <input id="alarm_thresh" type="number" value="{ALARM}" style="flex:1">
    <button onclick="setAlarm()" style="flex:0;width:auto">Alarm bei (g) setzen</button>
  </div>
</div>

<!-- LOG -->
<div class="card">
  <div style="font-size:0.95rem;font-weight:600;margin-bottom:6px;color:#7dd3fc">
    Messlog
    <button class="red sm" onclick="clearLog()" style="float:right">Löschen</button>
    <button class="sm" onclick="exportLog()" style="float:right;margin-right:4px">Export</button>
  </div>
  <div id="loglist">{LOG_HTML}</div>
</div>

<div style="text-align:center;font-size:0.72rem;color:#475569;margin-top:6px">
  ESP Uptime: <span id="uptime_disp">{UPTIME}</span> &bull;
  Kalibrierung: <span id="cal_factor_disp">{CAL_FACTOR}</span> &bull;
  Version: {FW_VERSION}
</div>

<script>
// ============================================================
// LIVE CHART
// ============================================================
var chartData   = [];
var MAX_POINTS  = 1000;
var chartMode   = 'filament';
var lastChartPushT = 0;

var CHART_PRESETS = [
  ['10 min',  5000,          10 * 60 * 1000],
  ['30 min',  15000,         30 * 60 * 1000],
  ['1 h',     30000,         60 * 60 * 1000],
  ['3 h',     60000,      3 * 60 * 60 * 1000],
  ['8 h',     3*60000,    8 * 60 * 60 * 1000],
  ['24 h',    10*60000,  24 * 60 * 60 * 1000],
  ['72 h',    30*60000,  72 * 60 * 60 * 1000],
];
var chartPresetIdx = 0;

function getPreset(){ return CHART_PRESETS[chartPresetIdx]; }
function chartSampleMs(){ return getPreset()[1]; }
function chartAgeMs(){    return getPreset()[2]; }

function chartModeChanged(){
  chartMode = document.getElementById('chart_mode').value;
  drawChart();
}
function chartRangeChanged(){
  chartPresetIdx = parseInt(document.getElementById('chart_range').value);
  updateRangeHint();
}
function updateRangeHint(){
  var p = getPreset();
  document.getElementById('chart_range_hint').textContent =
    'Speichert alle ' + (p[1]>=60000 ? Math.round(p[1]/60000)+'min' : (p[1]/1000)+'s') +
    ' einen Punkt · Puffer: ' + MAX_POINTS + ' Punkte';
}
function resetChart(){
  chartData = []; lastChartPushT = 0; drawChart();
}

var nfcOnlyMode = false;
function nfcOnlyChanged(){
  nfcOnlyMode = document.getElementById('nfc_only_toggle').checked;
  document.getElementById('nfc_tog_bg').style.background    = nfcOnlyMode ? '#2563eb' : '#2d3748';
  document.getElementById('nfc_tog_knob').style.left        = nfcOnlyMode ? '21px'    : '3px';
  document.getElementById('nfc_only_hint').textContent      = nfcOnlyMode
    ? 'Ein \u2013 Punkt nur wenn NFC-Tag aktualisiert wurde'
    : 'Aus \u2013 plottet kontinuierlich';
  resetChart();
}

function pushChartPoint(totalG, filamentG){
  if(totalG === null || totalG === undefined) return;
  var now = Date.now();
  if(now - lastChartPushT < chartSampleMs()) return;
  lastChartPushT = now;
  var cutoff = now - chartAgeMs();
  while(chartData.length > 0 && chartData[0].t < cutoff) chartData.shift();
  chartData.push({t: now, w: totalG, f: filamentG !== null ? filamentG : 0});
  if(chartData.length > MAX_POINTS) chartData.shift();
}

function drawChart(){
  var canvas = document.getElementById('chartCanvas');
  if(!canvas) return;
  var dpr = window.devicePixelRatio || 1;
  var cssW = canvas.parentElement.clientWidth - 28;
  var cssH = 180;
  canvas.style.width  = cssW + 'px';
  canvas.style.height = cssH + 'px';
  canvas.width  = cssW * dpr;
  canvas.height = cssH * dpr;
  var ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  var W = cssW, H = cssH;
  var PAD = {top:14, right:10, bottom:28, left:52};
  var plotW = W - PAD.left - PAD.right;
  var plotH = H - PAD.top  - PAD.bottom;
  ctx.fillStyle = '#0f1117';
  ctx.fillRect(0, 0, W, H);
  if(chartData.length < 2){
    ctx.fillStyle = '#475569';
    ctx.font = '13px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Warte auf Messpunkte...', W/2, H/2);
    document.getElementById('chart_points').textContent = '0 Messpunkte';
    document.getElementById('chart_min_label').textContent = 'Min: --';
    document.getElementById('chart_max_label').textContent = 'Max: --';
    return;
  }
  var vals = chartData.map(function(d){ return chartMode === 'total' ? d.w : d.f; });
  var rawMin = Math.min.apply(null, vals);
  var rawMax = Math.max.apply(null, vals);
  var spread = rawMax - rawMin;
  if(spread < 5) spread = 5;
  var yMin = Math.max(0, rawMin - spread * 0.12);
  var yMax = rawMax + spread * 0.12;
  function niceStep(range, ticks){
    var rough = range / ticks;
    var mag = Math.pow(10, Math.floor(Math.log(rough) / Math.LN10));
    var steps = [1,2,5,10];
    for(var i=0;i<steps.length;i++) if(steps[i]*mag >= rough) return steps[i]*mag;
    return mag*10;
  }
  var step = niceStep(yMax - yMin, 5);
  yMin = Math.floor(yMin / step) * step;
  yMax = Math.ceil(yMax  / step) * step;
  if(yMax === yMin) yMax = yMin + step;
  var tMin = chartData[0].t;
  var tMax = chartData[chartData.length-1].t;
  if(tMax === tMin) tMax = tMin + 1000;
  ctx.strokeStyle = '#1e2535'; ctx.lineWidth = 1;
  ctx.fillStyle = '#64748b'; ctx.font = '10px sans-serif'; ctx.textAlign = 'right';
  var nLines = Math.round((yMax - yMin) / step);
  for(var i=0; i<=nLines; i++){
    var yVal = yMin + i * step;
    var yPx  = PAD.top + plotH - ((yVal - yMin) / (yMax - yMin)) * plotH;
    ctx.beginPath(); ctx.moveTo(PAD.left, yPx); ctx.lineTo(PAD.left + plotW, yPx); ctx.stroke();
    ctx.fillText(Math.round(yVal) + 'g', PAD.left - 4, yPx + 3);
  }
  ctx.textAlign='center'; ctx.fillStyle='#64748b';
  var totalMs=tMax-tMin;
  var xStepMs=totalMs<=120000?10000:totalMs<=600000?60000:totalMs<=3600000?300000:totalMs<=21600000?1800000:3600000;
  var firstTick=Math.ceil(tMin/xStepMs)*xStepMs;
  for(var ts=firstTick;ts<=tMax;ts+=xStepMs){
    var xPx=PAD.left+((ts-tMin)/(tMax-tMin))*plotW;
    var d=new Date(ts);
    var hh=d.getHours().toString().padStart(2,'0');
    var mm=d.getMinutes().toString().padStart(2,'0');
    ctx.fillText(hh+':'+mm,xPx,H-6);
    ctx.beginPath(); ctx.strokeStyle='#1e2535'; ctx.moveTo(xPx,PAD.top); ctx.lineTo(xPx,PAD.top+plotH); ctx.stroke();
  }
  var alarmG = parseFloat(document.getElementById('alarm_thresh').value) || 0;
  if(chartMode === 'filament' && alarmG > yMin && alarmG < yMax){
    var alarmY = PAD.top + plotH - ((alarmG - yMin) / (yMax - yMin)) * plotH;
    ctx.setLineDash([4, 4]); ctx.strokeStyle = '#f87171'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.left, alarmY); ctx.lineTo(PAD.left + plotW, alarmY); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = '#f87171'; ctx.textAlign = 'left'; ctx.font = '9px sans-serif';
    ctx.fillText('Alarm ' + Math.round(alarmG) + 'g', PAD.left + 2, alarmY - 2);
  }
  ctx.setLineDash([]);
  ctx.beginPath();
  for(var i=0; i<chartData.length; i++){
    var xPx2 = PAD.left + ((chartData[i].t - tMin) / (tMax - tMin)) * plotW;
    var v    = chartMode === 'total' ? chartData[i].w : chartData[i].f;
    var yPx2 = PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
    if(i === 0) ctx.moveTo(xPx2, yPx2); else ctx.lineTo(xPx2, yPx2);
  }
  var lastX = PAD.left + plotW;
  ctx.lineTo(lastX, PAD.top + plotH); ctx.lineTo(PAD.left, PAD.top + plotH); ctx.closePath();
  var grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + plotH);
  grad.addColorStop(0, 'rgba(52,211,153,0.35)'); grad.addColorStop(1, 'rgba(52,211,153,0.02)');
  ctx.fillStyle = grad; ctx.fill();
  ctx.beginPath();
  for(var i=0; i<chartData.length; i++){
    var xPx2 = PAD.left + ((chartData[i].t - tMin) / (tMax - tMin)) * plotW;
    var v    = chartMode === 'total' ? chartData[i].w : chartData[i].f;
    var yPx2 = PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
    if(i === 0) ctx.moveTo(xPx2, yPx2); else ctx.lineTo(xPx2, yPx2);
  }
  ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
  var lastD = chartData[chartData.length-1];
  var lxPx = PAD.left + ((lastD.t - tMin) / (tMax - tMin)) * plotW;
  var lv   = chartMode === 'total' ? lastD.w : lastD.f;
  var lyPx = PAD.top + plotH - ((lv - yMin) / (yMax - yMin)) * plotH;
  ctx.beginPath(); ctx.arc(lxPx, lyPx, 4, 0, 2*Math.PI);
  ctx.fillStyle = '#34d399'; ctx.fill();
  ctx.strokeStyle = '#0f1117'; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = '#34d399'; ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = lxPx > plotW*0.8 ? 'right' : 'left';
  ctx.fillText(lv.toFixed(1) + 'g', lxPx + (lxPx > plotW*0.8 ? -7 : 7), lyPx - 5);
  ctx.strokeStyle = '#2d3748'; ctx.lineWidth = 1;
  ctx.strokeRect(PAD.left, PAD.top, plotW, plotH);
  document.getElementById('chart_min_label').textContent = 'Min: ' + Math.min.apply(null,vals).toFixed(1) + 'g';
  document.getElementById('chart_max_label').textContent = 'Max: ' + Math.max.apply(null,vals).toFixed(1) + 'g';
  document.getElementById('chart_points').textContent    = chartData.length + ' Punkte';
}

// ============================================================
// AKTIONEN
// ============================================================
var _espOk = true;

function showStatus(msg, ok){
  var s=document.getElementById('status');
  s.style.display='block'; s.style.background=ok?'#14532d':'#450a0a';
  s.style.color=ok?'#86efac':'#fca5a5'; s.textContent=msg;
  setTimeout(function(){s.style.display='none'},3500);
}

function setAutoThr(){
  var v=document.getElementById('auto_thr').value;
  fetch('/action?a=set_auto_thr&v='+v)
    .then(function(r){return r.json();})
    .then(function(d){showStatus(d.msg,d.ok);});
}

function action(a){
  fetch('/action?a='+a).then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg, d.ok);
    if(a==='nfc_read' && d.tag) fillTagFields(d.tag);
    if(a==='tare') resetChart();
    setTimeout(refreshWeight, 400);
  }).catch(function(e){showStatus('ESP nicht erreichbar: '+e, false);});
}

// Log-Eintrag: Mac fragt ESP nach Gewicht, speichert lokal
function logMeasurement(){
  fetch('/log_measurement').then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg, d.ok);
    if(d.ok) refreshLog();
  }).catch(function(e){showStatus('Fehler: '+e, false);});
}

function clearLog(){
  if(!confirm('Messlog wirklich löschen?')) return;
  fetch('/clear_log').then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg, d.ok); refreshLog();
  });
}

function exportLog(){
  window.open('/export_log', '_blank');
}

function calibrate(){
  var g=document.getElementById('cal_weight').value;
  if(!g){showStatus('Bitte Gewicht eingeben',false);return;}
  fetch('/action?a=calibrate&g='+g).then(function(r){return r.json();}).then(function(d){showStatus(d.msg,d.ok);});
}
function setSpool(){
  var g=document.getElementById('spool_g').value;
  if(!g||g<0){showStatus('Ungültig',false);return;}
  fetch('/action?a=spool&g='+g).then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg,d.ok); setTimeout(refreshWeight,300);
  });
}
function quickSpool(g){ document.getElementById('spool_g').value=g; setSpool(); }

function measureSpool(){
  fetch('/action?a=measure_spool').then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg,d.ok);
    if(d.ok&&d.g){
      document.getElementById('spool_g').value=Math.round(d.g);
      var h=document.getElementById('spool_hint');
      h.textContent='Gemessen: '+d.g.toFixed(1)+'g gespeichert!'; h.style.display='block';
      setTimeout(function(){h.style.display='none';},5000);
    }
  });
}
function setAlarm(){
  var g=document.getElementById('alarm_thresh').value;
  fetch('/action?a=alarm&g='+g).then(function(r){return r.json();}).then(function(d){
    showStatus(d.msg,d.ok); drawChart();
  });
}
function writeTag(){
  var p='brand='+encodeURIComponent(document.getElementById('brand').value)
    +'&mat='+encodeURIComponent(document.getElementById('material').value)
    +'&col='+encodeURIComponent(document.getElementById('color').value)
    +'&col_name='+encodeURIComponent(document.getElementById('color_name').value)
    +'&nm='+document.getElementById('nozzle_min').value
    +'&nx='+document.getElementById('nozzle_max').value
    +'&bm='+document.getElementById('bed_min').value
    +'&bx='+document.getElementById('bed_max').value
    +'&dia='+document.getElementById('diameter').value
    +'&fw='+document.getElementById('full_weight').value
    +'&sp='+document.getElementById('spool_g').value;
  fetch('/action?a=nfc_write&'+p).then(function(r){return r.json();}).then(function(d){showStatus(d.msg,d.ok);});
}
function fillTagFields(t){
  if(t.brand)      document.getElementById('brand').value=t.brand;
  if(t.material)   document.getElementById('material').value=t.material;
  if(t.color)      document.getElementById('color').value=t.color;
  if(t.color_name) document.getElementById('color_name').value=t.color_name;
  if(t.nozzle_min) document.getElementById('nozzle_min').value=t.nozzle_min;
  if(t.nozzle_max) document.getElementById('nozzle_max').value=t.nozzle_max;
  if(t.bed_min)    document.getElementById('bed_min').value=t.bed_min;
  if(t.bed_max)    document.getElementById('bed_max').value=t.bed_max;
  if(t.diameter)   document.getElementById('diameter').value=t.diameter;
  if(t.weight)     document.getElementById('full_weight').value=t.weight;
  var info='Brand: '+t.brand+' | '+t.material+' '+t.color_name
    +' | '+t.weight+'g | Rest: '+t.remaining_weight+'g'
    +' | Nozzle: '+t.nozzle_min+'-'+t.nozzle_max+'C';
  document.getElementById('taginfo').textContent=info;
}

function refreshLog(){
  fetch('/logdata').then(function(r){return r.json();}).then(function(d){
    document.getElementById('loglist').innerHTML=d.html;
  }).catch(function(){});
}

function refreshWeight(){
  fetch('/weight').then(function(r){return r.json();}).then(function(d){
    // ESP-Status-Badge
    var badge = document.getElementById('esp_status');
    if(!_espOk){ badge.textContent='\u25CF ESP verbunden'; badge.style.color='#34d399'; _espOk=true; }
    if(d.weight!==null){
      document.getElementById('weight').textContent=d.weight.toFixed(1);
      var fil = d.filament !== null ? d.filament : null;
      if(fil!==null) document.getElementById('filament').textContent=fil.toFixed(1);
      if(!nfcOnlyMode || d.nfc_event){
        pushChartPoint(d.weight, fil); drawChart();
      }
      if(nfcOnlyMode && d.nfc_event){
        var tog = document.getElementById('nfc_tog_bg');
        tog.style.background = '#34d399';
        setTimeout(function(){ tog.style.background = '#2563eb'; }, 600);
      }
    }
  }).catch(function(){
    if(_espOk){
      document.getElementById('esp_status').textContent='\u25CF ESP nicht erreichbar';
      document.getElementById('esp_status').style.color='#f87171';
      _espOk=false;
    }
  });
}

// Status vom ESP laden (Uptime, Kalibrierung)
function refreshStatus(){
  fetch('/status').then(function(r){return r.json();}).then(function(d){
    if(d.uptime) document.getElementById('uptime_disp').textContent=d.uptime;
    if(d.cal_factor) document.getElementById('cal_factor_disp').textContent=d.cal_factor.toFixed(4);
    if(d.cal_status) document.getElementById('cal_status_disp').textContent=d.cal_status;
    if(d.spool !== undefined) document.getElementById('spool_g').value=Math.round(d.spool);
    if(d.alarm !== undefined) document.getElementById('alarm_thresh').value=d.alarm;
    if(d.auto_thr !== undefined) document.getElementById('auto_thr').value=d.auto_thr;
  }).catch(function(){});
}

window.addEventListener('resize', drawChart);
updateRangeHint();
drawChart();

setInterval(refreshWeight,  1500);
setInterval(refreshLog,     5000);
setInterval(refreshStatus, 30000);  // alle 30s Uptime etc. aktualisieren
refreshStatus();  // sofort beim Laden
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════
# FLASK ROUTEN
# ═══════════════════════════════════════════════════════

@app.route("/")
def index():
    """Startseite – ESP-Status holen und Platzhalter füllen."""
    status = esp_get("/status") or {}
    td = status.get("tag") or {}

    cal_ok     = status.get("cal_ok", False)
    cal_factor = status.get("cal_factor", 1.0)
    cal_status = ("Kalibriert (Faktor: {:.2f})".format(cal_factor) if cal_ok
                  else "Nicht kalibriert – bitte kalibrieren!")
    cal_color  = "#34d399" if cal_ok else "#f87171"

    tag_info = "Kein Tag gelesen – ICODE SLIX/SLIX2 Tag auflegen und 'Tag lesen' drücken"
    if td:
        tag_info = "{} {} {} | {}g gesamt | {}g Rest | Nozzle {}-{}C".format(
            td.get("brand",""), td.get("material",""), td.get("color_name",""),
            td.get("weight",0), td.get("remaining_weight",0),
            td.get("nozzle_min",""), td.get("nozzle_max",""))

    # Log-HTML für initiale Anzeige
    log_html = _build_log_html()

    page = HTML
    page = page.replace("{MATERIAL_OPTIONS}", MATERIAL_OPTIONS)
    page = page.replace("{WEIGHT}",      "--")
    page = page.replace("{FILAMENT}",    "--")
    page = page.replace("{SPOOL}",       str(int(status.get("spool", 0))))
    page = page.replace("{PCT}",         "--")
    page = page.replace("{REMAINING}",   "--")
    page = page.replace("{ALARM_CLASS}", "")
    page = page.replace("{TAG_INFO}",    tag_info)
    page = page.replace("{TAG_BRAND}",   td.get("brand",""))
    page = page.replace("{TAG_COLOR_HEX}",  td.get("color","#ffffff"))
    page = page.replace("{TAG_COLOR_NAME}", td.get("color_name",""))
    page = page.replace("{NOZZLE_MIN}",  str(td.get("nozzle_min", 200)))
    page = page.replace("{NOZZLE_MAX}",  str(td.get("nozzle_max", 220)))
    page = page.replace("{BED_MIN}",     str(td.get("bed_min", 50)))
    page = page.replace("{BED_MAX}",     str(td.get("bed_max", 60)))
    page = page.replace("{DIAMETER}",    str(td.get("diameter", 1.75)))
    page = page.replace("{FULL_WEIGHT}", str(td.get("weight", "")))
    page = page.replace("{ALARM}",       str(status.get("alarm", 50.0)))
    page = page.replace("{AUTO_THR}",    str(status.get("auto_thr", 5)))
    page = page.replace("{CAL_STATUS}",  cal_status)
    page = page.replace("{CAL_COLOR}",   cal_color)
    page = page.replace("{CAL_FACTOR}",  "{:.4f}".format(cal_factor))
    page = page.replace("{FW_VERSION}",  status.get("fw", "–"))
    page = page.replace("{UPTIME}",      status.get("uptime", "–"))
    page = page.replace("{LOG_HTML}",    log_html)
    return page


@app.route("/weight")
def weight():
    """Gewicht vom ESP holen und weiterreichen."""
    data = esp_get("/weight")
    if data is None:
        return jsonify({"weight": None, "filament": None, "nfc_event": False,
                        "error": "ESP nicht erreichbar"})
    return jsonify(data)


@app.route("/status")
def status():
    """ESP-Status holen und weiterreichen."""
    data = esp_get("/status")
    if data is None:
        return jsonify({"error": "ESP nicht erreichbar"})
    # Cal-Status-Text ergänzen (für JS)
    cal_ok = data.get("cal_ok", False)
    data["cal_status"] = ("Kalibriert (Faktor: {:.2f})".format(data.get("cal_factor",1.0))
                          if cal_ok else "Nicht kalibriert – bitte kalibrieren!")
    return jsonify(data)


@app.route("/action")
def action():
    """Alle Aktionen an den ESP weiterleiten."""
    qs = request.query_string.decode()
    data = esp_get(f"/action?{qs}", timeout=8)
    if data is None:
        return jsonify({"ok": False, "msg": "ESP nicht erreichbar"})
    return jsonify(data)


@app.route("/log_measurement")
def log_measurement():
    """Messen und Eintrag lokal speichern (Log läuft auf Mac)."""
    global log_entries
    raw = esp_get("/action?a=get_weight_raw", timeout=6)
    if raw is None or not raw.get("ok"):
        return jsonify({"ok": False, "msg": "Waage nicht erreichbar oder nicht kalibriert"})

    w        = raw.get("weight")
    filament = raw.get("filament")
    brand    = raw.get("brand", "")
    mat      = raw.get("material", "")

    note = "{} {} {:.0f}g Filament".format(brand, mat, filament).strip() if filament else ""
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    log_entries.append({"ts": ts, "g": round(w, 1), "note": note})
    save_log(log_entries)
    print(f"[LOG] {ts} | {w:.1f}g | {note}")
    return jsonify({"ok": True, "msg": "Gespeichert: {:.1f}g".format(w)})


@app.route("/clear_log")
def clear_log():
    """Messlog löschen."""
    global log_entries
    log_entries.clear()
    save_log(log_entries)
    return jsonify({"ok": True, "msg": "Log gelöscht"})


@app.route("/logdata")
def logdata():
    """Log-HTML für die UI (letzte 20 Einträge)."""
    html = _build_log_html()
    return jsonify({"html": html})


@app.route("/export_log")
def export_log():
    """Log als JSON-Datei herunterladen."""
    content = json.dumps(log_entries, indent=2, ensure_ascii=False)
    return Response(content,
                    mimetype="application/json",
                    headers={"Content-Disposition":
                             "attachment; filename=filament_log.json"})


@app.route("/icon_waage9.png")
def icon():
    """Icon vom ESP holen."""
    try:
        r = requests.get(f"{ESP_BASE}/icon_waage9.png", timeout=5)
        return Response(r.content, mimetype="image/png")
    except:
        return Response(b"", status=404)


# ═══════════════════════════════════════════════════════
# HILFSFUNKTION: LOG-HTML BAUEN
# ═══════════════════════════════════════════════════════
def _build_log_html():
    if not log_entries:
        return '<div style="color:#475569;font-size:0.78rem">Noch keine Messungen</div>'
    return "".join(
        '<div class="log-entry">{} <b>{}g</b> {}</div>'.format(
            e.get("ts",""), e.get("g",""), e.get("note",""))
        for e in reversed(log_entries[-20:])
    )


# ═══════════════════════════════════════════════════════
# START
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print(f"  Filament-Waage Mac-Server")
    print(f"  ESP erwartet unter: {ESP_BASE}")
    print(f"  Web-UI:  http://localhost:{PORT}")
    print(f"  Log:     {LOG_FILE}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=PORT, debug=False)
