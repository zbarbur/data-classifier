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
  'tester/corpus/stories.json',
  'dist/data_classifier_core_bg.wasm',
  'dist/unified_patterns.json',
  'tester/corpus/zone-showcase.jsonl',
  'tester/corpus/zone-real.jsonl',
  // Copy dist into tester/ so the tester works when served standalone
  { src: 'dist/scanner.esm.js', dest: 'tester/dist/scanner.esm.js' },
  { src: 'dist/worker.esm.js', dest: 'tester/dist/worker.esm.js' },
  { src: 'dist/data_classifier_core_bg.wasm', dest: 'tester/dist/data_classifier_core_bg.wasm' },
  { src: 'dist/unified_patterns.json', dest: 'tester/dist/unified_patterns.json' },
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

for (const entry of INCLUDES) {
  const srcRel = typeof entry === 'string' ? entry : entry.src;
  const destRel = typeof entry === 'string' ? entry : entry.dest;
  const src = resolve(ROOT, srcRel);
  const dest = resolve(outDir, destRel);
  mkdirSync(dirname(dest), { recursive: true });

  // Strip dev-only fields from package.json for distribution
  if (srcRel === 'package.json') {
    const pkg = JSON.parse(readFileSync(src, 'utf8'));
    delete pkg.scripts;
    delete pkg.devDependencies;
    const { writeFileSync } = await import('node:fs');
    writeFileSync(dest, JSON.stringify(pkg, null, 2) + '\n');
  } else {
    cpSync(src, dest);
  }

  const bytes = statSync(dest).size;
  const gz = gzipSync(readFileSync(dest)).length;
  totalRaw += bytes;
  totalGz += gz;
}

console.log(`\n  Packaged to: ${outDir}`);
console.log(`  Files:       ${INCLUDES.length}`);
console.log(`  Size:        ${fmt(totalRaw)} (${fmt(totalGz)} gz)`);

// Create zip if --zip flag is passed
if (process.argv.includes('--zip')) {
  const { execFileSync } = await import('node:child_process');
  const pkg = JSON.parse(readFileSync(resolve(ROOT, 'package.json'), 'utf8'));
  const zipName = `data-classifier-browser-${pkg.version}.zip`;
  const zipPath = resolve(ROOT, zipName);
  rmSync(zipPath, { force: true });
  execFileSync('zip', ['-r', zipPath, '.'], { cwd: outDir, stdio: 'pipe' });
  const zipSize = statSync(zipPath).size;
  console.log(`  Zip:         ${zipPath}`);
  console.log(`               ${fmt(zipSize)}\n`);
}

function fmt(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}
