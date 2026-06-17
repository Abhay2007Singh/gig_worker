from __future__ import annotations

import html
import json
import os
import re
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from income_ledger.parser import ScannedPdfError
from income_ledger.pipeline import run_pipeline
from income_ledger.render_report import render_results_fragment

_FIELD_NAME_RE = re.compile(rb'name="([^"]*)"')
_FILENAME_RE = re.compile(rb'filename="([^"]*)"')


def parse_multipart_form_file(body: bytes, content_type: str, field_name: str) -> tuple[str, bytes] | None:
    boundary_match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not boundary_match:
        return None
    boundary = boundary_match.group(1).encode("utf-8")
    delimiter = b"--" + boundary

    parts = body.split(delimiter)
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue

        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue

        headers_raw = part[:header_end]
        content = part[header_end + 4:]
        if content.endswith(b"\r\n"):
            content = content[:-2]

        name_match = _FIELD_NAME_RE.search(headers_raw)
        if not name_match or name_match.group(1).decode("utf-8") != field_name:
            continue

        filename_match = _FILENAME_RE.search(headers_raw)
        if not filename_match:
            continue

        filename = filename_match.group(1).decode("utf-8")
        return filename, content

    return None


SPA_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gig Income Ledger</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, Segoe UI, Arial, sans-serif;
    background: #f8fafc;
    color: #1f2937;
    min-height: 100vh;
  }
  .shell { max-width: 780px; margin: 0 auto; padding: 32px 16px 64px; }

  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 28px; }
  .header h1 { font-size: 1.35rem; font-weight: 700; }
  .header p  { font-size: 0.82rem; color: #6b7280; margin-top: 2px; }
  .btn-ghost {
    background: none; border: 1px solid #d1d5db; border-radius: 6px;
    padding: 6px 14px; font-size: 0.85rem; cursor: pointer; color: #374151;
  }
  .btn-ghost:hover { background: #f3f4f6; }
  .btn-remove {
    background: none; border: none; cursor: pointer; color: #9ca3af;
    font-size: 1rem; padding: 0 4px; line-height: 1; flex-shrink: 0;
  }
  .btn-remove:hover { color: #dc2626; }

  #drop-zone {
    border: 2px dashed #94a3b8; border-radius: 12px;
    padding: 40px 24px; text-align: center;
    transition: border-color .15s, background .15s;
    cursor: pointer; background: #fff;
  }
  #drop-zone.drag-over { border-color: #2563eb; background: #eff6ff; }
  #drop-zone svg { width: 40px; height: 40px; stroke: #94a3b8; margin-bottom: 12px; }
  #drop-zone p  { color: #6b7280; font-size: 0.9rem; }
  #drop-zone strong { color: #1f2937; }
  #file-input { display: none; }
  .btn-primary {
    display: inline-block; margin-top: 14px;
    background: #2563eb; color: #fff; border: none;
    padding: 9px 22px; border-radius: 6px; font-size: 0.95rem;
    cursor: pointer; font-weight: 500;
  }
  .btn-primary:hover { background: #1d4ed8; }
  .btn-primary:disabled { background: #93c5fd; cursor: not-allowed; }

  #file-list { margin-top: 20px; display: flex; flex-direction: column; gap: 8px; }
  .file-row {
    display: flex; align-items: center; gap: 10px;
    background: #fff; border: 1px solid #e5e7eb;
    border-radius: 8px; padding: 10px 14px;
  }
  .file-row .fname { flex: 1; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill {
    font-size: 0.75rem; font-weight: 600; padding: 3px 10px;
    border-radius: 99px; white-space: nowrap;
  }
  .pill-waiting  { background: #f3f4f6; color: #6b7280; }
  .pill-uploading{ background: #dbeafe; color: #1d4ed8; }
  .pill-parsing  { background: #fef3c7; color: #92400e; }
  .pill-done     { background: #dcfce7; color: #166534; }
  .pill-error    { background: #fee2e2; color: #991b1b; }
  .file-err-msg  { font-size: 0.78rem; color: #991b1b; margin-top: 3px; }

  #confirm-section { margin-top: 28px; }
  #confirm-section h2 {
    font-size: 1rem; font-weight: 700; margin-bottom: 10px;
    color: #92400e; display: flex; align-items: center; gap: 6px;
  }
  .confirm-card {
    background: #fffbeb; border: 1px solid #fcd34d;
    border-radius: 8px; padding: 12px 14px; margin-bottom: 8px;
  }
  .confirm-card .desc { font-size: 0.85rem; color: #374151; margin-bottom: 8px; }
  .confirm-card .meta { font-size: 0.78rem; color: #6b7280; margin-bottom: 10px; }
  .confirm-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .confirm-row select {
    border: 1px solid #d1d5db; border-radius: 5px; padding: 4px 8px;
    font-size: 0.82rem; background: #fff;
  }
  .btn-confirm { background: #2563eb; color:#fff; border:none; border-radius:5px; padding:4px 12px; font-size:0.82rem; cursor:pointer; }
  .btn-confirm:hover { background:#1d4ed8; }
  .btn-notincome { background: #fff; color:#6b7280; border:1px solid #d1d5db; border-radius:5px; padding:4px 12px; font-size:0.82rem; cursor:pointer; }
  .btn-notincome:hover { background:#f3f4f6; }

  #analyse-bar { margin-top: 22px; display: flex; align-items: center; gap: 12px; }
  #pending-note { font-size: 0.82rem; color: #92400e; }

  #results-section { margin-top: 32px; }
  #results-section h2 {
    font-size: 1rem; font-weight: 700; border-bottom: 1px solid #e5e7eb;
    padding-bottom: 5px; margin-top: 24px; margin-bottom: 10px;
  }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 12px; margin-top: 8px; }
  .kpi-card { background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:14px 16px; }
  .kpi-card .label { font-size:0.75rem; color:#6b7280; text-transform:uppercase; letter-spacing:.04em; }
  .kpi-card .value { font-size:1.35rem; font-weight:700; margin-top:4px; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size:0.88rem; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #e5e7eb; }
  th { font-size:0.78rem; text-transform:uppercase; color:#6b7280; letter-spacing:.04em; }
  .summary-box { background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:14px 16px; margin-top:8px; font-size:0.9rem; line-height:1.6; }
  .disclaimer { font-size:0.78rem; color:#9ca3af; margin-top:28px; line-height:1.6; }
  .badge { display:inline-block; padding:3px 10px; border-radius:4px; font-size:0.75rem; font-weight:700; color:#fff; }
  .badge-synth { background:#b45309; }
  .badge-real  { background:#15803d; }

  .chart-wrap { overflow-x: auto; margin-top: 8px; }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width:14px; height:14px; border:2px solid #93c5fd; border-top-color:#2563eb; border-radius:50%; display:inline-block; animation:spin .7s linear infinite; vertical-align:middle; }
</style>
</head>
<body>
<div class="shell">

  <div class="header">
    <div>
      <h1>Gig Income Ledger</h1>
      <p>Upload bank statements or platform exports to reconstruct your income.</p>
    </div>
    <button class="btn-ghost" id="btn-reset" style="display:none">&#8635; Upload again</button>
  </div>

  <div id="upload-view">
    <div id="drop-zone" role="button" tabindex="0" aria-label="Drop files here or click to browse">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/>
      </svg>
      <p><strong>Drop PDF files here</strong> or click to browse</p>
      <p style="margin-top:6px;font-size:0.78rem">Bank statements &amp; platform exports — multiple files supported</p>
      <input type="file" id="file-input" accept="application/pdf" multiple>
      <br>
      <button class="btn-primary" id="btn-browse" type="button">Browse files</button>
    </div>

    <div id="file-list"></div>

    <div id="confirm-section" style="display:none">
      <h2>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>
        Needs confirmation (<span id="confirm-count">0</span>)
      </h2>
      <div id="confirm-cards"></div>
    </div>

    <div id="analyse-bar" style="display:none">
      <button class="btn-primary" id="btn-analyse" type="button">Generate Report</button>
      <span id="pending-note" style="display:none"></span>
    </div>
  </div>

  <div id="results-view" style="display:none">
    <div id="results-section"></div>
    <p class="disclaimer">
      This tool reconstructs past income from available records. It is not a
      credit score, not a lending product, and does not provide financial
      advice or eligibility recommendations.
    </p>
  </div>

</div>

<script>
async function parseRealFile(file) {
  const formData = new FormData();
  formData.append('statement', file);
  const res = await fetch('/upload', { method: 'POST', body: formData });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Server error ${res.status}`);
  return data;
}

let fileQueue   = [];
let allEvents   = [];
let pendingConf = [];

const dropZone      = document.getElementById('drop-zone');
const fileInput     = document.getElementById('file-input');
const fileList      = document.getElementById('file-list');
const confirmSec    = document.getElementById('confirm-section');
const confirmCards  = document.getElementById('confirm-cards');
const confirmCount  = document.getElementById('confirm-count');
const analyseBar    = document.getElementById('analyse-bar');
const btnAnalyse    = document.getElementById('btn-analyse');
const pendingNote   = document.getElementById('pending-note');
const uploadView    = document.getElementById('upload-view');
const resultsView   = document.getElementById('results-view');
const resultsSection= document.getElementById('results-section');
const btnReset      = document.getElementById('btn-reset');

function dedupKey(ev) {
  return `${ev.date}|${ev.amount}|${ev.platform}`;
}

function addFiles(newFiles) {
  const toProcess = [];
  for (const file of newFiles) {
    if (!file.name.toLowerCase().endsWith('.pdf')) continue;
    if (fileQueue.some(f => f.file.name === file.name && f.file.size === file.size)) continue;
    const entry = { id: crypto.randomUUID(), file, status: 'uploading', error: null };
    fileQueue.push(entry);
    toProcess.push(entry);
  }
  renderFileList();
  updateAnalyseBar();
  toProcess.forEach(entry => processFile(entry));
}

function renderFileList() {
  fileList.innerHTML = '';
  for (const entry of fileQueue) {
    const row = document.createElement('div');
    row.className = 'file-row';
    row.dataset.id = entry.id;

    const fname = document.createElement('span');
    fname.className = 'fname';
    fname.title = entry.file.name;
    fname.textContent = entry.file.name;

    const pill = document.createElement('span');
    pill.className = 'pill ' + pillClass(entry.status);
    pill.textContent = pillLabel(entry.status);

    row.appendChild(fname);
    if (entry.status === 'uploading' || entry.status === 'parsing') {
      const spin = document.createElement('span');
      spin.className = 'spinner';
      row.appendChild(spin);
    }
    row.appendChild(pill);

    if (entry.status === 'done' || entry.status === 'error') {
      const btnRm = document.createElement('button');
      btnRm.className = 'btn-remove';
      btnRm.title = 'Remove this file';
      btnRm.textContent = '✕';
      btnRm.addEventListener('click', () => removeFile(entry.id));
      row.appendChild(btnRm);
    }

    if (entry.error) {
      const errDiv = document.createElement('div');
      errDiv.className = 'file-err-msg';
      errDiv.textContent = entry.error;
      const wrap = document.createElement('div');
      wrap.style.width = '100%';
      wrap.appendChild(row);
      wrap.appendChild(errDiv);
      fileList.appendChild(wrap);
    } else {
      fileList.appendChild(row);
    }
  }
}

function updateFileStatus(id, status, error) {
  const entry = fileQueue.find(f => f.id === id);
  if (entry) { entry.status = status; entry.error = error || null; }
  renderFileList();
}

function removeFile(id) {
  fileQueue = fileQueue.filter(f => f.id !== id);
  renderFileList();
  updateAnalyseBar();
}

function pillClass(status) {
  return { uploading:'pill-uploading', parsing:'pill-parsing',
           done:'pill-done', error:'pill-error' }[status] || 'pill-waiting';
}
function pillLabel(status) {
  return { uploading:'Uploading…', parsing:'Parsing…',
           done:'Done', error:'Error' }[status] || status;
}

async function processFile(entry) {
  updateFileStatus(entry.id, 'uploading');
  let events;
  try {
    updateFileStatus(entry.id, 'parsing');
    events = await parseRealFile(entry.file);
  } catch (err) {
    updateFileStatus(entry.id, 'error', err.message || 'Upload failed');
    return;
  }

  if (!Array.isArray(events) || events.length === 0) {
    updateFileStatus(entry.id, 'error', 'No transactions found — check the terminal for parser details.');
    return;
  }

  const existingKeys = new Set(allEvents.map(dedupKey).concat(pendingConf.map(dedupKey)));
  for (const ev of events) {
    const key = dedupKey(ev);
    if (existingKeys.has(key)) continue;
    existingKeys.add(key);

    if (ev.direction === 'debit' && ev.event_type !== 'reversal') continue;

    if (ev.confidence >= 0.7) {
      allEvents.push(ev);
    } else {
      pendingConf.push(ev);
    }
  }

  updateFileStatus(entry.id, 'done');
  renderConfirmQueue();
  updateAnalyseBar();

  const allFinished = fileQueue.every(f => f.status === 'done' || f.status === 'error');
  if (allFinished && pendingConf.length === 0) {
    showResults();
  }
}

function renderConfirmQueue() {
  confirmCount.textContent = pendingConf.length;
  confirmSec.style.display = pendingConf.length > 0 ? '' : 'none';
  confirmCards.innerHTML = '';

  pendingConf.forEach((ev, idx) => {
    const card = document.createElement('div');
    card.className = 'confirm-card';
    card.dataset.idx = idx;

    card.innerHTML = `
      <div class="desc">${escHtml(ev.raw_description)}</div>
      <div class="meta">
        Date: ${escHtml(ev.date)} &nbsp;|&nbsp;
        Amount: Rs ${Number(ev.amount).toLocaleString('en-IN', {minimumFractionDigits:2})} &nbsp;|&nbsp;
        Confidence: ${(ev.confidence * 100).toFixed(0)}%
      </div>
      <div class="confirm-row">
        <select data-idx="${idx}">
          <option value="">— select platform —</option>
          <option value="swiggy">Swiggy</option>
          <option value="zomato">Zomato</option>
          <option value="uber">Uber</option>
          <option value="ola">Ola</option>
          <option value="rapido">Rapido</option>
        </select>
        <button class="btn-confirm" data-idx="${idx}">Confirm</button>
        <button class="btn-notincome" data-idx="${idx}">Not income</button>
      </div>`;
    confirmCards.appendChild(card);
  });

  confirmCards.onclick = (e) => {
    const idx = parseInt(e.target.dataset.idx, 10);
    if (isNaN(idx)) return;

    if (e.target.classList.contains('btn-confirm')) {
      const sel = confirmCards.querySelector(`select[data-idx="${idx}"]`);
      if (!sel.value) { sel.style.borderColor = '#f59e0b'; return; }
      const ev = pendingConf[idx];
      ev.platform = sel.value;
      const key = dedupKey(ev);
      if (!allEvents.some(e => dedupKey(e) === key)) allEvents.push(ev);
      removeConfirmItem(idx);
    } else if (e.target.classList.contains('btn-notincome')) {
      removeConfirmItem(idx);
    }
  };

  updateAnalyseBar();
}

function removeConfirmItem(idx) {
  pendingConf.splice(idx, 1);
  renderConfirmQueue();
  updateAnalyseBar();
}

function updateAnalyseBar() {
  const allFinished = fileQueue.length > 0 &&
    fileQueue.every(f => f.status === 'done' || f.status === 'error');
  const anyDone = fileQueue.some(f => f.status === 'done');

  analyseBar.style.display = (allFinished && anyDone) ? '' : 'none';

  const hasPending = pendingConf.length > 0;
  const hasConfirmed = allEvents.length > 0;

  if (hasPending) {
    pendingNote.style.display = '';
    pendingNote.textContent =
      `${pendingConf.length} item(s) need confirmation above. ` +
      (hasConfirmed
        ? 'You can generate the report now using confirmed events, or resolve them first.'
        : 'All events need confirmation — resolve them to generate a report.');
    btnAnalyse.textContent = hasConfirmed ? 'Generate Report' : 'Generate Report (0 confirmed)';
    btnAnalyse.disabled = !hasConfirmed;
  } else {
    pendingNote.style.display = 'none';
    btnAnalyse.textContent = 'Generate Report';
    btnAnalyse.disabled = !hasConfirmed;
  }
}

function showResults() {
  uploadView.style.display = 'none';
  resultsView.style.display = '';
  btnReset.style.display = '';

  if (allEvents.length === 0) {
    resultsSection.innerHTML = `
      <div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:20px 24px;margin-top:16px">
        <strong>No confirmed income events found.</strong><br><br>
        This can happen when:
        <ul style="margin-top:8px;margin-left:18px;line-height:1.8">
          <li>The PDF is not in SBI bank statement format</li>
          <li>All transactions were flagged as needing confirmation — go back and resolve them</li>
          <li>The statement contains no gig platform credits (Swiggy, Zomato, Uber, Ola, Rapido)</li>
        </ul>
        <button class="btn-ghost" onclick="document.getElementById('btn-reset').click()"
                style="margin-top:14px">&#8635; Upload again</button>
      </div>`;
    return;
  }

  resultsSection.innerHTML = buildResultsHTML(allEvents);
}

function buildResultsHTML(events) {
  const byMonth = {};
  const byPlatform = {};
  let total = 0;

  for (const ev of events) {
    if (ev.event_type !== 'payout' && ev.event_type !== 'reversal') continue;
    if (ev.event_type === 'payout' && ev.direction === 'debit') continue;

    const month = ev.date.slice(0, 7);
    const platform = ev.platform === 'unknown' ? null : ev.platform;

    const sign = ev.event_type === 'reversal' ? -1 : 1;
    const signed = sign * ev.amount;

    byMonth[month] = (byMonth[month] || 0) + signed;
    if (platform) byPlatform[platform] = (byPlatform[platform] || 0) + signed;
    total += signed;
  }

  const months = Object.keys(byMonth).sort();
  const monthValues = months.map(m => byMonth[m]);
  const avgMonthly = months.length ? total / months.length : 0;

  const mean = avgMonthly;
  const sd = months.length > 1
    ? Math.sqrt(monthValues.reduce((s, v) => s + (v - mean) ** 2, 0) / (monthValues.length - 1))
    : 0;
  const cv = mean >= 2000 ? (sd / mean) : null;

  let trendLabel = 'Insufficient data (< 6 months)';
  if (months.length >= 6) {
    const n = monthValues.length;
    const xs = monthValues.map((_, i) => i);
    const xMean = (n - 1) / 2;
    const yMean = monthValues.reduce((a, b) => a + b, 0) / n;
    const sxx = xs.reduce((s, x) => s + (x - xMean) ** 2, 0);
    const sxy = xs.reduce((s, x, i) => s + (x - xMean) * (monthValues[i] - yMean), 0);
    const slope = sxy / sxx;
    const absSlopeRounded = Math.round(Math.abs(slope));
    if (slope > 50)       trendLabel = `Growing (~Rs ${absSlopeRounded}/month)`;
    else if (slope < -50) trendLabel = `Declining (~Rs ${absSlopeRounded}/month)`;
    else                  trendLabel = 'Stable / inconclusive';
  }

  const platRows = Object.entries(byPlatform)
    .sort((a, b) => b[1] - a[1])
    .map(([p, amt]) => {
      const pct = total > 0 ? (amt / total * 100).toFixed(1) : '0.0';
      return `<tr><td>${escHtml(cap(p))}</td>
                  <td>Rs ${fmtNum(amt)}</td>
                  <td>${pct}%</td></tr>`;
    }).join('\n');

  const chart = months.length ? buildSVG(months, monthValues) : '<p>No monthly data.</p>';

  const recent = [...events]
    .filter(ev => ev.event_type === 'payout' && ev.direction === 'credit')
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 10);
  const evRows = recent.map(ev =>
    `<tr>
       <td>${escHtml(ev.date)}</td>
       <td>${escHtml(cap(ev.platform))}</td>
       <td style="text-align:right">Rs ${fmtNum(ev.amount)}</td>
       <td style="font-size:0.78rem;color:#6b7280;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(ev.raw_description)}</td>
     </tr>`
  ).join('\n');

  return `
<span class="badge badge-real" style="margin-bottom:12px;display:inline-block">REAL STATEMENT DATA</span>

<h2>Key Metrics</h2>
<div class="kpi-grid">
  <div class="kpi-card"><div class="label">Avg monthly income</div><div class="value">Rs ${fmtNum(avgMonthly)}</div></div>
  <div class="kpi-card"><div class="label">Total income</div><div class="value">Rs ${fmtNum(total)}</div></div>
  <div class="kpi-card"><div class="label">Months tracked</div><div class="value">${months.length}</div></div>
  <div class="kpi-card"><div class="label">Events confirmed</div><div class="value">${events.length}</div></div>
</div>

<h2>Trend</h2>
<p>${escHtml(trendLabel)}</p>

<h2>Volatility</h2>
<p>Monthly SD: Rs ${fmtNum(sd)}${cv !== null ? ' &nbsp;|&nbsp; CV: ' + cv.toFixed(2) : ' &nbsp;|&nbsp; CV: n/a (mean below Rs 2,000)'}</p>

<h2>Platform Breakdown</h2>
<table>
  <thead><tr><th>Platform</th><th>Total</th><th>Share</th></tr></thead>
  <tbody>${platRows}</tbody>
</table>

<h2>Monthly Income Chart</h2>
<div class="chart-wrap">${chart}</div>

<h2>Recent Events (last 10)</h2>
<table>
  <thead><tr><th>Date</th><th>Platform</th><th>Amount</th><th>Description</th></tr></thead>
  <tbody>${evRows}</tbody>
</table>
`;
}

function buildSVG(months, values) {
  const W = 700, H = 220, PAD = 44;
  const usableW = W - 2 * PAD;
  const usableH = H - 2 * PAD;
  const maxV = Math.max(...values) || 1;
  const n = months.length;
  const step = n > 1 ? usableW / (n - 1) : 0;

  const pts = values.map((v, i) => ({
    x: PAD + i * step,
    y: PAD + usableH - (v / maxV) * usableH
  }));

  const polyline = pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const circles = pts.map((p, i) =>
    `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="#2563eb">
       <title>${escHtml(months[i])}: Rs ${fmtNum(values[i])}</title>
     </circle>`
  ).join('\n');
  const labels = pts.map((p, i) =>
    `<text x="${p.x.toFixed(1)}" y="${H - 8}" font-size="10" text-anchor="middle" fill="#6b7280">${escHtml(months[i])}</text>`
  ).join('\n');
  const baseY = PAD + usableH;

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"
     xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Monthly income chart">
  <line x1="${PAD}" y1="${baseY}" x2="${W - PAD}" y2="${baseY}" stroke="#e5e7eb" stroke-width="1"/>
  <polyline points="${polyline}" fill="none" stroke="#2563eb" stroke-width="2"/>
  ${circles}
  ${labels}
</svg>`;
}

function resetAll() {
  fileQueue   = [];
  allEvents   = [];
  pendingConf = [];
  fileInput.value = '';
  fileList.innerHTML = '';
  confirmCards.innerHTML = '';
  confirmSec.style.display  = 'none';
  analyseBar.style.display  = 'none';
  resultsSection.innerHTML  = '';
  resultsView.style.display = 'none';
  uploadView.style.display  = '';
  btnReset.style.display    = 'none';
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function fmtNum(n) {
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

document.getElementById('btn-browse').addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
  addFiles(Array.from(e.target.files));
  fileInput.value = '';
});

dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', ()  => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  addFiles(Array.from(e.dataTransfer.files));
});
dropZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') fileInput.click();
});

btnAnalyse.addEventListener('click', () => showResults());

btnReset.addEventListener('click', resetAll);
</script>
</body>
</html>
"""


class UploadHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        print(f"[server] {format % args}", flush=True)

    def do_GET(self) -> None:
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self._send_html(SPA_HTML)

    def do_POST(self) -> None:
        if self.path != "/upload":
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_json({"error": "Invalid upload request."}, status=400)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        parsed = parse_multipart_form_file(body, content_type, "statement")
        if parsed is None or not parsed[0]:
            self._send_json({"error": "No file was selected."}, status=400)
            return

        filename, file_bytes = parsed
        if not file_bytes:
            self._send_json({"error": "Uploaded file is empty."}, status=400)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_path = tmp_path / "uploaded_statement.pdf"
            pdf_path.write_bytes(file_bytes)
            db_path = tmp_path / "ledger.db"

            try:
                report, summary, monthly_summaries, income_events = run_pipeline(
                    pdf_path, db_path, use_gemini=True
                )
            except ScannedPdfError:
                self._send_json(
                    {"error": (
                        "This PDF has no extractable text — it looks like a scanned "
                        "image rather than a text-based statement. Please upload a "
                        "text-based PDF."
                    )},
                    status=400,
                )
                return
            except Exception as exc:
                self._send_json({"error": f"Could not process this statement: {exc}"}, status=400)
                return

            events = render_results_fragment(report, summary, monthly_summaries, income_events)

        self._send_json(events)

    def _send_html(self, content: str, status: int = 200) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int = 8765, open_browser: bool = True) -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    port = int(os.environ.get("SERVER_PORT", port))
    open_browser_env = os.environ.get("SERVER_OPEN_BROWSER", "").strip().lower()
    if open_browser_env == "false":
        open_browser = False

    server = HTTPServer(("127.0.0.1", port), UploadHandler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Gig Income Ledger running at {url}")
    if os.environ.get("GEMINI_API_KEY"):
        print("Gemini API key loaded — live rephrasing enabled.")
    else:
        print("No GEMINI_API_KEY set — using template summary (no Gemini call).")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    run_server()
