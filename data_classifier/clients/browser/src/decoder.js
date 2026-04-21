// Mirror of data_classifier/patterns/_decoder.py — decodes xor:/b64: prefixes.

const XOR_KEY = 0x5a;

function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out;
}

// Uses TextDecoder default error mode ('replace'), which substitutes U+FFFD
// on malformed UTF-8. Python's .decode('utf-8') is strict by default.
// All encoded values in default_patterns.json are ASCII credentials, so the
// difference is dormant — but the caller must not pass non-ASCII bytes here
// if Python-parity error semantics matter.
function bytesToUtf8(bytes) {
  return new TextDecoder('utf-8').decode(bytes);
}

export function decodeEncodedStrings(values) {
  const out = [];
  for (const v of values) {
    if (v.startsWith('xor:')) {
      const bytes = base64ToBytes(v.slice(4));
      for (let i = 0; i < bytes.length; i++) bytes[i] ^= XOR_KEY;
      out.push(bytesToUtf8(bytes));
    } else if (v.startsWith('b64:')) {
      out.push(bytesToUtf8(base64ToBytes(v.slice(4))));
    } else {
      out.push(v);
    }
  }
  return out;
}
