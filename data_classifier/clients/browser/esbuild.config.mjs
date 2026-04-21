import esbuild from 'esbuild';

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

if (watch) {
  const ctxs = await Promise.all(builds.map((b) => esbuild.context(b)));
  await Promise.all(ctxs.map((c) => c.watch()));
  console.log('esbuild: watching...');
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
  console.log('esbuild: done');
}
