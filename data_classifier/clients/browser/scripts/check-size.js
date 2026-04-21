import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST = resolve(__dirname, '..', 'dist');
const BUDGET_GZ_KB = 20;

const files = ['scanner.esm.js', 'worker.esm.js'];
let totalRaw = 0;
let totalGz = 0;

console.log('');
for (const name of files) {
  const buf = readFileSync(resolve(DIST, name));
  const gz = gzipSync(buf);
  const rawKB = (buf.length / 1024).toFixed(1);
  const gzKB = (gz.length / 1024).toFixed(1);
  totalRaw += buf.length;
  totalGz += gz.length;
  console.log(`  ${name.padEnd(25)} ${rawKB.padStart(7)} KB  (${gzKB.padStart(5)} KB gz)`);
}
console.log('  ' + '-'.repeat(50));
const totalRawKB = (totalRaw / 1024).toFixed(1);
const totalGzKB = (totalGz / 1024).toFixed(1);
console.log(`  ${'total'.padEnd(25)} ${totalRawKB.padStart(7)} KB  (${totalGzKB.padStart(5)} KB gz)`);
console.log('');

const workerGzKB = gzipSync(readFileSync(resolve(DIST, 'worker.esm.js'))).length / 1024;
if (workerGzKB > BUDGET_GZ_KB) {
  console.log(`  ⚠  worker.esm.js is ${workerGzKB.toFixed(1)} KB gz — above ${BUDGET_GZ_KB} KB soft budget`);
}
console.log('');
