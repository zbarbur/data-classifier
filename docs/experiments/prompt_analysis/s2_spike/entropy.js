// Shannon entropy of a string, in bits per symbol.
// Mirrors data_classifier/engines/secret_scanner.py shannon_entropy().
export function shannonEntropy(s) {
  if (!s) return 0;
  const counts = new Map();
  for (const c of s) counts.set(c, (counts.get(c) || 0) + 1);
  const n = s.length;
  let h = 0;
  for (const c of counts.values()) {
    const p = c / n;
    h -= p * Math.log2(p);
  }
  return h;
}
