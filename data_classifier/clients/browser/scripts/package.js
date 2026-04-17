#!/usr/bin/env node
/**
 * Assemble a standalone delivery folder at dist-package/.
 * Contains everything a consumer needs — no repo checkout required.
 *
 * Usage: node scripts/package.js [--out <dir>]
 */

import { cpSync, mkdirSync, rmSync, readFileSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');

// Parse --out flag
let outDir = resolve(ROOT, 'dist-package');
const outIdx = process.argv.indexOf('--out');
if (outIdx !== -1 && process.argv[outIdx + 1]) {
  outDir = resolve(process.argv[outIdx + 1]);
}

// Files/dirs to include (mirrors package.json "files" + extras for standalone use)
const INCLUDES = [
  'dist/scanner.esm.js',
  'dist/worker.esm.js',
  'scanner.d.ts',
  'tester/index.html',
  'tester/tester.js',
  'tester/corpus/stories.jsonl',
  'docs/api.md',
  'docs/patterns.md',
  'docs/secret-scanner.md',
  'docs/stories.md',
  'README.md',
  'package.json',
];

// Clean and create
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

let totalRaw = 0;
let totalGz = 0;

for (const rel of INCLUDES) {
  const src = resolve(ROOT, rel);
  const dest = resolve(outDir, rel);
  mkdirSync(dirname(dest), { recursive: true });
  cpSync(src, dest);

  const bytes = statSync(dest).size;
  const gz = gzipSync(readFileSync(dest)).length;
  totalRaw += bytes;
  totalGz += gz;
}

console.log(`\n  Packaged to: ${outDir}`);
console.log(`  Files:       ${INCLUDES.length}`);
console.log(`  Size:        ${fmt(totalRaw)} (${fmt(totalGz)} gz)\n`);

function fmt(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}
