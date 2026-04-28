"""General-purpose prompt analysis review tool.

Multi-layer detection reviewer for prompts:
  - Zone detection (code/structured/CLI blocks)
  - Secret/credential detection (regex + key-name heuristic)
  - Unified Rust detector (zones + secrets in one call)

Features:
  - Browse and filter corpus prompts (paginated for large corpora)
  - Run all detectors on any prompt (from corpus or custom text)
  - Approve/reject annotations with clear visual feedback
  - Mark actual line ranges when correcting wrong annotations
  - Saves reviews back to corpus JSONL

Supports two corpus formats:
  - Legacy (s4): text field present, heuristic_blocks for zones
  - Unified (wildchat scan): prompt_xor encoded text, zones/secrets pre-computed

Usage:
    # Unified scan output (recommended):
    .venv/bin/python docs/experiments/prompt_analysis/tools/prompt_reviewer.py \
        --corpus data/wildchat_unified/candidates.jsonl --port 8234

    # Legacy s4 corpus:
    .venv/bin/python docs/experiments/prompt_analysis/tools/prompt_reviewer.py \
        --corpus docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl

Security note: Local-only development tool. All user-supplied text is escaped
via textContent (DOM safe) before display. No raw HTML insertion of untrusted content.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

log = logging.getLogger(__name__)

# Rust unified detector (preferred)
_UNIFIED_DETECTOR = None
try:
    from data_classifier_core import UnifiedDetector as _UnifiedDetectorClass

    _HAS_UNIFIED = True
except ImportError:
    _HAS_UNIFIED = False
    log.warning("Rust UnifiedDetector not available")

# XOR decoder for unified format
try:
    from data_classifier.patterns._decoder import decode_encoded_strings
except ImportError:
    decode_encoded_strings = None

# Global state
CORPUS: list[dict] = []
CORPUS_PATH: Path | None = None
PAGE_SIZE = 200  # sidebar pagination


def _get_unified_detector():
    """Get or create the Rust unified detector singleton."""
    global _UNIFIED_DETECTOR
    if _UNIFIED_DETECTOR is None and _HAS_UNIFIED:
        patterns_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "data_classifier_core"
            / "patterns"
            / "unified_patterns.json"
        )
        if patterns_path.exists():
            _UNIFIED_DETECTOR = _UnifiedDetectorClass(patterns_path.read_text())
            log.info("Loaded Rust UnifiedDetector from %s", patterns_path)
        else:
            log.warning("unified_patterns.json not found at %s", patterns_path)
    return _UNIFIED_DETECTOR


def _decode_xor(prompt_xor: str) -> str:
    """Decode XOR-encoded text from unified format."""
    if decode_encoded_strings:
        return decode_encoded_strings(["xor:" + prompt_xor])[0]
    # Fallback: manual decode
    import base64

    raw = base64.b64decode(prompt_xor)
    return bytes(b ^ 0x5A for b in raw).decode("utf-8")


def _load_corpus(path: Path):
    """Load corpus from JSONL. Handles both legacy and unified formats."""
    global CORPUS, CORPUS_PATH
    CORPUS_PATH = path
    raw_records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                raw_records.append(json.loads(line))

    # Detect format: unified has prompt_xor, legacy has text
    is_unified = len(raw_records) > 0 and "prompt_xor" in raw_records[0]

    if is_unified:
        log.info("Detected unified format (%d records), decoding XOR text...", len(raw_records))
        for r in raw_records:
            # Decode text from XOR
            r["text"] = _decode_xor(r["prompt_xor"])
            # Map unified zones to heuristic_blocks for UI compatibility
            if "zones" in r and "heuristic_blocks" not in r:
                r["heuristic_blocks"] = r["zones"]
                r["heuristic_has_blocks"] = len(r["zones"]) > 0
            # Map unified secrets for UI
            if "secrets" in r and not r.get("_secrets_v2"):
                # Convert scan output format to reviewer UI format
                r["secrets"] = _convert_scan_secrets(r["text"], r.get("secrets", []))
                r["_secrets_v2"] = True
    else:
        log.info("Detected legacy format (%d records)", len(raw_records))

    CORPUS = raw_records
    log.info("Loaded %d records from %s", len(CORPUS), path)


def _convert_scan_secrets(text: str, scan_secrets: list[dict]) -> list[dict]:
    """Convert scan_wildchat_unified secret format to reviewer UI format.

    The Rust detector returns byte offsets (UTF-8), but the JS UI works with
    character positions. This function converts byte offsets → line + char col.
    """
    lines = text.split("\n")

    # Build byte-offset → (line_no, char_col) mapping via cumulative byte lengths
    line_byte_starts = []
    byte_offset = 0
    for line in lines:
        line_byte_starts.append(byte_offset)
        byte_offset += len(line.encode("utf-8")) + 1  # +1 for \n

    def _byte_to_line_col(byte_off: int) -> tuple[int, int]:
        line_no = 0
        for li, bs in enumerate(line_byte_starts):
            if bs > byte_off:
                break
            line_no = li
        # Convert byte offset within line to character offset
        line_byte_start = line_byte_starts[line_no]
        bytes_into_line = byte_off - line_byte_start
        # Decode only the bytes up to our offset to get char count
        line_bytes = lines[line_no].encode("utf-8")
        char_col = len(line_bytes[:bytes_into_line].decode("utf-8", errors="replace"))
        return line_no, char_col

    findings = []
    for s in scan_secrets:
        start = s.get("start", 0)
        end = s.get("end", 0)
        line_no, col_start = _byte_to_line_col(start)
        end_line, col_end = _byte_to_line_col(end)

        findings.append(
            {
                "layer": s.get("engine", "unknown"),
                "entity_type": s.get("entity_type", "UNKNOWN"),
                "pattern_name": s.get("detection_type", ""),
                "display_name": s.get("display_name", ""),
                "confidence": s.get("confidence", 0),
                "matched_text": s.get("value_masked", ""),
                "evidence": s.get("evidence", ""),
                "line": line_no,
                "col_start": col_start,
                "col_end": col_end if end_line == line_no else len(lines[line_no]) if line_no < len(lines) else 0,
                "end_line": end_line,
            }
        )
    return findings


def _save_corpus():
    if CORPUS_PATH:
        with open(CORPUS_PATH, "w") as f:
            for r in CORPUS:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _run_unified_detection(text: str) -> dict:
    """Run the Rust unified detector. Returns {zones, secrets}."""
    detector = _get_unified_detector()
    if not detector:
        return {"zones": [], "secrets": []}

    result = json.loads(detector.detect(text))

    zones_data = result.get("zones", {})
    blocks = zones_data.get("blocks", []) if isinstance(zones_data, dict) else []
    findings = result.get("findings", [])

    secrets = _convert_rust_findings(text, findings)
    return {"zones": blocks, "secrets": secrets}


def _convert_rust_findings(text: str, findings: list[dict]) -> list[dict]:
    """Convert Rust unified detector findings to reviewer UI format.

    Rust returns byte offsets; convert to line + char col for the UI.
    """
    lines = text.split("\n")
    line_byte_starts = []
    byte_offset = 0
    for line in lines:
        line_byte_starts.append(byte_offset)
        byte_offset += len(line.encode("utf-8")) + 1

    def _byte_to_line_col(byte_off: int) -> tuple[int, int]:
        line_no = 0
        for li, bs in enumerate(line_byte_starts):
            if bs > byte_off:
                break
            line_no = li
        line_byte_start = line_byte_starts[line_no]
        bytes_into_line = byte_off - line_byte_start
        line_bytes = lines[line_no].encode("utf-8")
        char_col = len(line_bytes[:bytes_into_line].decode("utf-8", errors="replace"))
        return line_no, char_col

    out = []
    for f in findings:
        match_data = f.get("match", {})
        start = match_data.get("start", 0)
        end = match_data.get("end", 0)
        line_no, col_start = _byte_to_line_col(start)
        end_line, col_end = _byte_to_line_col(end)

        out.append(
            {
                "layer": f.get("engine", "unknown"),
                "entity_type": f.get("entity_type", "UNKNOWN"),
                "pattern_name": f.get("detection_type", ""),
                "display_name": f.get("display_name", ""),
                "confidence": f.get("confidence", 0),
                "matched_text": match_data.get("value_masked", ""),
                "evidence": f.get("evidence", ""),
                "line": line_no,
                "col_start": col_start,
                "col_end": col_end if end_line == line_no else len(lines[line_no]) if line_no < len(lines) else 0,
                "end_line": end_line,
            }
        )
    return out


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Prompt Analysis Reviewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; font-size: 13px; background: #1a1a2e; color: #e0e0e0; }
.container { display: flex; height: 100vh; }
.sidebar { width: 400px; border-right: 1px solid #333; overflow-y: auto; background: #16213e; flex-shrink: 0; }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.header { padding: 8px 16px; background: #0f3460; border-bottom: 1px solid #333; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.header h1 { font-size: 16px; color: #e94560; }
.main-body { flex: 1; display: flex; overflow: hidden; }
.content { flex: 1; overflow-y: auto; padding: 16px; }
.review-sidebar { width: 260px; border-left: 1px solid #333; background: #16213e; overflow-y: auto; flex-shrink: 0; padding: 12px; }

.sidebar-header { padding: 12px; background: #0f3460; border-bottom: 1px solid #333; position: sticky; top: 0; z-index: 1; }
.sidebar-header input { width: 100%; padding: 6px 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; }
.sidebar-stats { padding: 8px 12px; font-size: 11px; color: #888; border-bottom: 1px solid #222; }
.item { padding: 6px 10px; border-bottom: 1px solid #222; cursor: pointer; }
.item:hover { background: #1a1a3e; }
.item.active { background: #0f3460; border-left: 3px solid #e94560; }
.item-row1 { display: flex; justify-content: space-between; align-items: center; }
.item .id { font-size: 11px; color: #888; }
.item .badges { display: flex; gap: 3px; flex-wrap: wrap; }
.item-row2 { margin-top: 2px; height: 3px; background: #222; border-radius: 2px; overflow: hidden; }
.item-conf-bar { height: 100%; border-radius: 2px; }
.conf-high { background: #2d6a4f; }
.conf-mid { background: #b56727; }
.conf-low { background: #6b2c2c; }
.badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: bold; }
.badge-code { background: #2d6a4f; color: #95d5b2; }
.badge-markup { background: #0078a0; color: #7dd3e8; }
.badge-config { background: #5c4b99; color: #c8b6ff; }
.badge-query { background: #a0641e; color: #ffd9a0; }
.badge-structured { background: #5c4b99; color: #c8b6ff; }
.badge-cli { background: #b56727; color: #ffd9a0; }
.badge-data { background: #783c8c; color: #d4a5ff; }
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
.zone-markup { background: rgba(0, 120, 160, 0.2); border-left: 3px solid #0078a0; padding-left: 8px; }
.zone-config { background: rgba(92, 75, 153, 0.2); border-left: 3px solid #5c4b99; padding-left: 8px; }
.zone-query { background: rgba(160, 100, 30, 0.2); border-left: 3px solid #a0641e; padding-left: 8px; }
.zone-cli_shell { background: rgba(181, 103, 39, 0.2); border-left: 3px solid #b56727; padding-left: 8px; }
.zone-data { background: rgba(120, 60, 140, 0.2); border-left: 3px solid #783c8c; padding-left: 8px; }
.zone-structured_data { background: rgba(92, 75, 153, 0.2); border-left: 3px solid #5c4b99; padding-left: 8px; }
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
@keyframes flash-line { 0% { background: rgba(255, 80, 80, 0.5); } 100% { background: transparent; } }
.line-flash { animation: flash-line 1.5s ease-out; }
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
        <button class="filter-btn" data-filter="markup" onclick="setFilter('markup')">Markup</button>
        <button class="filter-btn" data-filter="config" onclick="setFilter('config')">Config</button>
        <button class="filter-btn" data-filter="secret" onclick="setFilter('secret')">Secrets</button>
        <button class="filter-btn" data-filter="none" onclick="setFilter('none')">No detect</button>
        <button class="filter-btn" data-filter="unreviewed" onclick="setFilter('unreviewed')">Unreviewed</button>
        <button class="filter-btn" data-filter="rejected" onclick="setFilter('rejected')">Rejected</button>
        <button class="filter-btn" data-filter="low_conf" onclick="setFilter('low_conf')">Low conf</button>
      </div>
      <div style="margin-top: 6px; display: flex; gap: 6px; align-items: center;">
        <label style="font-size: 10px; color: #888;">Sort:</label>
        <select id="sort-select" onchange="filterList()" style="flex:1;padding:3px;background:#1a1a2e;border:1px solid #444;color:#e0e0e0;border-radius:3px;font-size:10px;">
          <option value="default">Default (ID)</option>
          <option value="conf_asc">Confidence low-high</option>
          <option value="conf_desc">Confidence high-low</option>
          <option value="lines_desc">Lines (longest first)</option>
          <option value="blocks_desc">Most blocks first</option>
        </select>
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
              <option value="markup">Markup (HTML/XML)</option>
              <option value="config">Config (YAML/JSON/env)</option>
              <option value="query">Query (SQL/GraphQL)</option>
              <option value="cli_shell">CLI / Shell / Logs</option>
              <option value="data">Data (CSV/tabular)</option>
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
var corpusMeta = [];    // metadata only (from paginated API)
var corpusCache = {};   // idx -> full record (fetched on demand)
var filteredIndices = [];
var currentIdx = -1;
var currentFilter = 'all';
var activeFilters = new Set();
var currentSecrets = [];
var selectedLines = new Set();
var userBlocks = [];
var totalRecords = 0;

function escapeHtml(s) {
  var div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

async function loadCorpus() {
  // Load all metadata pages
  corpusMeta = [];
  var page = 0;
  var pageSize = 500;
  while (true) {
    var resp = await fetch('/api/corpus_meta?page=' + page + '&size=' + pageSize);
    var data = await resp.json();
    totalRecords = data.total;
    corpusMeta = corpusMeta.concat(data.items);
    if (corpusMeta.length >= data.total) break;
    page++;
  }
  updateStats();
  filterList();
}

async function updateStats() {
  var resp = await fetch('/api/stats');
  var s = await resp.json();
  var el = document.getElementById('stats');
  el.textContent = s.total + ' prompts | ' + s.with_zones + ' zones | ' + s.with_secrets + ' secrets | ' +
    s.reviewed + ' reviewed | ' + s.secret_tp + ' TP / ' + s.secret_fp + ' FP';
}

function setFilter(f) {
  // "All" clears everything. Other filters toggle on/off and combine.
  if (f === 'all') {
    activeFilters.clear();
    currentFilter = 'all';
  } else {
    if (activeFilters.has(f)) {
      activeFilters.delete(f);
    } else {
      activeFilters.add(f);
    }
    currentFilter = activeFilters.size > 0 ? 'combined' : 'all';
  }
  document.querySelectorAll('.filter-btn').forEach(function(b) {
    if (b.dataset.filter === 'all') {
      b.classList.toggle('active', activeFilters.size === 0);
    } else {
      b.classList.toggle('active', activeFilters.has(b.dataset.filter));
    }
  });
  filterList();
}

function filterList() {
  var search = document.getElementById('search').value.toLowerCase();
  filteredIndices = [];
  corpusMeta.forEach(function(m) {
    if (activeFilters.size > 0) {
      var pass = true;
      if (activeFilters.has('code') && m.zone_types.indexOf('code') < 0) pass = false;
      if (activeFilters.has('markup') && m.zone_types.indexOf('markup') < 0) pass = false;
      if (activeFilters.has('config') && m.zone_types.indexOf('config') < 0 && m.zone_types.indexOf('structured_data') < 0) pass = false;
      if (activeFilters.has('secret') && m.num_secrets === 0) pass = false;
      if (activeFilters.has('none') && (m.num_zones > 0 || m.num_secrets > 0)) pass = false;
      if (activeFilters.has('unreviewed') && m.has_review) pass = false;
      if (activeFilters.has('rejected') && m.review_correct !== false) pass = false;
      if (activeFilters.has('low_conf') && (m.max_confidence === 0 || m.max_confidence > 0.75)) pass = false;
      if (!pass) return;
    }
    if (search && m.prompt_id.indexOf(search) < 0) return;
    filteredIndices.push(m.idx);
  });
  // Sort using metadata
  var sortMode = document.getElementById('sort-select').value;
  if (activeFilters.has('low_conf') && sortMode === 'default') sortMode = 'conf_asc';

  function getMeta(idx) { return corpusMeta.find(function(m) { return m.idx === idx; }) || {}; }

  if (sortMode === 'conf_asc') {
    filteredIndices.sort(function(a, b) { return getMeta(a).max_confidence - getMeta(b).max_confidence; });
  } else if (sortMode === 'conf_desc') {
    filteredIndices.sort(function(a, b) { return getMeta(b).max_confidence - getMeta(a).max_confidence; });
  } else if (sortMode === 'lines_desc') {
    filteredIndices.sort(function(a, b) { return (getMeta(b).total_lines || 0) - (getMeta(a).total_lines || 0); });
  } else if (sortMode === 'blocks_desc') {
    filteredIndices.sort(function(a, b) { return (getMeta(b).num_zones || 0) - (getMeta(a).num_zones || 0); });
  }
  renderList();
}

function renderList() {
  var listEl = document.getElementById('list');
  listEl.textContent = '';

  // Virtual scroll: only render visible items (cap at 2000 for DOM perf)
  var renderLimit = Math.min(filteredIndices.length, 2000);
  if (filteredIndices.length > renderLimit) {
    var notice = document.createElement('div');
    notice.style.cssText = 'padding:6px 10px;font-size:10px;color:#888;border-bottom:1px solid #222;';
    notice.textContent = 'Showing ' + renderLimit + ' of ' + filteredIndices.length + ' — use filters to narrow';
    listEl.appendChild(notice);
  }

  for (var fi = 0; fi < renderLimit; fi++) {
    var idx = filteredIndices[fi];
    var m = corpusMeta.find(function(mm) { return mm.idx === idx; });
    if (!m) continue;

    var item = document.createElement('div');
    item.className = 'item' + (idx === currentIdx ? ' active' : '');
    item.onclick = (function(i) { return function() { selectPrompt(i); }; })(idx);

    var row1 = document.createElement('div');
    row1.className = 'item-row1';

    var idSpan = document.createElement('span');
    idSpan.className = 'id';
    idSpan.textContent = m.prompt_id + ' (' + m.total_lines + 'L)';

    var badgesSpan = document.createElement('span');
    badgesSpan.className = 'badges';

    function addBadge(parent, cls, text) {
      var b = document.createElement('span');
      b.className = 'badge ' + cls;
      b.textContent = text;
      parent.appendChild(b);
    }

    if (m.zone_types.indexOf('code') >= 0) addBadge(badgesSpan, 'badge-code', 'code');
    if (m.zone_types.indexOf('markup') >= 0) addBadge(badgesSpan, 'badge-markup', 'markup');
    if (m.zone_types.indexOf('config') >= 0 || m.zone_types.indexOf('structured_data') >= 0) addBadge(badgesSpan, 'badge-config', 'config');
    if (m.zone_types.indexOf('cli_shell') >= 0) addBadge(badgesSpan, 'badge-cli', 'cli');
    if (m.zone_types.indexOf('error_output') >= 0) addBadge(badgesSpan, 'badge-data', 'error');
    if (m.max_confidence > 0) {
      var confBadge = document.createElement('span');
      confBadge.className = 'badge';
      confBadge.style.cssText = 'background:transparent;color:' + (m.max_confidence >= 0.8 ? '#52b788' : m.max_confidence >= 0.65 ? '#ffd9a0' : '#f28b82') + ';font-size:10px;';
      confBadge.textContent = Math.round(m.max_confidence * 100) + '%';
      badgesSpan.appendChild(confBadge);
    }
    if (m.num_secrets > 0) addBadge(badgesSpan, 'badge-secret', m.num_secrets + 's');
    if (m.review_correct === true) addBadge(badgesSpan, 'badge-approved', 'ok');
    if (m.review_correct === false) addBadge(badgesSpan, 'badge-rejected', 'X');

    row1.appendChild(idSpan);
    row1.appendChild(badgesSpan);
    item.appendChild(row1);

    if (m.max_confidence > 0) {
      var row2 = document.createElement('div');
      row2.className = 'item-row2';
      var bar = document.createElement('div');
      bar.className = 'item-conf-bar ' + (m.max_confidence >= 0.8 ? 'conf-high' : m.max_confidence >= 0.65 ? 'conf-mid' : 'conf-low');
      bar.style.width = Math.round(m.max_confidence * 100) + '%';
      row2.appendChild(bar);
      item.appendChild(row2);
    }

    listEl.appendChild(item);
  }
}

async function selectPrompt(idx) {
  currentIdx = idx;
  selectedLines = new Set();

  // Fetch full record on demand
  var r = corpusCache[idx];
  if (!r) {
    var resp = await fetch('/api/prompt/' + idx);
    r = await resp.json();
    corpusCache[idx] = r;
  }

  // Load any existing user-marked blocks from saved review
  userBlocks = (r.review && r.review.actual_blocks) ? r.review.actual_blocks.slice() : [];
  currentSecrets = r.secrets || [];

  renderPrompt(r);
  renderList();
}

function rerenderCurrent() {
  if (currentIdx >= 0 && corpusCache[currentIdx]) renderPrompt(corpusCache[currentIdx]);
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

var secretReviews = {};  // index -> 'tp' | 'fp'

function renderSecretsList() {
  var el = document.getElementById('secrets-list');
  el.textContent = '';
  if (!currentSecrets || currentSecrets.length === 0) return;

  // Load saved secret reviews
  var r = corpusCache[currentIdx];
  if (r && r.review && r.review.secret_reviews) {
    secretReviews = r.review.secret_reviews;
  } else {
    secretReviews = {};
  }

  var fpCount = Object.values(secretReviews).filter(function(v) { return v === 'fp'; }).length;
  var h4 = document.createElement('h4');
  h4.textContent = 'Secrets (' + currentSecrets.length + ')' + (fpCount ? ' - ' + fpCount + ' FP' : '');
  h4.style.cssText = 'font-size:11px;color:#ff6b6b;margin-bottom:4px;';
  el.appendChild(h4);

  currentSecrets.forEach(function(s, si) {
    var isFP = secretReviews[si] === 'fp';
    var isTP = secretReviews[si] === 'tp';
    var item = document.createElement('div');
    item.className = 'secret-finding';
    if (isFP) item.style.opacity = '0.4';
    if (isFP) item.style.textDecoration = 'line-through';

    // Top row: type + FP/TP buttons
    var topRow = document.createElement('div');
    topRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

    var typeSpan = document.createElement('span');
    typeSpan.className = 'sf-type';
    typeSpan.textContent = s.entity_type + ' (L' + s.line + ')';
    typeSpan.style.cursor = 'pointer';
    typeSpan.onclick = function(e) {
      e.stopPropagation();
      var lineEl = document.querySelector('.line[data-line-no="' + s.line + '"]');
      if (lineEl) {
        lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        lineEl.classList.remove('line-flash');
        void lineEl.offsetWidth;  // force reflow to restart animation
        lineEl.classList.add('line-flash');
      }
    };

    var btnRow = document.createElement('span');
    btnRow.style.cssText = 'display:flex;gap:3px;';

    var tpBtn = document.createElement('button');
    tpBtn.textContent = 'TP';
    tpBtn.title = 'True Positive — real secret';
    tpBtn.style.cssText = 'padding:1px 5px;border:1px solid ' + (isTP ? '#52b788' : '#444') + ';background:' + (isTP ? '#1b4332' : 'transparent') + ';color:' + (isTP ? '#52b788' : '#888') + ';border-radius:2px;cursor:pointer;font-size:9px;';
    tpBtn.onclick = function(e) { e.stopPropagation(); flagSecret(si, 'tp'); };

    var fpBtn = document.createElement('button');
    fpBtn.textContent = 'FP';
    fpBtn.title = 'False Positive — not a secret';
    fpBtn.style.cssText = 'padding:1px 5px;border:1px solid ' + (isFP ? '#f28b82' : '#444') + ';background:' + (isFP ? '#6b2c2c' : 'transparent') + ';color:' + (isFP ? '#f28b82' : '#888') + ';border-radius:2px;cursor:pointer;font-size:9px;';
    fpBtn.onclick = function(e) { e.stopPropagation(); flagSecret(si, 'fp'); };

    btnRow.appendChild(tpBtn);
    btnRow.appendChild(fpBtn);
    topRow.appendChild(typeSpan);
    topRow.appendChild(btnRow);
    item.appendChild(topRow);

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

async function flagSecret(secretIdx, verdict) {
  secretReviews[secretIdx] = verdict;
  // Save to corpus
  if (currentIdx >= 0) {
    var r = corpusCache[currentIdx];
    if (!r) return;
    if (!r.review) r.review = { correct: null, actual_blocks: null, notes: '' };
    r.review.secret_reviews = Object.assign({}, secretReviews);

    await fetch('/api/review', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        index: currentIdx,
        correct: r.review.correct,
        notes: r.review.notes || '',
        actual_blocks: r.review.actual_blocks,
        secret_reviews: r.review.secret_reviews,
      })
    });
  }
  renderSecretsList();
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
    var m = corpusMeta.find(function(mm) { return mm.idx === filteredIndices[i]; });
    if (m && !m.has_review) {
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

  // "Wrong" auto-marks all un-reviewed secrets as FP
  // "Correct" auto-marks all un-reviewed secrets as TP
  if (currentSecrets.length > 0) {
    var autoVerdict = (action === 'reject') ? 'fp' : (action === 'approve') ? 'tp' : null;
    if (autoVerdict) {
      for (var si = 0; si < currentSecrets.length; si++) {
        if (!secretReviews[si]) {
          secretReviews[si] = autoVerdict;
        }
      }
    }
  }

  var sr = Object.keys(secretReviews).length > 0 ? Object.assign({}, secretReviews) : null;
  var resp = await fetch('/api/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      index: currentIdx,
      correct: correct,
      notes: notes,
      actual_blocks: userBlocks.length > 0 ? userBlocks : null,
      secret_reviews: sr,
    })
  });
  if (resp.ok) {
    if (corpusCache[currentIdx]) {
      corpusCache[currentIdx].review = { correct: correct, notes: notes, actual_blocks: userBlocks.length > 0 ? userBlocks : null, secret_reviews: sr };
    }
    // Update metadata
    var meta = corpusMeta.find(function(m) { return m.idx === currentIdx; });
    if (meta) { meta.has_review = true; meta.review_correct = correct; }
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

        elif parsed.path == "/api/corpus_meta":
            # Paginated metadata — send only fields needed for sidebar
            qs = parse_qs(parsed.query)
            page = int(qs.get("page", [0])[0])
            size = int(qs.get("size", [PAGE_SIZE])[0])
            start = page * size
            end = min(start + size, len(CORPUS))

            meta = []
            for i in range(start, end):
                r = CORPUS[i]
                blocks = r.get("heuristic_blocks", r.get("zones", []))
                secrets = r.get("secrets", [])
                zone_types = list({b.get("zone_type", "") for b in blocks})
                max_conf = max(
                    [b.get("confidence", 0) for b in blocks] + [s.get("confidence", 0) for s in secrets] + [0]
                )
                meta.append(
                    {
                        "idx": i,
                        "prompt_id": (r.get("prompt_id") or "")[:12],
                        "total_lines": r.get("total_lines", 0),
                        "num_zones": len(blocks),
                        "num_secrets": len(secrets),
                        "zone_types": zone_types,
                        "max_confidence": round(max_conf, 2),
                        "has_review": r.get("review") is not None and (r["review"] or {}).get("correct") is not None,
                        "review_correct": (r.get("review") or {}).get("correct"),
                        "secret_entity_types": list({s.get("entity_type", "") for s in secrets}),
                    }
                )
            self._json_response(
                {
                    "items": meta,
                    "total": len(CORPUS),
                    "page": page,
                    "page_size": size,
                }
            )

        elif parsed.path == "/api/corpus":
            # Full corpus — kept for backward compatibility with small corpora
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(CORPUS, ensure_ascii=False).encode())

        elif parsed.path.startswith("/api/prompt/"):
            # Fetch single prompt by index
            try:
                idx = int(parsed.path.split("/")[-1])
                if 0 <= idx < len(CORPUS):
                    self._json_response(CORPUS[idx])
                else:
                    self.send_error(404, "Index out of range")
            except ValueError:
                self.send_error(400, "Invalid index")

        elif parsed.path == "/api/stats":
            # Summary stats for the header
            total = len(CORPUS)
            reviewed = sum(1 for r in CORPUS if r.get("review") and (r["review"] or {}).get("correct") is not None)
            with_secrets = sum(1 for r in CORPUS if r.get("secrets") and len(r["secrets"]) > 0)
            with_zones = sum(1 for r in CORPUS if (r.get("heuristic_blocks") or r.get("zones") or []))
            rejected = sum(1 for r in CORPUS if r.get("review") and (r["review"] or {}).get("correct") is False)

            # Secret verdict stats
            tp_count = 0
            fp_count = 0
            for r in CORPUS:
                rev = (r.get("review") or {}).get("secret_reviews") or {}
                for v in rev.values():
                    if v == "tp":
                        tp_count += 1
                    elif v == "fp":
                        fp_count += 1

            self._json_response(
                {
                    "total": total,
                    "reviewed": reviewed,
                    "rejected": rejected,
                    "with_secrets": with_secrets,
                    "with_zones": with_zones,
                    "secret_tp": tp_count,
                    "secret_fp": fp_count,
                }
            )

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
                    "secret_reviews": body.get("secret_reviews"),
                }
                _save_corpus()
                self._json_response({"ok": True})
            else:
                self.send_error(400, "Invalid index")

        elif self.path == "/api/detect_secrets":
            text = body.get("text", "")
            result = _run_unified_detection(text)
            self._json_response({"findings": result["secrets"]})

        elif self.path == "/api/save_secrets":
            idx = body.get("index", -1)
            if 0 <= idx < len(CORPUS):
                CORPUS[idx]["secrets"] = body.get("secrets", [])
                _save_corpus()
                self._json_response({"ok": True})
            else:
                self.send_error(400, "Invalid index")

        elif self.path == "/api/detect_all":
            text = body.get("text", "")
            result = _run_unified_detection(text)
            self._json_response(
                {
                    "zones": result["zones"],
                    "secrets": result["secrets"],
                }
            )
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
    parser.add_argument("--corpus", type=str, default="data/wildchat_unified/candidates.jsonl")
    parser.add_argument("--port", type=int, default=8234)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    _load_corpus(Path(args.corpus))

    # Pre-warm the Rust detector
    detector = _get_unified_detector()
    detector_status = "Rust UnifiedDetector" if detector else "NOT available"

    server = HTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"\n  Prompt Analysis Reviewer running at http://localhost:{args.port}")
    print(f"  Corpus: {args.corpus} ({len(CORPUS)} records)")
    print(f"  Detector: {detector_status}")
    print(f"\n  Keys: a=approve r=reject s=skip n/right=next p/left=prev u=unreviewed")
    print(f"        click/shift+click lines to select, m=mark as block, Esc=clear selection\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
