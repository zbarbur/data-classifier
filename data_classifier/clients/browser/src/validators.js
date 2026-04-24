// Credential-touching validators ported from data_classifier/engines/validators.py.
// v1 ports: aws_secret_not_hex (line 247), random_password (line 487),
// not_placeholder_credential (line 470).
// Other validators (luhn, bitcoin_address, etc.) load as stubs that always return true;
// the generator emits a warning enumerating stubbed patterns so the gap is visible.

export function awsSecretNotHex(value) {
  const clean = value.trim();
  if (/^[0-9a-fA-F]+$/.test(clean)) return false;
  let hasUpper = false;
  let hasLower = false;
  for (const ch of clean) {
    if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= 'a' && ch <= 'z') hasLower = true;
  }
  return hasUpper && hasLower;
}

export function randomPassword(value) {
  if (value.length < 4 || value.length > 64) return false;
  let hasLower = false;
  let hasUpper = false;
  let hasDigit = false;
  let hasSymbol = false;
  for (const ch of value) {
    if (ch >= 'a' && ch <= 'z') hasLower = true;
    else if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= '0' && ch <= '9') hasDigit = true;
    else if (!/\s/.test(ch)) hasSymbol = true;
  }
  if (!hasSymbol) return false;
  const classes = +hasLower + +hasUpper + +hasDigit + +hasSymbol;
  return classes >= 3;
}

const _PLACEHOLDER_X_RE = /[xX]{5,}/;
const _PLACEHOLDER_CHAR_RE = /(.)\1{7,}/;
const _PLACEHOLDER_TEMPLATE_RE = /(?:^|[=:\s"'])(?:your[_\-\s]|my[_\-\s]|insert[_\-\s]|put[_\-\s]|replace[_\-\s]|add[_\-\s]|enter[_\-\s])/i;

export function makeNotPlaceholderCredential(placeholderSet) {
  return function notPlaceholderCredential(value) {
    const clean = value.trim().toLowerCase();
    if (placeholderSet.has(clean)) return false;
    if (_PLACEHOLDER_X_RE.test(value)) return false;
    if (_PLACEHOLDER_CHAR_RE.test(value)) return false;
    if (_PLACEHOLDER_TEMPLATE_RE.test(value)) return false;
    return true;
  };
}

const _CAMEL_CASE_RE = /[a-z][A-Z]/;

export function huggingfaceToken(value) {
  const suffix = value.startsWith('hf_') ? value.slice(3) : value;
  const hasCamel = _CAMEL_CASE_RE.test(suffix);
  const hasDigit = /[0-9]/.test(suffix);
  // camelCase + no digits + long/non-alnum = code identifier (Objective-C method names)
  // but short purely-alphanumeric suffixes (≤40 chars) are likely real tokens
  if (hasCamel && !hasDigit && (suffix.length > 40 || !/^[a-zA-Z0-9]+$/.test(suffix))) return false;
  return true;
}

const PORTED = {
  aws_secret_not_hex: awsSecretNotHex,
  random_password: randomPassword,
  huggingface_token: huggingfaceToken,
};

function makeStub() {
  const fn = (_value) => true;
  fn.isStub = true;
  return fn;
}

export function resolveValidator(name, { notPlaceholderCredential } = {}) {
  if (!name) return (_v) => true;
  if (name === 'not_placeholder_credential') {
    return notPlaceholderCredential || makeStub();
  }
  const fn = PORTED[name];
  if (fn) return fn;
  return makeStub();
}
