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

export function makeNotPlaceholderCredential(placeholderSet) {
  return function notPlaceholderCredential(value) {
    const clean = value.trim().toLowerCase();
    return !placeholderSet.has(clean);
  };
}

const PORTED = {
  aws_secret_not_hex: awsSecretNotHex,
  random_password: randomPassword,
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
