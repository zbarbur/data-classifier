// GENERATED - do not edit. Run: npm run generate
export const PYTHON_LOGIC_VERSION = "532b032fea26de61";

export const PYTHON_LOGIC_FILE_HASHES = {
  "engine_defaults.yaml": "a713f4fcdac41035",
  "heuristic_engine.py": "a0abc2e0c91110cf",
  "parsers.py": "58bbce7a7c514566",
  "regex_engine.py": "02c7c19a66072343",
  "secret_scanner.py": "8377eedf95450602",
  "validators.py": "42b2901a97775b8e"
};

export const SECRET_SCANNER = {
  minValueLength: 8,
  antiIndicators: ["example", "test", "placeholder", "changeme"],
  configValues: ["debug", "development", "disabled", "enabled", "error", "false", "info", "no", "none", "null", "off", "on", "production", "staging", "test", "trace", "true", "warn", "yes"],
  definitiveMultiplier: 0.95,
  strongMinEntropyScore: 0.6,
  relativeEntropyStrong: 0.5,
  relativeEntropyContextual: 0.7,
  diversityThreshold: 3,
  proseAlphaThreshold: 0.6,
  tierBoundaryDefinitive: 0.9,
  tierBoundaryStrong: 0.7,
  placeholderPatterns: [{"pattern": "x{5,}", "flags": "i"}, {"pattern": "(.)\\1{7,}", "flags": ""}, {"pattern": "<[^>]{1,80}>", "flags": ""}, {"pattern": "^\\[[A-Z_]{2,}\\]$", "flags": ""}, {"pattern": "your[_\\-\\s][\\w\\-\\s]{0,30}(key|token|secret|password|credential)\\b", "flags": "i"}, {"pattern": "put[_\\-\\s]?your", "flags": "i"}, {"pattern": "insert[_\\-\\s]?your", "flags": "i"}, {"pattern": "replace[_\\-\\s]?(me|with|this)", "flags": "i"}, {"pattern": "placeholder", "flags": "i"}, {"pattern": "redacted", "flags": "i"}, {"pattern": "\\bexample\\b", "flags": "i"}, {"pattern": "^sample[_\\-]", "flags": "i"}, {"pattern": "^dummy[_\\-]?", "flags": "i"}, {"pattern": "\\{\\{.*\\}\\}", "flags": ""}, {"pattern": "\\$\\{[A-Z_]+\\}", "flags": ""}, {"pattern": "EXAMPLE$", "flags": ""}, {"pattern": "(key|token|secret|password)[_\\-\\s]here", "flags": "i"}, {"pattern": "goes[_\\-\\s]here", "flags": "i"}, {"pattern": "\\bchangeme\\b", "flags": "i"}, {"pattern": "\\bfoobar\\b", "flags": "i"}, {"pattern": "\\btodo\\b", "flags": "i"}, {"pattern": "\\bfixme\\b", "flags": "i"}, {"pattern": "abcdefghij|bcdefghijk|cdefghijkl|defghijklm|efghijklmn|fghijklmno|ghijklmnop|hijklmnopq|ijklmnopqr|jklmnopqrs|klmnopqrst|lmnopqrstu|mnopqrstuv|nopqrstuvw|opqrstuvwx|pqrstuvwxy|qrstuvwxyz", "flags": "i"}],
  urlLikePattern: {"pattern": "^https?://", "flags": "i"},
  dateLikePattern: {"pattern": "^\\d{4}[-/]\\d{2}[-/]\\d{2}", "flags": ""},
  nonSecretSuffixes: ["_address", "_count", "_dir", "_endpoint", "_field", "_file", "_format", "_id", "_input", "_label", "_length", "_mode", "_name", "_path", "_placeholder", "_prefix", "_size", "_status", "_suffix", "_type", "_url"],
  nonSecretAllowlist: ["auth_id", "client_id", "session_id"],
  ipLikePattern: {"pattern": "^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}$", "flags": ""},
  numericOnlyPattern: {"pattern": "^[\\d\\s.,+-]+$", "flags": ""},
  uuidPattern: {"pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "flags": "i"},
  opaqueTokenMinLength: 16,
  opaqueTokenEntropyThreshold: 0.7,
  opaqueTokenDiversityThreshold: 3,
  opaqueTokenBaseConfidence: 0.65,
  opaqueTokenMaxConfidence: 0.85,
};
