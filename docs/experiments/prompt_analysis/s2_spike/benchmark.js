import { patterns } from "./patterns.js";

// XOR decode (key 0x5A) — mirror of data_classifier/patterns/_decoder.py
function decodeXor(s) {
  const b64 = s.startsWith("xor:") ? s.slice(4) : s;
  const raw = atob(b64);
  let out = "";
  for (let i = 0; i < raw.length; i++) {
    out += String.fromCharCode(raw.charCodeAt(i) ^ 0x5A);
  }
  return out;
}

// Compile all patterns once and report parse time separately.
const compileStart = performance.now();
const compiled = patterns.map(p => ({
  name: p.name,
  re: new RegExp(p.regex_source, p.flags || "g"),
  category: p.category,
}));
const compileMs = performance.now() - compileStart;

window.__runBenchmark = function (corpus) {
  // Warm-up (V8 JIT settle): scan first 100 prompts and discard timings.
  const warmupSize = Math.min(100, corpus.length);
  for (let i = 0; i < warmupSize; i++) {
    const text = decodeXor(corpus[i].text_xor);
    for (const c of compiled) {
      for (const _m of text.matchAll(c.re)) { /* discard */ }
    }
  }

  const heapBefore = (performance.memory && performance.memory.usedJSHeapSize) || 0;
  const perPrompt = [];
  const perPatternMax = new Array(compiled.length).fill(0);

  for (const rec of corpus) {
    const text = decodeXor(rec.text_xor);
    const totalStart = performance.now();
    let secretMs = 0;
    for (let i = 0; i < compiled.length; i++) {
      const patStart = performance.now();
      for (const _m of text.matchAll(compiled[i].re)) { /* discard */ }
      const dt = performance.now() - patStart;
      if (compiled[i].category === "Credential") secretMs += dt;
      if (dt > perPatternMax[i]) perPatternMax[i] = dt;
    }
    perPrompt.push({
      idx: rec.turn_index,
      length: rec.length,
      bucket: rec.bucket,
      ms: performance.now() - totalStart,
      secret_ms: secretMs,
    });
  }

  const heapAfter = (performance.memory && performance.memory.usedJSHeapSize) || 0;

  return {
    compileMs,
    patternCount: compiled.length,
    credentialPatternCount: compiled.filter(c => c.category === "Credential").length,
    corpusSize: corpus.length,
    perPrompt,
    perPatternMax: perPatternMax.map((ms, i) => ({
      name: compiled[i].name,
      category: compiled[i].category,
      max_ms: ms,
    })),
    heapDeltaBytes: heapAfter - heapBefore,
  };
};
