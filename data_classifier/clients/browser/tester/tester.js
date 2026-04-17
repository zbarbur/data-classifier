import { createScanner } from '../dist/scanner.esm.js';

const scanner = createScanner();
const inputEl = document.getElementById('input');
const verboseEl = document.getElementById('verbose');
const strategyEl = document.getElementById('strategy');
const btnEl = document.getElementById('scan-btn');
const redactedOut = document.getElementById('redacted-out');
const findingsOut = document.getElementById('findings-out');

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
