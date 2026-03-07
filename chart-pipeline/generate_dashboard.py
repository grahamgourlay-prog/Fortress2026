#!/usr/bin/env python3
"""
Portfolio Dashboard Generator
==============================
Reads CSVs from portfolio_data/ (one per ticker/interval) and generates a
single self-contained HTML dashboard.

Dashboard controls:
  - Timeframe buttons  : switch between 1H / 4H / 1D / 1W per chart
  - Range presets      : 1W · 1M · 3M · 6M · 1Y · All  (Plotly built-in)
  - Zoom / Pan         : drag to zoom, scroll wheel, toolbar buttons
  - Log / Linear scale : toggle on price axis
  - Indicator toggles  : SMA 20, SMA 50, Bollinger Bands, Volume, RSI, MACD
  - Tab view           : one ticker at a time
  - Grid view (⊞ All)  : compact overview of all tickers

Usage:
    python3 generate_dashboard.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERROR: Install deps: pip install pandas numpy --break-system-packages")
    sys.exit(1)

SCRIPT_DIR  = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "portfolio_config.json"


def load_config():
    if not CONFIG_FILE.exists():
        print(f"ERROR: portfolio_config.json not found"); sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def csv_path(output_dir, symbol, interval):
    return Path(output_dir) / f"{symbol.upper()}_{interval}.csv"


def load_csv(output_dir, symbol, interval):
    p = csv_path(output_dir, symbol, interval)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── Indicators ────────────────────────────────────────────────────────────────

def _clean(series):
    return [round(v, 4) if pd.notna(v) else None for v in series]

def sma(series, n):
    return _clean(series.rolling(n).mean())

def bollinger(series, n=20, sigma=2):
    mid = series.rolling(n).mean()
    std = series.rolling(n).std()
    return _clean(mid - sigma*std), _clean(mid), _clean(mid + sigma*std)

def rsi(series, n=14):
    d    = series.diff()
    gain = d.clip(lower=0).rolling(n).mean()
    loss = (-d.clip(upper=0)).rolling(n).mean()
    rs   = gain / loss.replace(0, float("nan"))
    return [round(v, 2) if pd.notna(v) else None for v in 100 - 100/(1+rs)]

def macd_calc(series, fast=12, slow=26, sig=9):
    ef  = series.ewm(span=fast, adjust=False).mean()
    es  = series.ewm(span=slow, adjust=False).mean()
    ml  = ef - es
    sl  = ml.ewm(span=sig, adjust=False).mean()
    return _clean(ml), _clean(sl), _clean(ml - sl)


def build_interval_data(df, ind_cfg):
    """Build chart data dict for one interval's DataFrame."""
    dates  = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S").tolist()
    result = {
        "dates":  dates,
        "open":   df["open"].tolist(),
        "high":   df["high"].tolist(),
        "low":    df["low"].tolist(),
        "close":  df["close"].tolist(),
        "volume": df["volume"].tolist() if "volume" in df.columns else [],
        "ind":    {},
    }

    c = df["close"]
    # Always compute ALL indicators regardless of config so JS toggles work at runtime.
    # The config's indicators section only controls which checkboxes default to checked.
    result["ind"]["sma20"] = sma(c, 20)
    result["ind"]["sma50"] = sma(c, 50)
    bl, bm, bu = bollinger(c)
    result["ind"]["bb_lower"] = bl
    result["ind"]["bb_mid"]   = bm
    result["ind"]["bb_upper"] = bu
    result["ind"]["rsi"] = rsi(c)
    ml, sl, hist = macd_calc(c)
    result["ind"]["macd_line"]   = ml
    result["ind"]["macd_signal"] = sl
    result["ind"]["macd_hist"]   = hist

    return result


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.26.0/plotly.min.js"></script>
<style>
:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#e6edf3;--mu:#8b949e;
  --ac:#58a6ff;--gn:#3fb950;--rd:#f85149;--yw:#d29922;--pu:#bc8cff;--or:#ffa657;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px}

/* Header */
header{background:var(--sf);border-bottom:1px solid var(--bd);padding:12px 20px;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap}
header h1{font-size:17px;font-weight:600;color:var(--ac)}
.upd{color:var(--mu);font-size:11px}

/* Ticker tabs */
#tab-bar{background:var(--sf);border-bottom:1px solid var(--bd);padding:0 16px;
  display:flex;gap:2px;overflow-x:auto;flex-wrap:nowrap;scrollbar-width:thin}
.tab-btn{background:none;border:none;border-bottom:3px solid transparent;color:var(--mu);
  cursor:pointer;padding:9px 13px;font-size:12px;white-space:nowrap;
  transition:color .12s,border-color .12s}
.tab-btn:hover{color:var(--tx)}
.tab-btn.active{color:var(--ac);border-bottom-color:var(--ac)}
.tab-btn.grid-btn{color:var(--yw);margin-left:auto}
.tab-btn.grid-btn.active{color:var(--yw);border-bottom-color:var(--yw)}

/* Controls row */
#controls{background:var(--sf);border-bottom:1px solid var(--bd);padding:8px 16px;
  display:flex;gap:0;align-items:center;flex-wrap:wrap;row-gap:6px}
.ctrl-section{display:flex;align-items:center;gap:10px;padding:0 12px;border-right:1px solid var(--bd)}
.ctrl-section:last-child{border-right:none}
.ctrl-label{color:var(--mu);font-size:10px;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
.ctrl-group{display:flex;gap:8px;flex-wrap:wrap;align-items:center}

/* Timeframe buttons */
.tf-btn{background:var(--bg);border:1px solid var(--bd);color:var(--mu);border-radius:4px;
  cursor:pointer;padding:3px 9px;font-size:11px;font-weight:500;transition:all .12s}
.tf-btn:hover{color:var(--tx);border-color:var(--ac)}
.tf-btn.active{background:rgba(88,166,255,.15);color:var(--ac);border-color:var(--ac)}
.tf-btn.disabled{opacity:.35;cursor:not-allowed}

/* Indicator checkboxes */
#controls label{color:var(--mu);font-size:11px;display:flex;align-items:center;gap:5px;
  cursor:pointer;user-select:none;white-space:nowrap}
#controls input[type=checkbox]{accent-color:var(--ac);width:13px;height:13px}

/* Scale toggle */
.scale-btn{background:var(--bg);border:1px solid var(--bd);color:var(--mu);border-radius:4px;
  cursor:pointer;padding:3px 9px;font-size:11px;font-weight:500;transition:all .12s}
.scale-btn:hover{color:var(--tx);border-color:var(--mu)}
.scale-btn.log-on{background:rgba(188,140,255,.15);color:var(--pu);border-color:var(--pu)}

/* Chart area */
#chart-container{padding:12px 16px}
.ticker-pane{display:none}
.ticker-pane.visible{display:block}
.chart-title{font-size:14px;font-weight:600;margin-bottom:6px;display:flex;align-items:center;gap:10px}
.chart-title .sub{color:var(--mu);font-weight:400;font-size:12px}
.chart-title .price-tag{font-size:13px;font-weight:600;padding:2px 8px;border-radius:4px;
  background:rgba(63,185,80,.12);color:var(--gn)}
.chart-title .price-tag.dn{background:rgba(248,81,73,.12);color:var(--rd)}

/* Grid */
#grid-pane{display:none;padding:12px 16px}
#grid-pane.visible{display:grid;grid-template-columns:repeat(auto-fill,minmax(540px,1fr));gap:14px}
.grid-cell{background:var(--sf);border:1px solid var(--bd);border-radius:7px;overflow:hidden}
.grid-cell-title{padding:7px 12px;font-size:12px;font-weight:600;background:var(--bg);
  border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}
.grid-cell-title .gpt{font-size:11px;font-weight:600}
.gpt.up{color:var(--gn)} .gpt.dn{color:var(--rd)}

/* No-data */
#loading{text-align:center;padding:60px;color:var(--mu)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px}
.nav-link{color:var(--mu);font-size:12px;text-decoration:none;padding:4px 12px;border:1px solid var(--bd);border-radius:4px;margin-left:auto;white-space:nowrap;transition:color .12s,border-color .12s}
.nav-link:hover{color:var(--tx);border-color:var(--ac)}
@media(max-width:640px){.tab-btn.grid-btn{display:none}}
</style>
</head>
<body>

<header>
  <h1>📈 Portfolio Dashboard</h1>
  <div class="upd">Updated: <span id="upd-ts">—</span></div>
  <a href="https://grahamgourlay-prog.github.io/Fortress2026/" class="nav-link">← Portfolio</a>
</header>

<div id="tab-bar"></div>

<div id="controls">
  <div class="ctrl-section">
    <span class="ctrl-label">Timeframe</span>
    <div class="ctrl-group" id="tf-group"></div>
  </div>
  <div class="ctrl-section">
    <span class="ctrl-label">Overlays</span>
    <div class="ctrl-group">
      <label><input type="checkbox" id="c-sma20" checked> SMA 20</label>
      <label><input type="checkbox" id="c-sma50" checked> SMA 50</label>
      <label><input type="checkbox" id="c-bb"> Bollinger</label>
    </div>
  </div>
  <div class="ctrl-section">
    <span class="ctrl-label">Sub-charts</span>
    <div class="ctrl-group">
      <label><input type="checkbox" id="c-vol" checked> Volume</label>
      <label><input type="checkbox" id="c-rsi" checked> RSI</label>
      <label><input type="checkbox" id="c-macd"> MACD</label>
    </div>
  </div>
  <div class="ctrl-section">
    <span class="ctrl-label">Scale</span>
    <div class="ctrl-group">
      <button class="scale-btn" id="log-btn" onclick="toggleLog()">Log</button>
    </div>
  </div>
</div>

<div id="loading">No data — run fetch_portfolio.py first.</div>
<div id="chart-container" style="display:none"></div>
<div id="grid-pane"></div>

<script>
// ── Embedded data (injected by generate_dashboard.py) ─────────────────────────
const DATA        = /*DATA*/null/*ENDDATA*/;
const INTERVALS   = /*INTERVALS*/[]/*ENDINTERVALS*/;
const DEFAULT_IV  = "/*DEFAULTIV*/1day/*ENDDEFAULTIV*/";
const GENERATED   = "/*GENERATED*//*ENDGENERATED*/";

// ── Theme ─────────────────────────────────────────────────────────────────────
const C = {
  bg:"#0d1117", sf:"#161b22", bd:"#30363d", tx:"#e6edf3", mu:"#8b949e",
  ac:"#58a6ff", gn:"#3fb950", rd:"#f85149", yw:"#d29922", pu:"#bc8cff", or:"#ffa657"
};

const PLOTLY_CFG = {
  responsive:true, displayModeBar:true, displaylogo:false,
  scrollZoom:true,
  modeBarButtonsToRemove:["lasso2d","select2d","toImage"],
  modeBarButtonsToAdd:[{
    name:"Download PNG", icon:Plotly.Icons.camera,
    click: gd => Plotly.downloadImage(gd,{format:"png",width:1400,height:800,filename:gd.id})
  }]
};

// ── State ─────────────────────────────────────────────────────────────────────
let activeTab     = null;
let activeIv      = DEFAULT_IV;
let logScale      = false;
const rendered    = {};   // rendered["SYM/iv"] = true
const gridRendered = {};

// ── Controls ──────────────────────────────────────────────────────────────────
function indOn() {
  return {
    sma20: document.getElementById("c-sma20").checked,
    sma50: document.getElementById("c-sma50").checked,
    bb:    document.getElementById("c-bb").checked,
    vol:   document.getElementById("c-vol").checked,
    rsi:   document.getElementById("c-rsi").checked,
    macd:  document.getElementById("c-macd").checked,
  };
}

function toggleLog() {
  logScale = !logScale;
  document.getElementById("log-btn").classList.toggle("log-on", logScale);
  if (activeTab && activeTab !== "__grid__") rebuildActive();
}

function setInterval_(iv) {
  activeIv = iv;
  document.querySelectorAll(".tf-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.iv === iv));
  if (activeTab && activeTab !== "__grid__") renderTab(activeTab, true);
}

// ── Indicator checkbox listeners ──────────────────────────────────────────────
["c-sma20","c-sma50","c-bb","c-vol","c-rsi","c-macd"].forEach(id => {
  document.getElementById(id)?.addEventListener("change", () => {
    if (activeTab && activeTab !== "__grid__") rebuildActive();
  });
});

function rebuildActive() {
  if (!activeTab || activeTab === "__grid__") return;
  renderTab(activeTab, true);
}

// ── Range preset buttons (injected into Plotly layout) ────────────────────────
function rangeSelector(iv) {
  // Only meaningful for daily+ intervals
  const daily = ["1day","1week"];
  if (!daily.includes(iv)) return { visible: false };
  return {
    visible: true,
    bgcolor: C.sf, activecolor: C.ac, bordercolor: C.bd,
    font: { color: C.mu, size: 10 },
    buttons: [
      { count:1,  label:"1M",  step:"month",  stepmode:"backward" },
      { count:3,  label:"3M",  step:"month",  stepmode:"backward" },
      { count:6,  label:"6M",  step:"month",  stepmode:"backward" },
      { count:1,  label:"1Y",  step:"year",   stepmode:"backward" },
      { step:"all", label:"All" },
    ]
  };
}

// ── Build chart traces + layout ───────────────────────────────────────────────
function buildChart(containerId, td, iv, opts, compact) {
  const ivData = td.intervals[iv];
  if (!ivData) {
    document.getElementById(containerId).innerHTML =
      `<div style="color:var(--mu);padding:30px;text-align:center">No ${iv} data — run fetch_portfolio.py --interval ${iv}</div>`;
    return;
  }

  const ind   = opts || indOn();
  const dates = ivData.dates;
  const o     = ivData;

  // Sub-chart rows (order determines top-to-bottom visual order below price panel)
  const subRows = [];
  if (!compact && ind.vol && o.volume?.length)       subRows.push("vol");
  if (!compact && ind.rsi && ivData.ind?.rsi)        subRows.push("rsi");
  if (!compact && ind.macd && ivData.ind?.macd_line) subRows.push("macd");

  // ── Domain layout ────────────────────────────────────────────────────────────
  // Plotly domains: 0 = bottom of paper, 1 = top of paper.
  // Layout order (bottom→top): last sub, …, first sub, main price panel.
  const nSubs    = subRows.length;
  const panelGap = 0.04;                          // gap between panels
  const gapTotal = nSubs * panelGap;
  const avail    = 1 - gapTotal;
  // Give price panel more space when fewer sub-panels
  const mainFrac = compact ? 1 : (nSubs === 0 ? 1 : nSubs === 1 ? 0.65 : 0.58);
  const subFrac  = nSubs > 0 ? (1 - mainFrac) / nSubs : 0;
  const mainH    = avail * mainFrac;
  const subH     = avail * subFrac;

  const domOf = {};
  let cur = 0;
  // Place sub-panels from bottom up (last in subRows = bottom-most)
  for (let i = subRows.length - 1; i >= 0; i--) {
    domOf[subRows[i]] = [parseFloat(cur.toFixed(4)), parseFloat((cur + subH).toFixed(4))];
    cur += subH + panelGap;
  }
  domOf.main = [parseFloat(cur.toFixed(4)), 1.0];

  // x-axis must anchor to the BOTTOM-MOST y-axis so date labels appear at the
  // very bottom of the chart (below all sub-panels).
  const xAnchorIdx = nSubs > 0 ? nSubs + 1 : 1;
  const xAnchor    = xAnchorIdx === 1 ? "y" : xAnchorIdx === 2 ? "y2" : `y${xAnchorIdx}`;

  // ── Traces ───────────────────────────────────────────────────────────────────
  const traces = [];

  // Candlestick
  traces.push({
    type:"candlestick", name:td.symbol,
    x:dates, open:o.open, high:o.high, low:o.low, close:o.close,
    increasing:{ line:{color:C.gn}, fillcolor:C.gn },
    decreasing:{ line:{color:C.rd}, fillcolor:C.rd },
    xaxis:"x", yaxis:"y", showlegend:false, hoverinfo:"x+y",
  });

  // SMA 20
  if (ind.sma20 && ivData.ind?.sma20) {
    traces.push({ type:"scatter", name:"SMA 20",
      x:dates, y:ivData.ind.sma20,
      line:{color:C.ac, width:1.3}, xaxis:"x", yaxis:"y", hoverinfo:"x+y" });
  }
  // SMA 50
  if (ind.sma50 && ivData.ind?.sma50) {
    traces.push({ type:"scatter", name:"SMA 50",
      x:dates, y:ivData.ind.sma50,
      line:{color:C.or, width:1.3}, xaxis:"x", yaxis:"y", hoverinfo:"x+y" });
  }
  // Bollinger Bands
  if (ind.bb && ivData.ind?.bb_upper) {
    const bc = "rgba(188,140,255,0.65)";
    traces.push({ type:"scatter", name:"BB Upper",
      x:dates, y:ivData.ind.bb_upper,
      line:{color:bc,width:1,dash:"dot"}, xaxis:"x", yaxis:"y", hoverinfo:"x+y" });
    traces.push({ type:"scatter", name:"BB Mid",
      x:dates, y:ivData.ind.bb_mid,
      line:{color:bc,width:1}, xaxis:"x", yaxis:"y", hoverinfo:"x+y" });
    traces.push({ type:"scatter", name:"BB Lower",
      x:dates, y:ivData.ind.bb_lower,
      line:{color:bc,width:1,dash:"dot"},
      fill:"tonexty", fillcolor:"rgba(188,140,255,0.04)",
      xaxis:"x", yaxis:"y", hoverinfo:"x+y" });
  }

  // Sub-chart y-axis definitions + traces
  // NOTE: all traces share xaxis:"x" — the explicit yaxis domains separate panels visually.
  const subAxisDefs = {};
  subRows.forEach((sub, idx) => {
    const yIdx = idx + 2;
    const yRef = yIdx === 2 ? "y2" : `y${yIdx}`;
    const yKey = yIdx === 2 ? "yaxis2" : `yaxis${yIdx}`;

    subAxisDefs[yKey] = {
      domain: domOf[sub],
      anchor: "x",
      showgrid:true, gridcolor:C.bd, zeroline:false,
      tickfont:{color:C.mu, size:9}, linecolor:C.bd,
      fixedrange: false,
    };

    if (sub === "vol") {
      const vc = dates.map((_,i) =>
        (o.close[i]??0) >= (o.open[i]??0) ? "rgba(63,185,80,0.55)" : "rgba(248,81,73,0.55)");
      traces.push({ type:"bar", name:"Volume", x:dates, y:o.volume,
        marker:{color:vc}, xaxis:"x", yaxis:yRef, showlegend:false, hoverinfo:"x+y" });
      subAxisDefs[yKey].title = {text:"Vol", font:{color:C.mu,size:9}};
    }
    if (sub === "rsi") {
      subAxisDefs[yKey].range = [0,100];
      traces.push({ type:"scatter", name:"RSI", x:dates, y:ivData.ind.rsi,
        line:{color:C.yw, width:1.5}, xaxis:"x", yaxis:yRef, hoverinfo:"x+y" });
      const xEdges = [dates[0], dates[dates.length-1]];
      traces.push({ type:"scatter", x:xEdges, y:[70,70],
        line:{color:"rgba(248,81,73,0.35)",width:1,dash:"dash"},
        xaxis:"x", yaxis:yRef, showlegend:false, hoverinfo:"none" });
      traces.push({ type:"scatter", x:xEdges, y:[30,30],
        line:{color:"rgba(63,185,80,0.35)",width:1,dash:"dash"},
        xaxis:"x", yaxis:yRef, showlegend:false, hoverinfo:"none" });
      subAxisDefs[yKey].title = {text:"RSI", font:{color:C.mu,size:9}};
    }
    if (sub === "macd") {
      subAxisDefs[yKey].zeroline = true;
      subAxisDefs[yKey].zerolinecolor = C.bd;
      const hc = ivData.ind.macd_hist.map(v =>
        v===null?"transparent":v>=0?"rgba(63,185,80,0.6)":"rgba(248,81,73,0.6)");
      traces.push({ type:"bar", name:"MACD Hist", x:dates, y:ivData.ind.macd_hist,
        marker:{color:hc}, xaxis:"x", yaxis:yRef, showlegend:false, hoverinfo:"x+y" });
      traces.push({ type:"scatter", name:"MACD", x:dates, y:ivData.ind.macd_line,
        line:{color:C.ac,width:1.5}, xaxis:"x", yaxis:yRef, hoverinfo:"x+y" });
      traces.push({ type:"scatter", name:"Signal", x:dates, y:ivData.ind.macd_signal,
        line:{color:C.or,width:1.5}, xaxis:"x", yaxis:yRef, hoverinfo:"x+y" });
      subAxisDefs[yKey].title = {text:"MACD", font:{color:C.mu,size:9}};
    }
  });

  // ── Layout ───────────────────────────────────────────────────────────────────
  const layout = {
    paper_bgcolor:C.sf, plot_bgcolor:C.bg,
    font:{color:C.tx, family:"-apple-system,sans-serif", size:10},
    height: compact ? 260 : Math.max(420, 340 + nSubs * 120),
    margin:{ l:55, r:20, t:compact?15:20, b:compact?30:40 },
    hovermode:"x unified",
    hoverlabel:{bgcolor:"#21262d", bordercolor:C.bd, font:{color:C.tx}},
    legend:{bgcolor:"rgba(0,0,0,0)", bordercolor:C.bd, borderwidth:1,
            font:{color:C.mu, size:9}, x:0, y:1.02, orientation:"h"},
    xaxis:{
      domain:[0,1],
      anchor: xAnchor,        // anchored to bottom-most panel → date labels at bottom
      showgrid:true, gridcolor:C.bd, zeroline:false,
      tickfont:{color:C.mu,size:9}, linecolor:C.bd,
      rangeslider:{visible:false},
      rangeselector: compact ? {visible:false} : rangeSelector(iv),
      showspikes:true, spikemode:"across", spikesnap:"cursor",
      spikethickness:1, spikecolor:C.mu, spikedash:"dot",
    },
    yaxis:{
      domain: domOf.main,
      anchor:"x",
      showgrid:true, gridcolor:C.bd, zeroline:false,
      tickfont:{color:C.mu,size:9}, linecolor:C.bd,
      type: logScale ? "log" : "linear",
      fixedrange: false,
      autorange: true,
      rangemode: "normal",    // never force y=0 into range
      showspikes:true, spikemode:"across", spikesnap:"cursor",
      spikethickness:1, spikecolor:C.mu, spikedash:"dot",
    },
    ...subAxisDefs,
  };

  Plotly.newPlot(containerId, traces, layout, PLOTLY_CFG);
}

// ── Price badge helper ─────────────────────────────────────────────────────────
function priceBadge(td, iv) {
  const d = td.intervals[iv];
  if (!d || !d.close?.length) return "";
  const last = d.close[d.close.length - 1];
  const prev = d.close[d.close.length - 2] ?? last;
  const pct  = ((last - prev) / prev * 100).toFixed(2);
  const cls  = last >= prev ? "up" : "dn";
  const sign = last >= prev ? "+" : "";
  return `<span class="price-tag ${last<prev?"dn":""}">${last?.toFixed?.(last>10?2:4)??""} <small>(${sign}${pct}%)</small></span>`;
}

// ── Show tab ───────────────────────────────────────────────────────────────────
function showTab(symbol) {
  document.querySelectorAll(".ticker-pane").forEach(p=>p.classList.remove("visible"));
  document.getElementById("grid-pane").classList.remove("visible");
  document.getElementById("chart-container").style.display = "block";
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.symbol === symbol));

  activeTab = symbol;
  const pane = document.getElementById(`pane-${symbol}`);
  if (pane) {
    pane.classList.add("visible");
    renderTab(symbol, false);
  }
  // Update timeframe buttons availability
  updateTfButtons(symbol);
}

function renderTab(symbol, force) {
  const key = `${symbol}/${activeIv}`;
  const td  = DATA[symbol];
  if (!td) return;

  // Always re-render (indicators/scale may have changed)
  buildChart(`chart-${symbol}`, td, activeIv);
  rendered[key] = true;

  // Update price badge
  const badge = document.getElementById(`badge-${symbol}`);
  if (badge) badge.innerHTML = priceBadge(td, activeIv);
}

function updateTfButtons(symbol) {
  const td = DATA[symbol];
  if (!td) return;
  document.querySelectorAll(".tf-btn").forEach(b => {
    const has = !!td.intervals[b.dataset.iv];
    b.classList.toggle("disabled", !has);
    b.onclick = has ? () => setInterval_(b.dataset.iv) : null;
    b.title = has ? "" : `No ${b.dataset.iv} data — run fetch_portfolio.py --interval ${b.dataset.iv}`;
  });
}

// ── Grid view ──────────────────────────────────────────────────────────────────
function showGrid() {
  document.querySelectorAll(".ticker-pane").forEach(p=>p.classList.remove("visible"));
  document.getElementById("chart-container").style.display = "none";
  document.getElementById("grid-pane").classList.add("visible");
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", b.classList.contains("grid-btn")));
  activeTab = "__grid__";

  Object.values(DATA).forEach(td => {
    const key = `grid-${td.symbol}`;
    if (!gridRendered[key]) {
      const opts = {sma20:true,sma50:true,bb:false,vol:true,rsi:false,macd:false};
      buildChart(`gchart-${td.symbol}`, td, activeIv, opts, true);
      gridRendered[key] = true;
    }
    // Update price badge in grid
    const badge = document.getElementById(`gbadge-${td.symbol}`);
    if (badge) {
      const d = td.intervals[activeIv];
      if (d?.close?.length) {
        const last = d.close[d.close.length-1];
        const prev = d.close[d.close.length-2]??last;
        const pct  = ((last-prev)/prev*100).toFixed(2);
        const cls  = last>=prev?"up":"dn";
        const sign = last>=prev?"+":"";
        badge.className = `gpt ${cls}`;
        badge.textContent = `${last?.toFixed?.(last>10?2:4)??""} (${sign}${pct}%)`;
      }
    }
  });
}

// ── Boot ───────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  if (!DATA || Object.keys(DATA).length === 0) return;

  document.getElementById("loading").style.display = "none";
  document.getElementById("upd-ts").textContent = GENERATED;

  // Build timeframe buttons
  const tfGroup = document.getElementById("tf-group");
  INTERVALS.forEach(iv => {
    const b = document.createElement("button");
    b.className = "tf-btn" + (iv.id === DEFAULT_IV ? " active" : "");
    b.dataset.iv = iv.id;
    b.textContent = iv.label;
    b.onclick = () => setInterval_(iv.id);
    tfGroup.appendChild(b);
  });

  // Build ticker tabs + panes + grid cells
  const tabBar   = document.getElementById("tab-bar");
  const container= document.getElementById("chart-container");
  const grid     = document.getElementById("grid-pane");

  Object.values(DATA).forEach(td => {
    // Tab
    const btn = document.createElement("button");
    btn.className = "tab-btn";
    btn.dataset.symbol = td.symbol;
    btn.textContent = td.symbol;
    btn.title = td.label;
    btn.onclick = () => showTab(td.symbol);
    tabBar.appendChild(btn);

    // Pane
    const pane = document.createElement("div");
    pane.className = "ticker-pane";
    pane.id = `pane-${td.symbol}`;
    pane.innerHTML =
      `<div class="chart-title">
        ${td.symbol}
        <span class="sub">${td.label}</span>
        <span id="badge-${td.symbol}"></span>
       </div>
       <div id="chart-${td.symbol}"></div>`;
    container.appendChild(pane);

    // Grid cell
    const cell = document.createElement("div");
    cell.className = "grid-cell";
    cell.innerHTML =
      `<div class="grid-cell-title">
        <span>${td.symbol} — ${td.label}</span>
        <span class="gpt" id="gbadge-${td.symbol}"></span>
       </div>
       <div id="gchart-${td.symbol}" style="cursor:pointer" onclick="showTab('${td.symbol}')"></div>`;
    grid.appendChild(cell);
  });

  // Grid tab button
  const gridBtn = document.createElement("button");
  gridBtn.className = "tab-btn grid-btn";
  gridBtn.textContent = "⊞ All";
  gridBtn.onclick = showGrid;
  tabBar.appendChild(gridBtn);

  // Deep-link: honour ?ticker=SYM in URL, fall back to first ticker
  const _params = new URLSearchParams(window.location.search);
  const _tickerParam = _params.get('ticker');
  const first = Object.keys(DATA)[0];
  if (_tickerParam && DATA[_tickerParam]) {
    showTab(_tickerParam);
  } else if (first) {
    showTab(first);
  }
});
</script>
</body>
</html>
"""


def generate_dashboard(config):
    tickers     = config.get("tickers", [])
    intervals   = config.get("intervals", [{"id":"1day","label":"1D","outputsize":365}])
    ind_cfg     = config.get("chart", {}).get("indicators", {})
    default_iv  = config.get("default_interval", intervals[0]["id"])
    output_dir  = SCRIPT_DIR / config.get("output_dir", "portfolio_data")
    out_file    = SCRIPT_DIR / config.get("dashboard_file", "portfolio_dashboard.html")

    # ── Load all data: {symbol: {label, intervals: {iv_id: {...}}}} ───────────
    all_data = {}   # keyed by symbol, JS-safe

    for ticker in tickers:
        symbol = ticker["symbol"]
        label  = ticker.get("label", symbol)
        ticker_ivs = {}

        for iv in intervals:
            iv_id = iv["id"]
            df = load_csv(output_dir, symbol, iv_id)
            if df is None or df.empty:
                continue
            ticker_ivs[iv_id] = build_interval_data(df, ind_cfg)

        if not ticker_ivs:
            print(f"  ⚠  {symbol:<8} no CSVs found — skipped")
            continue

        available = list(ticker_ivs.keys())
        print(f"  ✓  {symbol:<8}  intervals: {', '.join(available)}")
        all_data[symbol] = {
            "symbol":    symbol,
            "label":     label,
            "intervals": ticker_ivs,
        }

    if not all_data:
        print("\nERROR: No data. Run fetch_portfolio.py first.")
        return None

    generated_at = datetime.now().strftime("%d %b %Y %H:%M")
    iv_meta      = [{"id": iv["id"], "label": iv["label"]} for iv in intervals]

    html = HTML \
        .replace("/*DATA*/null/*ENDDATA*/",                json.dumps(all_data)) \
        .replace("/*INTERVALS*/[]/*ENDINTERVALS*/",         json.dumps(iv_meta)) \
        .replace("/*DEFAULTIV*/1day/*ENDDEFAULTIV*/",       default_iv) \
        .replace("/*GENERATED*//*ENDGENERATED*/",           generated_at)

    out_file.write_text(html, encoding="utf-8")
    return out_file


def main():
    print("Building dashboard...\n")
    config   = load_config()
    out_file = generate_dashboard(config)
    if out_file:
        size_kb = out_file.stat().st_size / 1024
        print(f"\n✓ {out_file.name}  ({size_kb:.0f} KB)")
        print("Open in Cowork or any browser — fully interactive.")


if __name__ == "__main__":
    main()
