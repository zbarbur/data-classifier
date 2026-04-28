"""Local review server for zone detection labeled data.

Serves a browser UI to:
  - Browse prompts from the labeled corpus
  - View heuristic zone detection results with syntax-highlighted blocks
  - Run the zone detector on any prompt
  - Edit/approve/reject block annotations
  - Save review decisions back to the corpus JSONL

Usage:
    python -m docs.experiments.prompt_analysis.s4_zone_detection.review_server \
        --corpus docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl \
        --port 8234

Then open http://localhost:8234 in your browser.

Security note: This is a local-only development tool. The innerHTML usage below
renders corpus data that is already trusted (loaded from our own JSONL files).
All user-supplied text is escaped via escapeHtml() before insertion.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from docs.experiments.prompt_analysis.s4_zone_detection.zone_detector import detect_zones

log = logging.getLogger(__name__)

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
        log.info("Saved %d records to %s", len(CORPUS), CORPUS_PATH)


# The HTML page is served as a static asset.  All prompt text is escaped
# client-side via the dedicated escapeHtml() helper (creates a text node,
# reads back its .innerHTML — equivalent to textContent-based escaping).
# Block-annotation markers use only our own metadata strings (zone_type,
# method, confidence) which are controlled vocabulary, not user input.

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>S4 Zone Detection Reviewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; font-size: 13px; background: #1a1a2e; color: #e0e0e0; }
.container { display: flex; height: 100vh; }
.sidebar { width: 320px; border-right: 1px solid #333; overflow-y: auto; background: #16213e; flex-shrink: 0; }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.header { padding: 12px 16px; background: #0f3460; border-bottom: 1px solid #333; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.header h1 { font-size: 16px; color: #e94560; }
.content { flex: 1; overflow-y: auto; padding: 16px; }

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
.badge-none { background: #333; color: #888; }
.badge-reviewed { background: #1b4332; color: #52b788; }
.badge-rejected { background: #6b2c2c; color: #f28b82; }

.filters { display: flex; gap: 4px; flex-wrap: wrap; }
.filter-btn { padding: 3px 8px; border: 1px solid #444; background: #1a1a2e; color: #aaa; cursor: pointer; border-radius: 3px; font-size: 11px; }
.filter-btn.active { background: #0f3460; color: #fff; border-color: #e94560; }

.prompt-text { white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; }
.line { display: flex; }
.line-no { color: #555; min-width: 40px; text-align: right; padding-right: 12px; user-select: none; flex-shrink: 0; }
.line-content { flex: 1; }

.zone-code { background: rgba(45, 106, 79, 0.2); border-left: 3px solid #2d6a4f; padding-left: 8px; }
.zone-structured_data { background: rgba(92, 75, 153, 0.2); border-left: 3px solid #5c4b99; padding-left: 8px; }
.zone-cli_shell { background: rgba(181, 103, 39, 0.2); border-left: 3px solid #b56727; padding-left: 8px; }
.zone-natural_language { background: rgba(100, 100, 100, 0.1); }

.block-marker { font-size: 10px; padding: 2px 8px; margin: 4px 0; border-radius: 3px; display: inline-block; }
.block-start { background: #0f3460; color: #53a8b6; }
.block-end { background: #333; color: #888; }

.review-panel { padding: 12px 16px; background: #16213e; border-top: 1px solid #333; }
.review-panel h3 { margin-bottom: 8px; color: #e94560; font-size: 13px; }
.review-actions { display: flex; gap: 8px; margin-bottom: 8px; }
.btn { padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; }
.btn-approve { background: #2d6a4f; color: #fff; }
.btn-approve:hover { background: #40916c; }
.btn-reject { background: #6b2c2c; color: #fff; }
.btn-reject:hover { background: #993333; }
.btn-skip { background: #333; color: #ccc; }
.btn-skip:hover { background: #444; }
.btn-rerun { background: #0f3460; color: #53a8b6; }
.btn-rerun:hover { background: #1a4a80; }
.review-notes { width: 100%; padding: 6px 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; resize: vertical; min-height: 40px; }

.nav-btns { display: flex; gap: 8px; }
.nav-btn { padding: 4px 12px; background: #333; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 12px; }
.nav-btn:hover { background: #444; }

.custom-input { width: 100%; padding: 8px; background: #1a1a2e; border: 1px solid #444; color: #e0e0e0; border-radius: 4px; resize: vertical; min-height: 80px; font-family: inherit; }
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
        <button class="filter-btn" data-filter="none" onclick="setFilter('none')">No blocks</button>
        <button class="filter-btn" data-filter="unreviewed" onclick="setFilter('unreviewed')">Unreviewed</button>
        <button class="filter-btn" data-filter="reviewed" onclick="setFilter('reviewed')">Reviewed</button>
      </div>
    </div>
    <div class="sidebar-stats" id="stats"></div>
    <div id="list"></div>
  </div>
  <div class="main">
    <div class="header">
      <h1>S4 Zone Reviewer</h1>
      <div class="nav-btns">
        <button class="nav-btn" onclick="navigate(-1)">&#9664; Prev</button>
        <button class="nav-btn" onclick="navigate(1)">Next &#9654;</button>
        <button class="nav-btn" onclick="navigateUnreviewed()">Next unreviewed &#9654;&#9654;</button>
      </div>
      <button class="btn btn-rerun" onclick="showCustomInput()">Run on custom text</button>
    </div>
    <div class="content" id="content">
      <p style="color: #888; padding: 20px;">Select a prompt from the sidebar to begin reviewing.</p>
    </div>
    <div class="review-panel" id="review-panel" style="display:none;">
      <h3>Review</h3>
      <div class="review-actions">
        <button class="btn btn-approve" onclick="review('approve')">Correct</button>
        <button class="btn btn-reject" onclick="review('reject')">Wrong</button>
        <button class="btn btn-skip" onclick="review('skip')">Skip</button>
      </div>
      <textarea class="review-notes" id="review-notes" placeholder="Notes (optional)..."></textarea>
    </div>
  </div>
</div>

<script>
let corpus = [];
let filteredIndices = [];
let currentIdx = -1;
let currentFilter = 'all';

// Safe HTML escaping — creates a text node and reads back escaped content
function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

async function loadCorpus() {
  const resp = await fetch('/api/corpus');
  corpus = await resp.json();
  updateStats();
  filterList();
}

function updateStats() {
  const reviewed = corpus.filter(r => r.review && r.review.correct !== null).length;
  const total = corpus.length;
  const withBlocks = corpus.filter(r => r.heuristic_has_blocks).length;
  const el = document.getElementById('stats');
  el.textContent = total + ' prompts | ' + withBlocks + ' with blocks | ' + reviewed + ' reviewed';
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  filterList();
}

function filterList() {
  const search = document.getElementById('search').value.toLowerCase();
  filteredIndices = [];
  corpus.forEach(function(r, i) {
    if (currentFilter === 'code' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'code'; })) return;
    if (currentFilter === 'structured_data' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'structured_data'; })) return;
    if (currentFilter === 'cli_shell' && !(r.heuristic_blocks || []).some(function(b) { return b.zone_type === 'cli_shell'; })) return;
    if (currentFilter === 'none' && r.heuristic_has_blocks) return;
    if (currentFilter === 'unreviewed' && r.review && r.review.correct !== null) return;
    if (currentFilter === 'reviewed' && (!r.review || r.review.correct === null)) return;
    if (search && !(r.text || '').toLowerCase().includes(search) && !(r.prompt_id || '').includes(search)) return;
    filteredIndices.push(i);
  });
  renderList();
}

function renderList() {
  const listEl = document.getElementById('list');
  // Build list safely using DOM methods
  listEl.textContent = '';  // clear
  filteredIndices.forEach(function(idx) {
    const r = corpus[idx];
    const types = new Set((r.heuristic_blocks || []).map(function(b) { return b.zone_type; }));

    const item = document.createElement('div');
    item.className = 'item' + (idx === currentIdx ? ' active' : '');
    item.onclick = function() { selectPrompt(idx); };

    const idSpan = document.createElement('span');
    idSpan.className = 'id';
    idSpan.textContent = (r.prompt_id || '').slice(0, 10) + '... (' + r.total_lines + 'L)';

    const badgesSpan = document.createElement('span');
    badgesSpan.className = 'badges';

    function addBadge(cls, text) {
      const b = document.createElement('span');
      b.className = 'badge ' + cls;
      b.textContent = text;
      badgesSpan.appendChild(b);
    }

    if (types.has('code')) addBadge('badge-code', 'code');
    if (types.has('structured_data')) addBadge('badge-structured', 'struct');
    if (types.has('cli_shell')) addBadge('badge-cli', 'cli');
    if (!r.heuristic_has_blocks) addBadge('badge-none', 'none');
    if (r.review && r.review.correct === true) addBadge('badge-reviewed', 'ok');
    if (r.review && r.review.correct === false) addBadge('badge-rejected', 'bad');

    item.appendChild(idSpan);
    item.appendChild(badgesSpan);
    listEl.appendChild(item);
  });
}

function selectPrompt(idx) {
  currentIdx = idx;
  renderPrompt(corpus[idx]);
  renderList();
}

function renderPrompt(r) {
  const lines = (r.text || '').split('\n');
  const blocks = r.heuristic_blocks || [];

  // Build line-to-zone map
  const lineZones = {};
  blocks.forEach(function(b) {
    for (var l = b.start_line; l < b.end_line; l++) {
      lineZones[l] = b;
    }
  });

  // Build content safely using DOM
  var container = document.createElement('div');

  // Header
  var header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #333;';
  var headerLeft = document.createElement('div');
  var strong = document.createElement('strong');
  strong.textContent = r.prompt_id || '';
  var meta = document.createElement('span');
  meta.className = 'prompt-meta';
  meta.textContent = ' ' + lines.length + ' lines | ' + blocks.length + ' blocks';
  meta.style.cssText = 'font-size:11px;color:#888;margin-left:8px;';
  headerLeft.appendChild(strong);
  headerLeft.appendChild(meta);
  header.appendChild(headerLeft);
  container.appendChild(header);

  // Prompt text with zone highlighting
  var textDiv = document.createElement('div');
  textDiv.className = 'prompt-text';

  var inBlock = null;
  lines.forEach(function(line, i) {
    var zone = lineZones[i] || null;
    if (zone && zone !== inBlock) {
      var marker = document.createElement('div');
      marker.className = 'block-marker block-start';
      marker.textContent = '\u25BC ' + zone.zone_type + ' (' + zone.method + ', conf=' + zone.confidence.toFixed(2) + (zone.language_hint ? ', ' + zone.language_hint : '') + ') L' + zone.start_line + '-' + zone.end_line;
      textDiv.appendChild(marker);
      inBlock = zone;
    }
    if (!zone && inBlock) {
      var endMarker = document.createElement('div');
      endMarker.className = 'block-marker block-end';
      endMarker.textContent = '\u25B2 end block';
      textDiv.appendChild(endMarker);
      inBlock = null;
    }

    var lineDiv = document.createElement('div');
    lineDiv.className = 'line' + (zone ? ' zone-' + zone.zone_type : '');
    var lineNo = document.createElement('span');
    lineNo.className = 'line-no';
    lineNo.textContent = i;
    var lineContent = document.createElement('span');
    lineContent.className = 'line-content';
    lineContent.textContent = line || ' ';  // textContent = safe, no XSS
    lineDiv.appendChild(lineNo);
    lineDiv.appendChild(lineContent);
    textDiv.appendChild(lineDiv);
  });

  if (inBlock) {
    var finalEnd = document.createElement('div');
    finalEnd.className = 'block-marker block-end';
    finalEnd.textContent = '\u25B2 end block';
    textDiv.appendChild(finalEnd);
  }

  container.appendChild(textDiv);

  var contentEl = document.getElementById('content');
  contentEl.textContent = '';
  contentEl.appendChild(container);

  document.getElementById('review-panel').style.display = 'block';
  document.getElementById('review-notes').value = (r.review && r.review.notes) || '';
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

async function review(action) {
  if (currentIdx < 0) return;
  var notes = document.getElementById('review-notes').value;
  var correct = action === 'approve' ? true : action === 'reject' ? false : null;

  var resp = await fetch('/api/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ index: currentIdx, correct: correct, notes: notes })
  });
  if (resp.ok) {
    corpus[currentIdx].review = { correct: correct, notes: notes, actual_blocks: null };
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
  h3.textContent = 'Run zone detector on custom text';
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
  btn.textContent = 'Run detector';
  btn.onclick = runCustom;
  wrapper.appendChild(btn);
  contentEl.appendChild(wrapper);
  document.getElementById('review-panel').style.display = 'none';
}

async function runCustom() {
  var text = document.getElementById('custom-text').value;
  var resp = await fetch('/api/detect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ text: text })
  });
  var result = await resp.json();
  renderPrompt({
    prompt_id: 'custom',
    text: text,
    total_lines: text.split('\n').length,
    heuristic_has_blocks: result.blocks.length > 0,
    heuristic_blocks: result.blocks,
    review: { correct: null, notes: '', actual_blocks: null },
  });
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowRight' || e.key === 'n') navigate(1);
  if (e.key === 'ArrowLeft' || e.key === 'p') navigate(-1);
  if (e.key === 'a') review('approve');
  if (e.key === 'r') review('reject');
  if (e.key === 's') review('skip');
  if (e.key === 'u') navigateUnreviewed();
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
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            else:
                self.send_error(400, "Invalid index")

        elif self.path == "/api/detect":
            text = body.get("text", "")
            zones = detect_zones(text, prompt_id="custom")
            result = {
                "blocks": [
                    {
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                        "zone_type": b.zone_type,
                        "confidence": b.confidence,
                        "method": b.method,
                        "language_hint": b.language_hint,
                    }
                    for b in zones.blocks
                ]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # Suppress request logging


def main():
    parser = argparse.ArgumentParser(description="S4 Zone Detection Review Server")
    parser.add_argument(
        "--corpus",
        type=str,
        default="docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl",
    )
    parser.add_argument("--port", type=int, default=8234)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    _load_corpus(Path(args.corpus))

    server = HTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"\n  Zone Detection Reviewer running at http://localhost:{args.port}")
    print(f"  Corpus: {args.corpus} ({len(CORPUS)} records)")
    print(f"\n  Keyboard shortcuts: a=approve, r=reject, s=skip, n/right=next, p/left=prev, u=next unreviewed\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
