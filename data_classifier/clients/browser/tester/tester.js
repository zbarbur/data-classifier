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
const redactedOut = document.getElementById('redacted-out');
const findingsOut = document.getElementById('findings-out');
const storiesEl = document.getElementById('stories');
const storiesRow = document.getElementById('stories-row');
const annotationEl = document.getElementById('annotation');

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
    storiesRow.style.display = '';
  } catch {
    // stories.jsonl not available — hide dropdown, tester works without it
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

btnEl.addEventListener('click', async () => {
  const text = inputEl.value;
  const opts = {
    verbose: verboseEl.checked,
    redactStrategy: strategyEl.value,
  };
  try {
    const { findings, redactedText, scannedMs } = await scanner.scan(text, opts);
    redactedOut.textContent = redactedText;
    findingsOut.textContent = JSON.stringify({ scannedMs, findings }, null, 2);
  } catch (err) {
    findingsOut.textContent = 'error: ' + ((err && err.message) || err);
  }
});

loadStories();
