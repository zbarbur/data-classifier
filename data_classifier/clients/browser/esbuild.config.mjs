import esbuild from 'esbuild';
import { copyFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const dev = process.argv.includes('--dev');

const shared = {
  bundle: true,
  format: 'esm',
  target: ['es2022'],
  minify: !watch && !dev,
  sourcemap: dev,
  logLevel: 'info',
};

const builds = [
  {
    ...shared,
    entryPoints: ['src/scanner.js'],
    outfile: 'dist/scanner.esm.js',
  },
  {
    ...shared,
    entryPoints: ['src/worker.js'],
    outfile: 'dist/worker.esm.js',
  },
];

function copyAssets() {
  mkdirSync(resolve(__dirname, 'dist'), { recursive: true });
  copyFileSync(
    resolve(__dirname, 'assets/data_classifier_core_bg.wasm'),
    resolve(__dirname, 'dist/data_classifier_core_bg.wasm'),
  );
  copyFileSync(
    resolve(__dirname, 'assets/unified_patterns.json'),
    resolve(__dirname, 'dist/unified_patterns.json'),
  );
  // Copy dist into tester/dist/ so the tester page works during development
  // (same as scripts/package.js does for standalone distribution)
  mkdirSync(resolve(__dirname, 'tester/dist'), { recursive: true });
  for (const f of ['scanner.esm.js', 'worker.esm.js', 'data_classifier_core_bg.wasm', 'unified_patterns.json']) {
    copyFileSync(resolve(__dirname, 'dist', f), resolve(__dirname, 'tester/dist', f));
  }
}

if (watch) {
  const ctxs = await Promise.all(builds.map((b) => esbuild.context(b)));
  await Promise.all(ctxs.map((c) => c.watch()));
  copyAssets();
  console.log('esbuild: watching...');
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
  copyAssets();
  console.log('esbuild: done');
}
