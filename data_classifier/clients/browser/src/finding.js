// Shared helpers for building Finding objects that match the shape in the
// design doc. Keeping this in its own module lets unit tests avoid
// hand-building findings (which is brittle and drifts from the spec).

export function maskValue(value, entityType) {
  if (value.length <= 4) return '*'.repeat(value.length);
  if (entityType === 'EMAIL') {
    const at = value.indexOf('@');
    if (at > 1) return value[0] + '*'.repeat(at - 1) + value.slice(at);
  }
  return value[0] + '*'.repeat(value.length - 2) + value[value.length - 1];
}

export function makeFinding({
  entityType,
  category,
  sensitivity,
  confidence,
  engine,
  evidence,
  match,
  kv,
  details,
}) {
  const f = { entity_type: entityType, category, sensitivity, confidence, engine, evidence, match };
  if (kv) f.kv = kv;
  if (details) f.details = details;
  return f;
}
