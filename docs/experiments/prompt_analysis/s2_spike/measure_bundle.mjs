import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import esbuild from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENTRY = path.join(__dirname, "browser_entry.js");
const VALIDATORS = path.resolve(__dirname, "../../../../data_classifier/engines/validators.py");
const REPORT_DIR = path.join(__dirname, "report");

const result = await esbuild.build({
  entryPoints: [ENTRY],
  bundle: true,
  minify: true,
  format: "esm",
  write: false,
  target: ["chrome120"],
});

if (result.errors.length > 0) {
  console.error("esbuild errors:", result.errors);
  process.exit(1);
}

const bundled = result.outputFiles[0].text;
const minifiedBytes = Buffer.byteLength(bundled, "utf8");
const gzippedBytes = zlib.gzipSync(bundled, { level: 9 }).length;

// Validator size projection: validators_python_LOC × 0.7 (JS/Python LOC ratio) × 30 (bytes/min-LOC).
const validatorsLOC = fs.readFileSync(VALIDATORS, "utf8").split("\n").length;
const projectedValidatorBytes = Math.round(validatorsLOC * 0.7 * 30);

const out = {
  spec: "S2",
  date: new Date().toISOString(),
  bundler: "esbuild (minify, format=esm, target=chrome120, gzip level 9)",
  measured: {
    bundled_modules: ["patterns.js", "entropy.js"],
    minified_bytes: minifiedBytes,
    minified_kb: +(minifiedBytes / 1024).toFixed(2),
    gzipped_bytes: gzippedBytes,
    gzipped_kb: +(gzippedBytes / 1024).toFixed(2),
  },
  projection: {
    validators_python_loc: validatorsLOC,
    projected_validator_bytes: projectedValidatorBytes,
    projected_validator_kb: +(projectedValidatorBytes / 1024).toFixed(2),
    formula: "loc * 0.7 (js/py ratio) * 30 (bytes/min-loc)",
  },
  projected_total_gzipped_bytes: gzippedBytes + projectedValidatorBytes,
  projected_total_gzipped_kb: +((gzippedBytes + projectedValidatorBytes) / 1024).toFixed(2),
  target: { gzipped_kb: 200, source: "queue.md S2 architectural commitment" },
};

fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, "bundle.json"), JSON.stringify(out, null, 2));
console.log(`wrote report/bundle.json`);
console.log(`measured gzipped:  ${out.measured.gzipped_kb} KB`);
console.log(`projected total:   ${out.projected_total_gzipped_kb} KB (target: ${out.target.gzipped_kb} KB)`);
