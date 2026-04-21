// Redaction strategies. Right-to-left replacement so earlier offsets
// remain valid as the text mutates. For KV findings the match span is
// already the value only (parsers emit valueStart/valueEnd inside the
// quotes), so the key stays visible naturally.

const STRATEGIES = new Set(['type-label', 'asterisk', 'placeholder', 'none']);

export function redact(text, findings, strategy = 'type-label') {
  if (!STRATEGIES.has(strategy)) {
    throw new Error(`redact: unknown strategy "${strategy}"`);
  }
  if (strategy === 'none' || !findings.length) return text;

  const sorted = [...findings].sort((a, b) => b.match.start - a.match.start);
  let out = text;
  let leftBound = Infinity;
  for (const f of sorted) {
    if (f.match.end > leftBound) continue;
    const replacement = replacementFor(f, strategy);
    out = out.slice(0, f.match.start) + replacement + out.slice(f.match.end);
    leftBound = f.match.start;
  }
  return out;
}

function replacementFor(finding, strategy) {
  const length = finding.match.end - finding.match.start;
  switch (strategy) {
    case 'type-label':
      return `[REDACTED:${finding.entity_type}]`;
    case 'asterisk':
      return '*'.repeat(length);
    case 'placeholder':
      return '«secret»';
    default:
      throw new Error(`redact: unknown strategy "${strategy}"`);
  }
}
