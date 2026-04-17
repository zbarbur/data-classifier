import { createScanner } from '../dist/scanner.esm.js';

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
const originalOut = document.getElementById('original-out');
const redactedOut = document.getElementById('redacted-out');
const findingsSummary = document.getElementById('findings-summary');
const findingsJson = document.getElementById('findings-json');
const scanTimeEl = document.getElementById('scan-time');
const storiesEl = document.getElementById('stories');
const storiesRow = document.getElementById('stories-row');
const annotationEl = document.getElementById('annotation');
const rawToggle = document.getElementById('raw-toggle');
const rawJson = document.getElementById('raw-json');

let stories = [];

async function loadStories() {
  try {
    const res = await fetch('./corpus/stories.jsonl');
    if (!res.ok) return;
    const text = await res.text();
    stories = text
      .split('\n')
      .filter(Boolean)
      .map((l) => JSON.parse(l));
    for (const s of stories) {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.title;
      storiesEl.appendChild(opt);
    }
    storiesRow.style.display = 'block';
  } catch {
    // stories.jsonl not available
  }
}

storiesEl.addEventListener('change', () => {
  const story = stories.find((s) => s.id === storiesEl.value);
  if (story) {
    inputEl.value = decodeXor(story.prompt_xor);
    annotationEl.textContent = story.annotation;
    annotationEl.style.display = '';
  } else {
    inputEl.value = '';
    annotationEl.style.display = 'none';
  }
});

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
  };
  try {
    const { findings, redactedText, scannedMs } = await scanner.scan(text, opts);
    resultsEl.style.display = 'block';
    scanTimeEl.textContent = `${scannedMs.toFixed(1)} ms`;
    renderFindings(findings);
    renderOriginalWithHighlights(originalOut, text, findings);
    renderRedacted(redactedOut, redactedText);
    findingsJson.textContent = JSON.stringify({ scannedMs, findings }, null, 2);
  } catch (err) {
    resultsEl.style.display = 'block';
    findingsSummary.textContent = '';
    originalOut.textContent = '';
    redactedOut.textContent = '';
    const errDiv = document.createElement('div');
    errDiv.className = 'error';
    errDiv.textContent = 'Error: ' + ((err && err.message) || err);
    findingsSummary.appendChild(errDiv);
  }
});

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
    typeEl.textContent = f.entity_type;
    card.appendChild(typeEl);

    const metaEl = document.createElement('div');
    metaEl.className = 'finding-meta';
    const parts = [`engine: ${f.engine}`, `confidence: ${f.confidence}`, `sensitivity: ${f.sensitivity}`];
    if (f.kv) {
      const keySpan = document.createElement('span');
      keySpan.className = 'finding-key';
      keySpan.textContent = f.kv.key;
      metaEl.textContent = '';
      metaEl.appendChild(document.createTextNode('key: '));
      metaEl.appendChild(keySpan);
      metaEl.appendChild(document.createTextNode(` | tier: ${f.kv.tier} | ${parts.join(' | ')}`));
    } else {
      metaEl.textContent = parts.join(' | ');
    }
    card.appendChild(metaEl);

    if (f.match && f.match.valueMasked) {
      const evidenceEl = document.createElement('div');
      evidenceEl.className = 'finding-evidence';
      evidenceEl.textContent = `matched: ${f.match.valueMasked}`;
      card.appendChild(evidenceEl);
    }

    findingsSummary.appendChild(card);
  }
}

function renderOriginalWithHighlights(el, text, findings) {
  el.textContent = '';
  if (!findings.length) {
    el.appendChild(document.createTextNode(text));
    return;
  }
  // Sort findings by start offset ascending, merge overlapping spans
  const spans = findings
    .filter((f) => f.match && typeof f.match.start === 'number')
    .map((f) => ({ start: f.match.start, end: f.match.end }))
    .sort((a, b) => a.start - b.start);

  // Merge overlapping
  const merged = [];
  for (const s of spans) {
    if (merged.length && s.start <= merged[merged.length - 1].end) {
      merged[merged.length - 1].end = Math.max(merged[merged.length - 1].end, s.end);
    } else {
      merged.push({ ...s });
    }
  }

  let last = 0;
  for (const s of merged) {
    if (s.start > last) el.appendChild(document.createTextNode(text.slice(last, s.start)));
    const span = document.createElement('span');
    span.className = 'secret-highlight';
    span.textContent = text.slice(s.start, s.end);
    el.appendChild(span);
    last = s.end;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

function renderRedacted(el, text) {
  el.textContent = '';
  const re = /\[REDACTED:[^\]]+\]|\*{3,}|\u00ABsecret\u00BB/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
    const span = document.createElement('span');
    span.className = 'redacted';
    span.textContent = m[0];
    el.appendChild(span);
    last = m.index + m[0].length;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

// Sync scroll between original and redacted panels
let syncing = false;
function syncScroll(source, target) {
  if (syncing) return;
  syncing = true;
  const maxScroll = source.scrollHeight - source.clientHeight;
  const ratio = maxScroll > 0 ? source.scrollTop / maxScroll : 0;
  target.scrollTop = ratio * (target.scrollHeight - target.clientHeight);
  syncing = false;
}
originalOut.addEventListener('scroll', () => syncScroll(originalOut, redactedOut));
redactedOut.addEventListener('scroll', () => syncScroll(redactedOut, originalOut));

loadStories();
