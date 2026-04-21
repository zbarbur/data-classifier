"""General-purpose prompt analysis review tool.

Multi-layer detection reviewer for prompts:
  - Zone detection (code/structured/CLI blocks)
  - Secret/credential detection (regex + key-name heuristic)
  - Future layers plug in via the same interface

Features:
  - Browse and filter corpus prompts
  - Run all detectors on any prompt (from corpus or custom text)
  - Approve/reject annotations with clear visual feedback
  - Mark actual line ranges when correcting wrong annotations
  - Saves reviews back to corpus JSONL

Usage:
    python -m docs.experiments.prompt_analysis.tools.prompt_reviewer \
        --corpus docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl \
        --port 8234

Security note: Local-only development tool. All user-supplied text is escaped
via textContent (DOM safe) before display. No raw HTML insertion of untrusted content.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from docs.experiments.prompt_analysis.s4_zone_detection.zone_detector import detect_zones

log = logging.getLogger(__name__)

# Use the Sprint 14 scan_text API — single detection path
try:
    from data_classifier.scan_text import TextScanner
    _HAS_SECRET_DETECTION = True
except ImportError:
    _HAS_SECRET_DETECTION = False
    log.warning("Secret detection not available (data_classifier.scan_text not found)")

# Module-level scanner singleton (initialized on first use)
_SCANNER: TextScanner | None = None

# Global state
CORPUS: list[dict] = []
CORPUS_PATH: Path | None = None


def _load_corpus(path: Path):
    global CORPUS, CORPUS_PATH
    CORPUS_PATH = path
    with open(path) as f:
        CORPUS = [json.loads(l) for l in f if l.strip()]
    log.info("Loaded %d records from %s", len(CORPUS), path)


def _save_corpus():
    if CORPUS_PATH:
        with open(CORPUS_PATH, "w") as f:
            for r in CORPUS:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _get_scanner() -> TextScanner:
    """Get or create the module-level TextScanner singleton."""
    global _SCANNER
    if _SCANNER is None:
        _SCANNER = TextScanner()
        _SCANNER.startup()
    return _SCANNER


def _run_secret_detection(text: str) -> list[dict]:
    """Run scan_text on text, return findings with exact match spans.

    Uses the Sprint 14 scan_text API — single detection path for both
    regex patterns and secret_scanner key+entropy heuristic.
    """
    if not _HAS_SECRET_DETECTION:
        return []

    try:
        scanner = _get_scanner()
        result = scanner.scan(text, min_confidence=0.3)
    except Exception as e:
        log.error("scan_text error: %s", e)
        return []

    # Convert char offsets to line/col for the UI
    lines = text.split("\n")
    line_starts = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1

    def _char_to_line_col(char_offset: int) -> tuple[int, int]:
        line_no = 0
        for li, ls in enumerate(line_starts):
            if ls > char_offset:
                break
            line_no = li
        return line_no, char_offset - line_starts[line_no]

    findings = []
    for f in result.findings:
        line_no, col_start = _char_to_line_col(f.start)
        end_line, col_end = _char_to_line_col(f.end)

        findings.append({
            "layer": f.engine,
            "entity_type": f.entity_type,
            "pattern_name": f.detection_type,
            "display_name": f.display_name,
            "confidence": f.confidence,
            "matched_text": f.value_masked,
            "evidence": f.evidence,
            "line": line_no,
            "col_start": col_start,
            "col_end": col_end if end_line == line_no else len(lines[line_no]),
            "end_line": end_line,
        })

    return findings


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Prompt Analysis Reviewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; font-size: 13px; background: #1a1a2e; color: #e0e0e0; }
.container { display: flex; height: 100vh; }
.sidebar { width: 280px; border-right: 1px solid #333; overflow-y: auto; background: #16213e; flex-shrink: 0; }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.header { padding: 8px 16px; background: #0f3460; border-bottom: 1px solid #333; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.header h1 { font-size: 16px; color: #e94560; }
.main-body { flex: 1; display: flex; overflow: hidden; }
.content { flex: 1; overflow-y: auto; padding: 16px; }
.review-sidebar { width: 260px; border-left: 1px solid #333; background: #16213e; overflow-y: auto; flex-shrink: 0; padding: 12px; }

.sidebar-header { padding: 12px; background: #0f3460; border-bottom: 1px solid #333; position: sticky; top: 0; z-index: 1; }
.sidebar-header input { width: 100%; padding: 6px 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; }
.sidebar-stats { padding: 8px 12px; font-size: 11px; color: #888; border-bottom: 1px solid #222; }
.item { padding: 8px 12px; border-bottom: 1px solid #222; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.item:hover { background: #1a1a3e; }
.item.active { background: #0f3460; border-left: 3px solid #e94560; }
.item .id { font-size: 11px; color: #888; }
.item .badges { display: flex; gap: 4px; }
.badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: bold; }
.badge-code { background: #2d6a4f; color: #95d5b2; }
.badge-structured { background: #5c4b99; color: #c8b6ff; }
.badge-cli { background: #b56727; color: #ffd9a0; }
.badge-secret { background: #8b0000; color: #ff6b6b; }
.badge-none { background: #333; color: #888; }
.badge-approved { background: #1b4332; color: #52b788; }
.badge-rejected { background: #6b2c2c; color: #f28b82; }
.badge-correction { background: #5c2d82; color: #d4a5ff; }

.filters { display: flex; gap: 4px; flex-wrap: wrap; }
.filter-btn { padding: 3px 8px; border: 1px solid #444; background: #1a1a2e; color: #aaa; cursor: pointer; border-radius: 3px; font-size: 11px; }
.filter-btn.active { background: #0f3460; color: #fff; border-color: #e94560; }

/* Prompt display */
.prompt-text { white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; }
.line { display: flex; cursor: pointer; }
.line:hover { background: rgba(255,255,255,0.03); }
.line.selected { background: rgba(233, 69, 96, 0.15); }
.line-no { color: #555; min-width: 40px; text-align: right; padding-right: 12px; user-select: none; flex-shrink: 0; }
.line-content { flex: 1; }
.line-markers { flex-shrink: 0; padding-left: 8px; display: flex; gap: 2px; }

/* Zone highlighting */
.zone-code { background: rgba(45, 106, 79, 0.2); border-left: 3px solid #2d6a4f; padding-left: 8px; }
.zone-structured_data { background: rgba(92, 75, 153, 0.2); border-left: 3px solid #5c4b99; padding-left: 8px; }
.zone-cli_shell { background: rgba(181, 103, 39, 0.2); border-left: 3px solid #b56727; padding-left: 8px; }
.zone-natural_language { }

/* Rejected zone — strikethrough + red tint */
.zone-rejected { background: rgba(107, 44, 44, 0.15) !important; border-left: 3px solid #6b2c2c !important; text-decoration: line-through; text-decoration-color: rgba(255,100,100,0.4); }

/* User-marked correction zone */
.zone-correction { background: rgba(233, 69, 96, 0.12); border-left: 3px solid #e94560; padding-left: 8px; }

/* Block annotation markers */
.block-marker { font-size: 10px; padding: 2px 8px; margin: 4px 0; border-radius: 3px; display: inline-block; }
.block-start { background: #0f3460; color: #53a8b6; }
.block-end { background: #333; color: #888; }
.block-rejected-marker { background: #6b2c2c; color: #f28b82; text-decoration: line-through; }

/* Secret findings — inline highlights */
.secret-highlight { background: rgba(255, 80, 80, 0.25); border-bottom: 2px solid #ff6b6b; cursor: help; position: relative; }
.secret-highlight:hover { background: rgba(255, 80, 80, 0.4); }
.secret-tooltip { display: none; position: absolute; bottom: 100%; left: 0; background: #2a0a0a; border: 1px solid #ff6b6b; border-radius: 4px; padding: 4px 8px; font-size: 10px; color: #ff6b6b; white-space: nowrap; z-index: 10; pointer-events: none; }
.secret-highlight:hover .secret-tooltip { display: block; }

/* Secret findings — right panel list */
.secret-finding { padding: 4px 6px; margin: 2px 0; background: rgba(139,0,0,0.2); border-radius: 3px; font-size: 10px; cursor: pointer; }
.secret-finding:hover { background: rgba(139,0,0,0.35); }
.secret-finding .sf-type { color: #ff6b6b; font-weight: bold; }
.secret-finding .sf-meta { color: #888; display: block; margin-top: 1px; }
.secret-finding .sf-match { color: #aaa; display: block; margin-top: 1px; word-break: break-all; }

/* Review panel (right sidebar) */
.review-panel h3 { margin-bottom: 10px; color: #e94560; font-size: 13px; }
.review-section { margin-bottom: 14px; }
.review-section h4 { font-size: 11px; color: #888; margin-bottom: 4px; }
.review-actions { display: flex; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.btn { padding: 5px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: bold; }
.btn-approve { background: #2d6a4f; color: #fff; }
.btn-approve:hover { background: #40916c; }
.btn-reject { background: #6b2c2c; color: #fff; }
.btn-reject:hover { background: #993333; }
.btn-skip { background: #333; color: #ccc; }
.btn-skip:hover { background: #444; }
.btn-rerun { background: #0f3460; color: #53a8b6; }
.btn-rerun:hover { background: #1a4a80; }
.btn-mark { background: #5c2d82; color: #d4a5ff; }
.btn-mark:hover { background: #7b3fa8; }
.review-notes { width: 100%; padding: 6px 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; resize: vertical; min-height: 36px; font-size: 11px; }

/* Selection info */
.selection-info { padding: 4px 8px; background: #2d1b4e; border-radius: 3px; font-size: 11px; color: #d4a5ff; margin-bottom: 6px; display: none; }

.nav-btns { display: flex; gap: 8px; }
.nav-btn { padding: 4px 12px; background: #333; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 12px; }
.nav-btn:hover { background: #444; }

.custom-input { width: 100%; padding: 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; resize: vertical; min-height: 80px; font-family: inherit; }

/* Layer toggles */
.layer-toggles { display: flex; gap: 8px; align-items: center; }
.layer-toggle { display: flex; align-items: center; gap: 4px; font-size: 11px; cursor: pointer; }
.layer-toggle input { cursor: pointer; }
</style>
</head>
<body>
<div class="container">
  <div class="sidebar">
    <div class="sidebar-header">
      <input type="text" id="search" placeholder="Search prompts..." oninput="filterList()">
      <div class="filters" style="margin-top: 6px;">
        <button class="filter-btn active" data-filter="all" onclick="setFilter('all')">All</button>
        <button class="filter-btn" data-filter="code" onclick="setFilter('code')">Code</button>
        <button class="filter-btn" data-filter="structured_data" onclick="setFilter('structured_data')">Structured</button>
        <button class="filter-btn" data-filter="cli_shell" onclick="setFilter('cli_shell')">CLI</button>
        <button class="filter-btn" data-filter="secret" onclick="setFilter('secret')">Secrets</button>
        <button class="filter-btn" data-filter="none" onclick="setFilter('none')">No detect</button>
        <button class="filter-btn" data-filter="unreviewed" onclick="setFilter('unreviewed')">Unreviewed</button>
        <button class="filter-btn" data-filter="rejected" onclick="setFilter('rejected')">Rejected</button>
      </div>
    </div>
    <div class="sidebar-stats" id="stats"></div>
    <div id="list"></div>
  </div>
  <div class="main">
    <div class="header">
      <h1>Prompt Reviewer</h1>
      <div class="nav-btns">
        <button class="nav-btn" onclick="navigate(-1)">&#9664; Prev</button>
        <button class="nav-btn" onclick="navigate(1)">Next &#9654;</button>
        <button class="nav-btn" onclick="navigateUnreviewed()">Unreviewed &#9654;&#9654;</button>
      </div>
      <div class="layer-toggles">
        <label class="layer-toggle"><input type="checkbox" id="toggle-zones" checked onchange="rerenderCurrent()">Zones</label>
        <label class="layer-toggle"><input type="checkbox" id="toggle-secrets" checked onchange="rerenderCurrent()">Secrets</label>
      </div>
      <button class="btn btn-rerun" onclick="showCustomInput()">Custom text</button>
    </div>
    <div class="main-body">
      <div class="content" id="content">
        <p style="color: #888; padding: 20px;">Select a prompt from the sidebar, or paste custom text.</p>
      </div>
      <div class="review-sidebar" id="review-panel" style="display:none;">
        <h3>Review</h3>
        <div class="review-section">
          <h4>Verdict</h4>
          <div class="review-actions">
            <button class="btn btn-approve" onclick="reviewZones('approve')">Correct</button>
            <button class="btn btn-reject" onclick="reviewZones('reject')">Wrong</button>
            <button class="btn btn-skip" onclick="reviewZones('skip')">Skip</button>
          </div>
        </div>
        <div class="review-section">
          <h4>Mark lines</h4>
          <div class="selection-info" id="selection-info">Selected: <span id="sel-range"></span></div>
          <div id="mark-controls" style="display:none;">
            <select id="mark-type" style="width:100%;padding:4px;background:#1a1a2e;border:1px solid #444;color:#e0e0e0;border-radius:3px;margin-bottom:6px;font-size:11px;">
              <option value="code">Code</option>
              <option value="structured_data">Structured data</option>
              <option value="cli_shell">CLI / Shell</option>
              <option value="natural_language">Natural language</option>
            </select>
            <button class="btn btn-mark" id="btn-mark-block" onclick="markBlock()">Mark as block (m)</button>
          </div>
          <div style="font-size:10px;color:#666;margin-top:4px;">Click lines to select. Shift+click for range.</div>
        </div>
        <div class="review-section" id="user-blocks-list"></div>
        <div class="review-section" id="secrets-list"></div>
        <div class="review-section">
          <h4>Notes</h4>
          <textarea class="review-notes" id="review-notes" placeholder="Notes..."></textarea>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
var corpus = [];
var filteredIndices = [];
var currentIdx = -1;
var currentFilter = 'all';
var currentSecrets = [];  // secret findings for current prompt
var selectedLines = new Set();  // lines selected by user for correction
var userBlocks = [];  // user-marked correction blocks

function escapeHtml(s) {
  var div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

async function loadCorpus() {
  var resp = await fetch('/api/corpus');
  corpus = await resp.json();
  updateStats();
  filterList();
}

function updateStats() {
  var reviewed = corpus.filter(function(r) { return r.review && r.review.correct !== null; }).length;
  var rejected = corpus.filter(function(r) { return r.review && r.review.correct === false; }).length;
  var total = corpus.length;
  var withBlocks = corpus.filter(function(r) { return r.heuristic_has_blocks; }).length;
  document.getElementById('stats').textContent =
    total + ' prompts | ' + withBlocks + ' detected | ' + reviewed + ' reviewed | ' + rejected + ' rejected';
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  filterList();
}

function filterList() {
  var search = document.getElementById('search').value.toLowerCase();
  filteredIndices = [];
  corpus.forEach(function(r, i) {
    if (currentFilter === 'code' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'code'; })) return;
    if (currentFilter === 'structured_data' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'structured_data'; })) return;
    if (currentFilter === 'cli_shell' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'cli_shell'; })) return;
    if (currentFilter === 'secret' && !(r.secrets && r.secrets.length > 0)) return;
    if (currentFilter === 'none' && r.heuristic_has_blocks) return;
    if (currentFilter === 'unreviewed' && r.review && r.review.correct !== null) return;
    if (currentFilter === 'rejected' && (!r.review || r.review.correct !== false)) return;
    if (search && !(r.text || '').toLowerCase().includes(search) && !(r.prompt_id || '').includes(search)) return;
    filteredIndices.push(i);
  });
  renderList();
}

function renderList() {
  var listEl = document.getElementById('list');
  listEl.textContent = '';
  filteredIndices.forEach(function(idx) {
    var r = corpus[idx];
    var types = new Set((r.heuristic_blocks || []).map(function(b) { return b.zone_type; }));

    var item = document.createElement('div');
    item.className = 'item' + (idx === currentIdx ? ' active' : '');
    item.onclick = function() { selectPrompt(idx); };

    var idSpan = document.createElement('span');
    idSpan.className = 'id';
    idSpan.textContent = (r.prompt_id || '').slice(0, 10) + '.. (' + r.total_lines + 'L)';

    var badgesSpan = document.createElement('span');
    badgesSpan.className = 'badges';

    function addBadge(cls, text) {
      var b = document.createElement('span');
      b.className = 'badge ' + cls;
      b.textContent = text;
      badgesSpan.appendChild(b);
    }

    if (types.has('code')) addBadge('badge-code', 'code');
    if (types.has('structured_data')) addBadge('badge-structured', 'struct');
    if (types.has('cli_shell')) addBadge('badge-cli', 'cli');
    if (r.secrets && r.secrets.length > 0) addBadge('badge-secret', 'secret');
    if (!r.heuristic_has_blocks && !(r.secrets && r.secrets.length > 0)) addBadge('badge-none', '-');
    if (r.review && r.review.actual_blocks && r.review.actual_blocks.length > 0) addBadge('badge-correction', 'marked');
    if (r.review && r.review.correct === true) addBadge('badge-approved', 'ok');
    if (r.review && r.review.correct === false) addBadge('badge-rejected', 'X');

    item.appendChild(idSpan);
    item.appendChild(badgesSpan);
    listEl.appendChild(item);
  });
}

async function selectPrompt(idx) {
  currentIdx = idx;
  selectedLines = new Set();
  var r = corpus[idx];

  // Load any existing user-marked blocks from saved review
  userBlocks = (r.review && r.review.actual_blocks) ? r.review.actual_blocks.slice() : [];

  // Run secret detection if not cached
  if (!r._secrets_loaded) {
    var resp = await fetch('/api/detect_secrets', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ text: r.text })
    });
    var result = await resp.json();
    r.secrets = result.findings;
    r._secrets_loaded = true;
  }
  currentSecrets = r.secrets || [];

  renderPrompt(r);
  renderList();
}

function rerenderCurrent() {
  if (currentIdx >= 0) renderPrompt(corpus[currentIdx]);
}

function renderPrompt(r) {
  var lines = (r.text || '').split('\n');
  var blocks = r.heuristic_blocks || [];
  var showZones = document.getElementById('toggle-zones').checked;
  var showSecrets = document.getElementById('toggle-secrets').checked;
  var isRejected = r.review && r.review.correct === false;

  // Build line-to-zone map
  var lineZones = {};
  if (showZones) {
    blocks.forEach(function(b) {
      for (var l = b.start_line; l < b.end_line; l++) {
        lineZones[l] = b;
      }
    });
  }

  // Build line-to-user-block map
  var lineUserBlocks = {};
  userBlocks.forEach(function(ub) {
    for (var l = ub.start_line; l < ub.end_line; l++) {
      lineUserBlocks[l] = ub;
    }
  });

  // Build per-line secret match spans for inline highlighting
  // secretLineMatches[lineNo] = [{col_start, col_end, entity_type, pattern_name, confidence}]
  var secretLineMatches = {};
  if (showSecrets && currentSecrets.length > 0) {
    currentSecrets.forEach(function(s) {
      if (s.col_start >= 0) {
        // Exact span available
        if (!secretLineMatches[s.line]) secretLineMatches[s.line] = [];
        secretLineMatches[s.line].push({
          col_start: s.col_start,
          col_end: s.col_end,
          entity_type: s.entity_type,
          pattern_name: s.pattern_name || '',
          confidence: s.confidence,
        });
      } else if (s.matched_text) {
        // Scanner — no exact span, highlight the whole matched text if found
        lines.forEach(function(line, li) {
          var idx = line.indexOf(s.matched_text.slice(0, 30));
          if (idx >= 0) {
            if (!secretLineMatches[li]) secretLineMatches[li] = [];
            secretLineMatches[li].push({
              col_start: idx,
              col_end: Math.min(idx + s.matched_text.length, line.length),
              entity_type: s.entity_type,
              pattern_name: s.pattern_name || 'secret_scanner',
              confidence: s.confidence,
            });
          }
        });
      }
    });
  }

  var container = document.createElement('div');

  // Header
  var header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #333;';
  var headerLeft = document.createElement('div');
  var strong = document.createElement('strong');
  strong.textContent = r.prompt_id || '';
  var meta = document.createElement('span');
  meta.style.cssText = 'font-size:11px;color:#888;margin-left:8px;';
  meta.textContent = lines.length + ' lines | ' + blocks.length + ' zone blocks | ' + currentSecrets.length + ' secrets';
  headerLeft.appendChild(strong);
  headerLeft.appendChild(meta);

  // Review status badge in header
  if (r.review && r.review.correct === true) {
    var approvedBadge = document.createElement('span');
    approvedBadge.style.cssText = 'margin-left:12px;padding:2px 8px;background:#1b4332;color:#52b788;border-radius:3px;font-size:11px;font-weight:bold;';
    approvedBadge.textContent = 'APPROVED';
    headerLeft.appendChild(approvedBadge);
  } else if (isRejected) {
    var rejBadge = document.createElement('span');
    rejBadge.style.cssText = 'margin-left:12px;padding:2px 8px;background:#6b2c2c;color:#f28b82;border-radius:3px;font-size:11px;font-weight:bold;';
    rejBadge.textContent = 'REJECTED';
    headerLeft.appendChild(rejBadge);
    if (r.review.notes) {
      var noteSpan = document.createElement('span');
      noteSpan.style.cssText = 'margin-left:8px;font-size:11px;color:#f28b82;';
      noteSpan.textContent = '(' + r.review.notes + ')';
      headerLeft.appendChild(noteSpan);
    }
  }

  header.appendChild(headerLeft);
  container.appendChild(header);

  // Prompt text with zone + secret highlighting
  var textDiv = document.createElement('div');
  textDiv.className = 'prompt-text';

  var inBlock = null;
  lines.forEach(function(line, i) {
    var zone = lineZones[i] || null;
    var ub = lineUserBlocks[i] || null;

    // Block start marker
    if (zone && zone !== inBlock) {
      var marker = document.createElement('div');
      marker.className = 'block-marker ' + (isRejected ? 'block-rejected-marker' : 'block-start');
      marker.textContent = '\u25BC ' + zone.zone_type + ' (' + zone.method + ', conf=' + zone.confidence.toFixed(2) + (zone.language_hint ? ', ' + zone.language_hint : '') + ') L' + zone.start_line + '-' + zone.end_line;
      textDiv.appendChild(marker);
      inBlock = zone;
    }
    if (!zone && inBlock) {
      var endMarker = document.createElement('div');
      endMarker.className = 'block-marker block-end';
      endMarker.textContent = '\u25B2 end';
      textDiv.appendChild(endMarker);
      inBlock = null;
    }

    // User correction block markers
    if (ub && (i === 0 || !lineUserBlocks[i-1] || lineUserBlocks[i-1] !== ub)) {
      var corrMarker = document.createElement('div');
      corrMarker.className = 'block-marker';
      corrMarker.style.cssText = 'background:#5c2d82;color:#d4a5ff;';
      corrMarker.textContent = '\u25BC MARKED: ' + ub.zone_type + ' L' + ub.start_line + '-' + ub.end_line;
      textDiv.appendChild(corrMarker);
    }

    var lineDiv = document.createElement('div');
    var zoneClass = '';
    if (ub) {
      // User correction always takes priority
      zoneClass = 'zone-correction';
    } else if (zone && isRejected) {
      zoneClass = 'zone-rejected';
    } else if (zone) {
      zoneClass = 'zone-' + zone.zone_type;
    }
    // If there's BOTH a heuristic zone AND a correction, show a dual indicator
    if (ub && zone) {
      zoneClass = 'zone-correction';
    }
    lineDiv.className = 'line ' + zoneClass + (selectedLines.has(i) ? ' selected' : '');
    lineDiv.dataset.lineNo = i;
    lineDiv.onclick = function(e) { toggleLine(i, e.shiftKey); };

    var lineNo = document.createElement('span');
    lineNo.className = 'line-no';
    lineNo.textContent = i;

    var lineContent = document.createElement('span');
    lineContent.className = 'line-content';

    // Render line with inline secret highlights
    var lineSecrets = secretLineMatches[i];
    if (lineSecrets && lineSecrets.length > 0 && line) {
      // Sort spans by start position
      lineSecrets.sort(function(a,b) { return a.col_start - b.col_start; });
      var pos = 0;
      lineSecrets.forEach(function(sp) {
        // Text before match
        if (sp.col_start > pos) {
          lineContent.appendChild(document.createTextNode(line.slice(pos, sp.col_start)));
        }
        // Highlighted match
        var hlSpan = document.createElement('span');
        hlSpan.className = 'secret-highlight';
        hlSpan.textContent = line.slice(sp.col_start, sp.col_end);
        // Tooltip
        var tip = document.createElement('span');
        tip.className = 'secret-tooltip';
        tip.textContent = sp.entity_type + ' (' + sp.pattern_name + ') conf=' + sp.confidence.toFixed(2);
        hlSpan.appendChild(tip);
        lineContent.appendChild(hlSpan);
        pos = sp.col_end;
      });
      // Text after last match
      if (pos < line.length) {
        lineContent.appendChild(document.createTextNode(line.slice(pos)));
      }
    } else {
      lineContent.textContent = line || ' ';
    }

    var lineMarkers = document.createElement('span');
    lineMarkers.className = 'line-markers';

    lineDiv.appendChild(lineNo);
    lineDiv.appendChild(lineContent);
    lineDiv.appendChild(lineMarkers);
    textDiv.appendChild(lineDiv);
  });

  if (inBlock) {
    var finalEnd = document.createElement('div');
    finalEnd.className = 'block-marker block-end';
    finalEnd.textContent = '\u25B2 end';
    textDiv.appendChild(finalEnd);
  }

  container.appendChild(textDiv);

  var contentEl = document.getElementById('content');
  contentEl.textContent = '';
  contentEl.appendChild(container);

  document.getElementById('review-panel').style.display = 'block';
  document.getElementById('review-notes').value = (r.review && r.review.notes) || '';
  updateSelectionInfo();
  renderSecretsList();
}

// Line selection for marking actual code blocks
var lastSelectedLine = -1;

function toggleLine(lineNo, shiftKey) {
  if (shiftKey && lastSelectedLine >= 0) {
    // Range select
    var start = Math.min(lastSelectedLine, lineNo);
    var end = Math.max(lastSelectedLine, lineNo);
    for (var i = start; i <= end; i++) {
      selectedLines.add(i);
    }
  } else {
    if (selectedLines.has(lineNo)) {
      selectedLines.delete(lineNo);
    } else {
      selectedLines.add(lineNo);
    }
  }
  lastSelectedLine = lineNo;
  updateSelectionInfo();

  // Update visual
  document.querySelectorAll('.line').forEach(function(el) {
    var ln = parseInt(el.dataset.lineNo);
    el.classList.toggle('selected', selectedLines.has(ln));
  });
}

function updateSelectionInfo() {
  var info = document.getElementById('selection-info');
  var controls = document.getElementById('mark-controls');
  if (selectedLines.size > 0) {
    var sorted = Array.from(selectedLines).sort(function(a,b){return a-b;});
    info.style.display = 'block';
    document.getElementById('sel-range').textContent = 'L' + sorted[0] + '-' + sorted[sorted.length-1] + ' (' + sorted.length + ' lines)';
    controls.style.display = 'block';
  } else {
    info.style.display = 'none';
    controls.style.display = 'none';
  }
  renderUserBlocksList();
}

function markBlock() {
  if (selectedLines.size === 0) return;
  var sorted = Array.from(selectedLines).sort(function(a,b){return a-b;});
  var zoneType = document.getElementById('mark-type').value;
  var block = {
    start_line: sorted[0],
    end_line: sorted[sorted.length-1] + 1,
    zone_type: zoneType,
  };
  userBlocks.push(block);
  selectedLines = new Set();
  lastSelectedLine = -1;
  rerenderCurrent();
}

function renderSecretsList() {
  var el = document.getElementById('secrets-list');
  el.textContent = '';
  if (!currentSecrets || currentSecrets.length === 0) return;
  var h4 = document.createElement('h4');
  h4.textContent = 'Secrets (' + currentSecrets.length + ')';
  h4.style.cssText = 'font-size:11px;color:#ff6b6b;margin-bottom:4px;';
  el.appendChild(h4);
  currentSecrets.forEach(function(s) {
    var item = document.createElement('div');
    item.className = 'secret-finding';
    // Click to scroll to line
    item.onclick = function() {
      var lineEl = document.querySelector('.line[data-line-no="' + s.line + '"]');
      if (lineEl) lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };
    var typeSpan = document.createElement('span');
    typeSpan.className = 'sf-type';
    typeSpan.textContent = s.entity_type + ' (L' + s.line + ')';
    item.appendChild(typeSpan);
    var matchSpan = document.createElement('span');
    matchSpan.className = 'sf-match';
    matchSpan.textContent = (s.matched_text || '').slice(0, 50);
    item.appendChild(matchSpan);
    var metaSpan = document.createElement('span');
    metaSpan.className = 'sf-meta';
    metaSpan.textContent = s.layer + ' / ' + (s.pattern_name || '') + ' conf=' + (s.confidence || 0).toFixed(2);
    item.appendChild(metaSpan);
    el.appendChild(item);
  });
}

function removeUserBlock(idx) {
  userBlocks.splice(idx, 1);
  rerenderCurrent();
}

function renderUserBlocksList() {
  var el = document.getElementById('user-blocks-list');
  el.textContent = '';
  if (userBlocks.length === 0) return;
  var h4 = document.createElement('h4');
  h4.textContent = 'Marked blocks (' + userBlocks.length + ')';
  h4.style.cssText = 'font-size:11px;color:#888;margin-bottom:4px;';
  el.appendChild(h4);
  userBlocks.forEach(function(ub, i) {
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:3px 6px;margin:2px 0;background:rgba(92,45,130,0.2);border-radius:3px;font-size:11px;';
    var label = document.createElement('span');
    label.style.color = '#d4a5ff';
    label.textContent = ub.zone_type + ' L' + ub.start_line + '-' + ub.end_line;
    var delBtn = document.createElement('button');
    delBtn.textContent = 'x';
    delBtn.style.cssText = 'background:none;border:none;color:#f28b82;cursor:pointer;font-size:11px;padding:0 4px;';
    delBtn.onclick = function() { removeUserBlock(i); };
    row.appendChild(label);
    row.appendChild(delBtn);
    el.appendChild(row);
  });
}

function navigate(dir) {
  var fiIdx = filteredIndices.indexOf(currentIdx);
  var newFi = fiIdx + dir;
  if (newFi >= 0 && newFi < filteredIndices.length) {
    selectPrompt(filteredIndices[newFi]);
  }
}

function navigateUnreviewed() {
  var fiIdx = filteredIndices.indexOf(currentIdx);
  for (var i = fiIdx + 1; i < filteredIndices.length; i++) {
    var r = corpus[filteredIndices[i]];
    if (!r.review || r.review.correct === null) {
      selectPrompt(filteredIndices[i]);
      return;
    }
  }
  alert('No more unreviewed prompts in current filter.');
}

async function reviewZones(action) {
  if (currentIdx < 0) return;
  var notes = document.getElementById('review-notes').value;
  var correct = action === 'approve' ? true : action === 'reject' ? false : null;

  // Auto-mark any selected lines as a block before saving
  if (selectedLines.size > 0) {
    markBlock();
  }

  var resp = await fetch('/api/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      index: currentIdx,
      correct: correct,
      notes: notes,
      actual_blocks: userBlocks.length > 0 ? userBlocks : null,
    })
  });
  if (resp.ok) {
    corpus[currentIdx].review = { correct: correct, notes: notes, actual_blocks: userBlocks.length > 0 ? userBlocks : null };
    updateStats();
    navigate(1);
  }
}

function showCustomInput() {
  var contentEl = document.getElementById('content');
  contentEl.textContent = '';
  var wrapper = document.createElement('div');
  wrapper.style.padding = '16px';
  var h3 = document.createElement('h3');
  h3.textContent = 'Run detectors on custom text';
  h3.style.marginBottom = '8px';
  wrapper.appendChild(h3);
  var textarea = document.createElement('textarea');
  textarea.className = 'custom-input';
  textarea.id = 'custom-text';
  textarea.rows = 15;
  textarea.placeholder = 'Paste a prompt here...';
  wrapper.appendChild(textarea);
  wrapper.appendChild(document.createElement('br'));
  wrapper.appendChild(document.createElement('br'));
  var btn = document.createElement('button');
  btn.className = 'btn btn-rerun';
  btn.textContent = 'Run all detectors';
  btn.onclick = runCustom;
  wrapper.appendChild(btn);
  contentEl.appendChild(wrapper);
  document.getElementById('review-panel').style.display = 'none';
}

async function runCustom() {
  var text = document.getElementById('custom-text').value;
  var resp = await fetch('/api/detect_all', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ text: text })
  });
  var result = await resp.json();
  currentSecrets = result.secrets || [];
  renderPrompt({
    prompt_id: 'custom',
    text: text,
    total_lines: text.split('\n').length,
    heuristic_has_blocks: result.zones.length > 0,
    heuristic_blocks: result.zones,
    secrets: result.secrets,
    review: { correct: null, notes: '', actual_blocks: null },
  });
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowRight' || e.key === 'n') navigate(1);
  if (e.key === 'ArrowLeft' || e.key === 'p') navigate(-1);
  if (e.key === 'a') reviewZones('approve');
  if (e.key === 'r') reviewZones('reject');
  if (e.key === 's') reviewZones('skip');
  if (e.key === 'u') navigateUnreviewed();
  if (e.key === 'm') markBlock();
  if (e.key === 'Escape') { selectedLines = new Set(); updateSelectionInfo(); rerenderCurrent(); }
});

loadCorpus();
</script>
</body>
</html>"""


class ReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif parsed.path == "/api/corpus":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(CORPUS, ensure_ascii=False).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        if self.path == "/api/review":
            idx = body.get("index", -1)
            if 0 <= idx < len(CORPUS):
                CORPUS[idx]["review"] = {
                    "correct": body.get("correct"),
                    "actual_blocks": body.get("actual_blocks"),
                    "notes": body.get("notes", ""),
                }
                _save_corpus()
                self._json_response({"ok": True})
            else:
                self.send_error(400, "Invalid index")

        elif self.path == "/api/detect_secrets":
            text = body.get("text", "")
            findings = _run_secret_detection(text)
            self._json_response({"findings": findings})

        elif self.path == "/api/detect_all":
            text = body.get("text", "")
            zones = detect_zones(text, prompt_id="custom")
            secrets = _run_secret_detection(text)
            self._json_response({
                "zones": [
                    {
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                        "zone_type": b.zone_type,
                        "confidence": b.confidence,
                        "method": b.method,
                        "language_hint": b.language_hint,
                    }
                    for b in zones.blocks
                ],
                "secrets": secrets,
            })
        else:
            self.send_error(404)

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Prompt Analysis Review Server")
    parser.add_argument("--corpus", type=str,
                        default="docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl")
    parser.add_argument("--port", type=int, default=8234)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    _load_corpus(Path(args.corpus))

    server = HTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"\n  Prompt Analysis Reviewer running at http://localhost:{args.port}")
    print(f"  Corpus: {args.corpus} ({len(CORPUS)} records)")
    print(f"  Secret detection: {'available' if _HAS_SECRET_DETECTION else 'NOT available'}")
    print(f"\n  Keys: a=approve r=reject s=skip n/right=next p/left=prev u=unreviewed")
    print(f"        click/shift+click lines to select, m=mark as block, Esc=clear selection\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
