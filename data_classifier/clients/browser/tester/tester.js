import { createScanner } from './dist/scanner.esm.js';

const XOR_KEY = 0x5a;

function decodeXor(encoded) {
  if (encoded.startsWith('xor:')) encoded = encoded.slice(4);
  const raw = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
  const decoded = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) decoded[i] = raw[i] ^ XOR_KEY;
  return new TextDecoder().decode(decoded);
}

const scanner = createScanner();
const inputEl = document.getElementById('input');
const verboseEl = document.getElementById('verbose');
const strategyEl = document.getElementById('strategy');
const btnEl = document.getElementById('scan-btn');
const resultsEl = document.getElementById('results');
const unifiedOut = document.getElementById('unified-out');
const legendEl = document.getElementById('legend');
const findingsSummary = document.getElementById('findings-summary');
const findingsJson = document.getElementById('findings-json');
const scanTimeEl = document.getElementById('scan-time');
const storiesEl = document.getElementById('stories');
const storiesRow = document.getElementById('stories-row');
const annotationEl = document.getElementById('annotation');
const rawToggle = document.getElementById('raw-toggle');
const rawJson = document.getElementById('raw-json');
const zonesEnabledEl = document.getElementById('zones-enabled');
const storyCategoryEl = document.getElementById('story-category');

let allStories = [];

// ── Story loading ────────────────────────────────────────────────

async function loadStories() {
  const secretStories = await loadJsonl('./corpus/stories.json', 'secret');
  const zoneShowcase = await loadJsonl('./corpus/zone-showcase.jsonl', 'zone-showcase');
  const zoneReal = await loadJsonl('./corpus/zone-real.jsonl', 'zone-real');

  allStories = [...secretStories, ...zoneReal, ...zoneShowcase];

  if (allStories.length) {
    storiesRow.style.display = 'block';
    populateStoryDropdown('all');
  }
}

async function loadJsonl(url, tag) {
  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    const text = await res.text();
    if (text.startsWith('<')) return [];
    return text.split('\n').filter(Boolean).map((l) => {
      const d = JSON.parse(l);
      d._tag = tag;
      return d;
    });
  } catch { return []; }
}

loadStories();

function populateStoryDropdown(category) {
  // Clear all options except the first placeholder
  while (storiesEl.options.length > 1) storiesEl.remove(1);

  const filtered = category === 'all'
    ? allStories
    : allStories.filter((s) => s._tag === category);

  for (const s of filtered) {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.title || s.id;
    storiesEl.appendChild(opt);
  }
  storiesEl.value = '';
}

storyCategoryEl.addEventListener('change', () => {
  populateStoryDropdown(storyCategoryEl.value);
  annotationEl.style.display = 'none';
});

storiesEl.addEventListener('change', () => {
  const story = allStories.find((s) => s.id === storiesEl.value);
  if (story) {
    inputEl.value = decodeXor(story.prompt_xor);
    annotationEl.textContent = story.annotation || '';
    annotationEl.style.display = story.annotation ? 'block' : 'none';
  } else {
    inputEl.value = '';
    annotationEl.style.display = 'none';
  }
});

function getStories() { return allStories; }

// ── Controls ─────────────────────────────────────────────────────

rawToggle.addEventListener('click', () => {
  const visible = rawJson.style.display === 'block';
  rawJson.style.display = visible ? 'none' : 'block';
  rawToggle.textContent = visible ? 'Show raw JSON' : 'Hide raw JSON';
});

btnEl.addEventListener('click', async () => {
  const text = inputEl.value;
  const opts = {
    verbose: verboseEl.checked,
    redactStrategy: strategyEl.value,
    dangerouslyIncludeRawValues: true,
    zones: zonesEnabledEl.checked,
  };
  try {
    const { findings, redactedText, scannedMs, zones } = await scanner.scan(text, opts);
    resultsEl.style.display = 'block';
    scanTimeEl.textContent = scannedMs.toFixed(1) + ' ms';
    renderFindings(findings);
    renderUnifiedOutput(text, findings, zones);
    // Debug: show zone count in scan time area
    const zoneCount = (zones && zones.blocks) ? zones.blocks.length : 0;
    scanTimeEl.textContent = scannedMs.toFixed(1) + ' ms | ' + findings.length + ' secrets | ' + zoneCount + ' zones';
    findingsJson.textContent = JSON.stringify({ scannedMs, findings, zones }, null, 2);
  } catch (err) {
    resultsEl.style.display = 'block';
    findingsSummary.textContent = '';
    unifiedOut.textContent = '';
    const errDiv = document.createElement('div');
    errDiv.className = 'error';
    errDiv.textContent = 'Error: ' + ((err && err.message) || err);
    findingsSummary.appendChild(errDiv);
  }
});

// ── Findings cards ───────────────────────────────────────────────

function renderFindings(findings) {
  findingsSummary.textContent = '';
  if (!findings.length) {
    const div = document.createElement('div');
    div.className = 'no-findings';
    div.textContent = 'No secrets detected.';
    findingsSummary.appendChild(div);
    return;
  }
  for (const f of findings) {
    const card = document.createElement('div');
    card.className = 'finding-card';

    const typeEl = document.createElement('div');
    typeEl.className = 'finding-type';
    typeEl.textContent = f.display_name || f.entity_type;
    if (f.detection_type) {
      const dtSpan = document.createElement('span');
      dtSpan.style.cssText = 'font-weight:400;color:#666;margin-left:8px;font-size:12px';
      dtSpan.textContent = '(' + f.detection_type + ')';
      typeEl.appendChild(dtSpan);
    }
    card.appendChild(typeEl);

    const metaEl = document.createElement('div');
    metaEl.className = 'finding-meta';
    const parts = ['engine: ' + f.engine, 'confidence: ' + f.confidence, 'sensitivity: ' + f.sensitivity];
    if (f.kv) {
      const keySpan = document.createElement('span');
      keySpan.className = 'finding-key';
      keySpan.textContent = f.kv.key;
      metaEl.appendChild(document.createTextNode('key: '));
      metaEl.appendChild(keySpan);
      metaEl.appendChild(document.createTextNode(' | tier: ' + f.kv.tier + ' | ' + parts.join(' | ')));
    } else {
      metaEl.textContent = parts.join(' | ');
    }
    card.appendChild(metaEl);

    if (f.match) {
      const matchEl = document.createElement('div');
      matchEl.className = 'finding-match';
      const raw = f.match.valueRaw || f.match.valueMasked || '';
      matchEl.appendChild(document.createTextNode('matched: '));
      const code = document.createElement('code');
      code.className = 'finding-matched-value';
      code.textContent = raw;
      matchEl.appendChild(code);
      if (typeof f.match.start === 'number') {
        matchEl.appendChild(document.createTextNode(' (offset ' + f.match.start + '\u2013' + f.match.end + ')'));
      }
      card.appendChild(matchEl);
    }

    if (f.details) {
      const detailsEl = document.createElement('div');
      detailsEl.className = 'finding-details';
      const items = ['pattern: ' + f.details.pattern, 'validator: ' + f.details.validator];
      if (f.details.entropy) {
        const e = f.details.entropy;
        items.push(
          'shannon: ' + e.shannon.toFixed(2),
          'relative: ' + e.relative.toFixed(2),
          'charset: ' + e.charset,
          'entropy score: ' + e.score.toFixed(2)
        );
      }
      if (f.details.tier) items.push('tier: ' + f.details.tier);
      detailsEl.textContent = items.join(' | ');
      card.appendChild(detailsEl);
    }

    findingsSummary.appendChild(card);
  }
}

// ── Unified output renderer ──────────────────────────────────────

const ZONE_COLORS = {
  code: { border: '#3b82f6', label: 'Code' },
  config: { border: '#f59e0b', label: 'Config' },
  markup: { border: '#ef4444', label: 'Markup' },
  query: { border: '#22c55e', label: 'Query' },
  cli_shell: { border: '#8b5cf6', label: 'CLI' },
  error_output: { border: '#f97316', label: 'Error' },
  data: { border: '#06b6d4', label: 'Data' },
  natural_language: { border: '#9ca3af', label: 'Prose' },
};

function renderUnifiedOutput(text, findings, zones) {
  unifiedOut.textContent = '';
  legendEl.textContent = '';

  const lines = text.split('\n');

  // Build a map: lineIndex -> zone info
  const lineZones = new Map();
  const activeZoneTypes = new Set();
  if (zones && zones.blocks) {
    for (const block of zones.blocks) {
      activeZoneTypes.add(block.zone_type);
      for (let i = block.start_line; i < block.end_line && i < lines.length; i++) {
        lineZones.set(i, block);
      }
    }
  }

  // Build legend
  if (findings.length > 0) {
    const item = document.createElement('span');
    item.className = 'legend-item';
    const swatch = document.createElement('span');
    swatch.className = 'legend-swatch';
    swatch.style.background = '#dc2626';
    item.appendChild(swatch);
    item.appendChild(document.createTextNode('Secret'));
    legendEl.appendChild(item);
  }
  for (const zt of activeZoneTypes) {
    const c = ZONE_COLORS[zt];
    if (!c) continue;
    const item = document.createElement('span');
    item.className = 'legend-item';
    const swatch = document.createElement('span');
    swatch.className = 'legend-swatch';
    swatch.style.background = c.border;
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(c.label));
    legendEl.appendChild(item);
  }

  // Build sorted secret spans
  const secretSpans = findings
    .filter((f) => f.match && typeof f.match.start === 'number')
    .map((f) => ({
      start: f.match.start,
      end: f.match.end,
      raw: f.match.valueRaw || f.match.valueMasked || '',
      type: f.display_name || f.entity_type,
    }))
    .sort((a, b) => a.start - b.start);

  // Merge overlapping spans
  const merged = [];
  for (const s of secretSpans) {
    if (merged.length && s.start <= merged[merged.length - 1].end) {
      const last = merged[merged.length - 1];
      last.end = Math.max(last.end, s.end);
    } else {
      merged.push({ ...s });
    }
  }

  // Render line by line
  let charOffset = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineStart = charOffset;
    const lineEnd = charOffset + line.length;

    const lineEl = document.createElement('div');
    lineEl.className = 'unified-line';
    const zoneBlock = lineZones.get(i);
    if (zoneBlock) {
      lineEl.setAttribute('data-zone', zoneBlock.zone_type);
    }

    // Line number
    const numEl = document.createElement('span');
    numEl.className = 'line-num';
    numEl.textContent = String(i + 1);
    lineEl.appendChild(numEl);

    // Line text with inline secret highlights
    const textEl = document.createElement('span');
    textEl.className = 'line-text';

    // Zone label on first line of each block
    if (zoneBlock && zoneBlock.start_line === i) {
      const label = document.createElement('span');
      label.className = 'zone-label zone-label-' + zoneBlock.zone_type;
      let labelText = (ZONE_COLORS[zoneBlock.zone_type] || {}).label || zoneBlock.zone_type;
      if (zoneBlock.language_hint) labelText += ' ' + zoneBlock.language_hint;
      label.textContent = labelText;
      textEl.appendChild(label);
    }

    // Render line content with secret spans
    renderLineWithSecrets(textEl, line, lineStart, lineEnd, merged);

    lineEl.appendChild(textEl);
    unifiedOut.appendChild(lineEl);

    charOffset = lineEnd + 1; // +1 for \n
  }
}

function renderLineWithSecrets(container, line, lineStart, lineEnd, secretSpans) {
  // Find secrets that overlap this line
  const overlapping = secretSpans.filter(
    (s) => s.start < lineEnd && s.end > lineStart
  );

  if (!overlapping.length) {
    container.appendChild(document.createTextNode(line || '\u200b'));
    return;
  }

  let pos = lineStart;
  for (const span of overlapping) {
    const spanStart = Math.max(span.start, lineStart);
    const spanEnd = Math.min(span.end, lineEnd);

    // Text before this secret
    if (spanStart > pos) {
      container.appendChild(document.createTextNode(line.slice(pos - lineStart, spanStart - lineStart)));
    }

    // The secret span — shows [TYPE], hover reveals actual value
    const secretEl = document.createElement('span');
    secretEl.className = 'secret-redacted';
    secretEl.textContent = '[' + span.type + ']';

    const tooltip = document.createElement('span');
    tooltip.className = 'secret-tooltip';
    tooltip.textContent = line.slice(spanStart - lineStart, spanEnd - lineStart);
    secretEl.appendChild(tooltip);

    container.appendChild(secretEl);
    pos = spanEnd;
  }

  // Text after last secret
  if (pos < lineEnd) {
    container.appendChild(document.createTextNode(line.slice(pos - lineStart)));
  }
}

// ── Benchmark ────────────────────────────────────────────────────

const benchBtn = document.getElementById('bench-btn');
const perfBar = document.getElementById('perf-bar');
const perfBarFill = document.getElementById('perf-bar-fill');
const perfGrid = document.getElementById('perf-grid');
const perfNote = document.getElementById('perf-note');
const benchRoundsEl = document.getElementById('bench-rounds');

benchBtn.addEventListener('click', async () => {
  const BENCH_ROUNDS = parseInt(benchRoundsEl.value, 10) || 10;
  if (!getStories().length) {
    perfNote.textContent = 'No stories loaded — cannot benchmark.';
    return;
  }
  benchBtn.disabled = true;
  benchBtn.textContent = 'Running...';
  perfBar.style.display = '';
  perfBarFill.style.width = '0%';
  perfGrid.style.display = 'none';
  perfNote.textContent = '';

  const prompts = getStories().map((s) => decodeXor(s.prompt_xor));
  const totalScans = prompts.length * BENCH_ROUNDS;
  const latencies = [];
  let done = 0;

  for (let round = 0; round < BENCH_ROUNDS; round++) {
    for (const text of prompts) {
      const { scannedMs } = await scanner.scan(text, {});
      latencies.push(scannedMs);
      done++;
      perfBarFill.style.width = ((done / totalScans) * 100) + '%';
    }
  }

  latencies.sort((a, b) => a - b);
  const mean = latencies.reduce((s, x) => s + x, 0) / latencies.length;
  const p50 = latencies[Math.floor(latencies.length * 0.5)];
  const p95 = latencies[Math.floor(latencies.length * 0.95)];
  const p99 = latencies[Math.floor(latencies.length * 0.99)];
  const max = latencies[latencies.length - 1];
  const warmStart = latencies.length > prompts.length ? latencies.slice(prompts.length) : [];
  const warmMean = warmStart.length ? warmStart.reduce((s, x) => s + x, 0) / warmStart.length : mean;

  const stats = [
    { value: mean.toFixed(2), label: 'Mean (ms)' },
    { value: p50.toFixed(2), label: 'P50 (ms)' },
    { value: p95.toFixed(2), label: 'P95 (ms)' },
    { value: p99.toFixed(2), label: 'P99 (ms)' },
    { value: max.toFixed(2), label: 'Max (ms)' },
    { value: warmMean.toFixed(2), label: 'Warm mean (ms)' },
  ];

  perfGrid.textContent = '';
  for (const s of stats) {
    const div = document.createElement('div');
    div.className = 'perf-stat';
    const valEl = document.createElement('div');
    valEl.className = 'perf-value';
    valEl.textContent = s.value;
    const labEl = document.createElement('div');
    labEl.className = 'perf-label';
    labEl.textContent = s.label;
    div.appendChild(valEl);
    div.appendChild(labEl);
    perfGrid.appendChild(div);
  }
  perfGrid.style.display = '';
  perfBar.style.display = 'none';

  const avgLen = Math.round(prompts.reduce((s, p) => s + p.length, 0) / prompts.length);
  perfNote.textContent =
    totalScans + ' scans (' + getStories().length + ' stories x ' + BENCH_ROUNDS + ' rounds). ' +
    'Avg prompt: ' + avgLen.toLocaleString() + ' chars.';

  benchBtn.disabled = false;
  benchBtn.textContent = 'Run again';
});
