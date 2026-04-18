import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check } from "recheck";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = path.join(__dirname, "report");

const { patterns } = await import("./patterns.js");

const results = [];
let i = 0;
for (const p of patterns) {
  i++;
  process.stdout.write(`\r[${i}/${patterns.length}] ${p.name.padEnd(40)}`);
  let res;
  try {
    res = await check(p.regex_source, p.flags || "g");
  } catch (e) {
    results.push({
      name: p.name,
      regex_source: p.regex_source,
      category: p.category,
      status: "error",
      error: String(e),
    });
    continue;
  }
  results.push({
    name: p.name,
    regex_source: p.regex_source,
    category: p.category,
    status: res.status,
    complexity_type: res.complexity?.type ?? null,
    attack_string: res.attack?.string ?? null,
    hotspot: res.hotspot ?? null,
  });
}
process.stdout.write("\n");

const counts = results.reduce((acc, r) => {
  let key;
  if (r.status === "vulnerable") {
    key = `vulnerable_${r.complexity_type || "unknown"}`;
  } else {
    key = r.status;
  }
  acc[key] = (acc[key] || 0) + 1;
  return acc;
}, {});

const out = {
  spec: "S2",
  date: new Date().toISOString(),
  pattern_count: patterns.length,
  counts,
  results,
};

fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, "redos.json"), JSON.stringify(out, null, 2));
console.log(`wrote report/redos.json`);
console.log(`counts: ${JSON.stringify(counts)}`);

const vulnerable = results.filter(r => r.status === "vulnerable");
if (vulnerable.length > 0) {
  console.log(`\nvulnerable patterns:`);
  for (const v of vulnerable) {
    console.log(`  ${v.name} [${v.category}]: ${v.complexity_type}`);
  }
}
