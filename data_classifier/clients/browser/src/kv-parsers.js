// KV parsers — JSON, env, code-literal.
// Mirrors data_classifier/engines/parsers.py. Each returned pair carries
// { key, value, valueStart, valueEnd } offsets into the original text, used
// by redaction.js to splice without re-searching.

const ENV_RE =
  /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s()\[\]{},]+))\s*$/gm;

const CODE_RE =
  /([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|:|=)\s*(?:"([^"]{1,500})"|'([^']{1,500})')/g;

export function parseKeyValues(text) {
  if (!text || !text.trim()) return [];

  const jsonPairs = parseJson(text);
  if (jsonPairs.length > 0) return jsonPairs;

  const results = [];
  results.push(...parseEnv(text));
  results.push(...parseCodeLiterals(text));

  // Deduplicate by (key, value) — ENV runs first so its entry wins when both parsers
  // match the same assignment (e.g. PASS="secret" matches both ENV_RE and CODE_RE).
  const seen = new Set();
  return results.filter((p) => {
    const sig = `${p.key}\0${p.value}`;
    if (seen.has(sig)) return false;
    seen.add(sig);
    return true;
  });
}

function parseJson(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return [];
  return flattenDict(data, '', text, { cursor: 0 });
}

function flattenDict(obj, prefix, text, state) {
  const out = [];
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...flattenDict(value, fullKey, text, state));
    } else if (Array.isArray(value)) {
      for (let i = 0; i < value.length; i++) {
        const item = value[i];
        if (item !== null && typeof item === 'object') {
          out.push(...flattenDict(item, `${fullKey}[${i}]`, text, state));
        } else if (item !== null && item !== undefined) {
          pushJsonPair(out, fullKey, String(item), text, state);
        }
      }
    } else if (value !== null && value !== undefined) {
      pushJsonPair(out, fullKey, String(value), text, state);
    }
  }
  return out;
}

function pushJsonPair(out, key, value, text, state) {
  const offsets = findValueOffset(text, value, state.cursor);
  if (offsets) {
    state.cursor = offsets.valueEnd;
    out.push({ key, value, valueStart: offsets.valueStart, valueEnd: offsets.valueEnd });
  } else {
    out.push({ key, value, valueStart: -1, valueEnd: -1 });
  }
}

function findValueOffset(text, value, from) {
  // JSON-encode the value to get the on-wire representation that matches
  // the raw text, handling escape sequences (\\, \", \n, \uXXXX, etc.).
  // This is correct for all string values in JSON (always quoted).
  const encoded = JSON.stringify(value);
  const qIdx = text.indexOf(encoded, from);
  if (qIdx >= 0) {
    // encoded starts with '"' and ends with '"'. The value span is between.
    // valueEnd points at the closing quote (exclusive) so that
    // text.slice(valueStart, valueEnd) yields the on-wire body; the
    // downstream consumer is responsible for interpreting escapes (or for
    // redaction, replacing the quoted span is sufficient).
    return { valueStart: qIdx + 1, valueEnd: qIdx + encoded.length - 1 };
  }
  // Fallback: bare search for non-string JSON primitives (numbers, booleans).
  // The generator coerces these via String(value); their on-wire form matches.
  const bare = text.indexOf(value, from);
  if (bare >= 0) {
    return { valueStart: bare, valueEnd: bare + value.length };
  }
  return null;
}

function parseEnv(text) {
  const out = [];
  for (const m of text.matchAll(ENV_RE)) {
    const key = m[1];
    let value = '';
    let valueStart = -1;
    let valueEnd = -1;
    if (m[2] !== undefined) {
      value = m[2];
      const quoteOpen = m.index + m[0].indexOf('"');
      valueStart = quoteOpen + 1;
      valueEnd = valueStart + value.length;
    } else if (m[3] !== undefined) {
      value = m[3];
      const quoteOpen = m.index + m[0].indexOf("'");
      valueStart = quoteOpen + 1;
      valueEnd = valueStart + value.length;
    } else if (m[4] !== undefined) {
      value = m[4];
      valueStart = m.index + m[0].indexOf(value, m[0].indexOf('='));
      valueEnd = valueStart + value.length;
    }
    if (value) out.push({ key, value, valueStart, valueEnd });
  }
  return out;
}

function parseCodeLiterals(text) {
  const out = [];
  for (const m of text.matchAll(CODE_RE)) {
    const key = m[1];
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : '';
    if (!value) continue;
    const quoteChar = m[2] !== undefined ? '"' : "'";
    // First quoteChar in m[0] is the opening quote: keys are identifiers
    // (no quotes) and operators (:=, :, =) contain no quotes.
    const quoteOpen = m.index + m[0].indexOf(quoteChar);
    const valueStart = quoteOpen + 1;
    const valueEnd = valueStart + value.length;
    out.push({ key, value, valueStart, valueEnd });
  }
  return out;
}
