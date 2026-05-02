"""Source-diverse NEGATIVE corpus generators.

Sprint 17 item ``source-diverse-negative-corpus-for-benchmark``: expand
the NEGATIVE pool from 90 SecretBench values (homogeneous) to 5
structurally-distinct sources with 500 values each (~2,500 total) so the
binary-PII / NEGATIVE-F1 metric reflects real FP-resistance rather than
corpus homogeneity. See Sprint 14's binary-PII-gate RED verdict for
context.

The five sources are:

* ``config`` — config-shaped strings without secrets (env vars, JSON
  config, INI lines, YAML pairs).
* ``code`` — short code snippets without PII (function signatures,
  imports, simple statements).
* ``business`` — generic business data (product codes, catch phrases,
  buzzwords, color names) via Faker (MIT) plus synthesized SKUs.
* ``numeric`` — non-PII numeric values with units (measurements, scores,
  counts, plain numbers).
* ``prose`` — short prose snippets without PII (synthesized
  documentation-style sentences).

Each value carries a ``source`` metadata tag so the contamination test
can identify which source leaked if the regex engine fires on it.

Provenance and license posture: ``docs/research/negative_corpus_sources.md``.
"""

from __future__ import annotations

import logging
import random

from faker import Faker

logger = logging.getLogger(__name__)

#: Version stamp for the synthesized corpus. Bump when generation logic
#: changes meaningfully so downstream caches/baselines invalidate.
NEGATIVE_CORPUS_VERSION = "v1.0-sprint17"

#: Default per-source sample size. The Sprint 17 spec requires >=100;
#: we ship 500 for stronger statistical power on FP-resistance metrics.
DEFAULT_VALUES_PER_SOURCE = 500

#: Default seed for deterministic generation. Tests pin this seed so
#: regressions show up as test failures, not flaky behavior.
DEFAULT_SEED = 20260428

NEGATIVE_SOURCE_IDS: tuple[str, ...] = ("config", "code", "business", "numeric", "prose")


def _generate_config(n: int, seed: int) -> list[str]:
    """Source A: config-shaped strings, no secrets.

    Mixes four config dialects (env-var, JSON, INI, YAML) with neutral
    keys (PORT, DEBUG, LOG_LEVEL, ...) and bounded numeric/boolean values.
    """
    rng = random.Random(seed)
    keys = [
        "PORT",
        "DEBUG",
        "MAX_CONNECTIONS",
        "LOG_LEVEL",
        "TIMEOUT_SECS",
        "RETRY_COUNT",
        "BUFFER_SIZE",
        "WORKER_THREADS",
        "BATCH_SIZE",
        "ENABLE_TRACING",
        "USE_HTTPS",
        "POOL_SIZE",
        "TIER",
        "SHARD_COUNT",
        "CACHE_TTL",
        "MAX_PAYLOAD_BYTES",
        "FLUSH_INTERVAL_MS",
        "VERBOSITY",
        "READONLY",
        "STRICT_MODE",
        "AUTO_RECONNECT",
        "PIPELINE_DEPTH",
    ]
    log_levels = ["debug", "info", "warn", "error", "trace"]
    tiers = ["free", "basic", "pro", "enterprise", "internal"]
    bools = ["true", "false"]
    out: list[str] = []
    for _ in range(n):
        key = rng.choice(keys)
        # Pick a value type appropriate to the key.
        if "LEVEL" in key:
            val: str | int | bool = rng.choice(log_levels)
        elif "TIER" in key:
            val = rng.choice(tiers)
        elif key.startswith(("DEBUG", "ENABLE_", "USE_", "READONLY", "STRICT_", "AUTO_")):
            val = rng.choice(bools)
        else:
            val = rng.randint(1, 100000)
        dialect = rng.choice(("env", "json", "ini", "yaml"))
        if dialect == "env":
            out.append(f"{key}={val}")
        elif dialect == "json":
            if isinstance(val, str) and val not in bools:
                json_val = f'"{val}"'
            elif val in bools:
                json_val = str(val).lower()
            else:
                json_val = str(val)
            out.append(f'{{"{key.lower()}": {json_val}}}')
        elif dialect == "ini":
            out.append(f"{key.lower()} = {val}")
        else:  # yaml
            out.append(f"{key.lower()}: {val}")
    return out


def _generate_code(n: int, seed: int) -> list[str]:
    """Source B: code snippets without PII.

    Synthesized from templates rather than scraped from real source
    files — eliminates the risk of leaked author names, company names in
    headers, or copyrighted strings. Each kind is parameterized over
    multiple lexical slots so the combinatorial space comfortably
    exceeds 500 unique outputs.
    """
    rng = random.Random(seed)
    func_names = [
        "compute",
        "process",
        "validate",
        "normalize",
        "serialize",
        "deserialize",
        "transform",
        "filter_items",
        "build_response",
        "parse_input",
        "render",
        "encode",
        "decode",
        "merge",
        "split",
        "chunk",
        "flatten",
        "deduplicate",
        "sort_by_priority",
        "estimate",
    ]
    arg_names = ["data", "value", "items", "config", "request", "payload", "buffer", "context", "node", "graph"]
    type_hints = ["int", "str", "bytes", "list[int]", "dict[str, Any]", "bool", "float", "Optional[str]", "set[int]"]
    modules = [
        "json",
        "os",
        "sys",
        "logging",
        "re",
        "asyncio",
        "math",
        "random",
        "functools",
        "itertools",
        "operator",
        "hashlib",
    ]
    from_modules = [
        ("pathlib", ["Path", "PurePath"]),
        ("typing", ["Optional", "Any", "Callable", "TypeVar", "Iterable"]),
        ("collections", ["defaultdict", "Counter", "deque", "OrderedDict"]),
        ("dataclasses", ["dataclass", "field", "asdict"]),
        ("contextlib", ["contextmanager", "suppress", "ExitStack"]),
        ("functools", ["lru_cache", "partial", "reduce", "wraps"]),
    ]
    decorators_simple = ["@property", "@staticmethod", "@classmethod", "@cached_property", "@dataclass"]
    decorators_param = [
        ("@lru_cache", "maxsize"),
        ("@retry", "attempts"),
        ("@timeout", "seconds"),
    ]
    stmt_templates = [
        "return {arg}",
        "return {arg}.strip()",
        "{arg} = []",
        "{arg} = {{}}",
        "{arg} += 1",
        "{arg}.append({other})",
        "if not {arg}: return None",
        'if {arg} is None: raise ValueError("missing")',
        "for item in {arg}: yield item",
        "with open(path) as f: contents = f.read()",
        "{arg}.update({other})",
        'raise NotImplementedError("todo")',
        'logger.debug("step complete")',
        "{arg} = {arg} or default",
        "return [x for x in {arg} if x]",
        "return {{k: v for k, v in {arg}.items() if v}}",
        'assert {arg}, "precondition failed"',
    ]
    out: list[str] = []
    for _ in range(n):
        kind = rng.choice(("def", "import", "from-import", "stmt", "decorator", "decorator-param", "lambda"))
        if kind == "def":
            fn = rng.choice(func_names)
            arg = rng.choice(arg_names)
            t_in = rng.choice(type_hints)
            t_out = rng.choice(type_hints)
            out.append(f"def {fn}({arg}: {t_in}) -> {t_out}:")
        elif kind == "import":
            out.append(f"import {rng.choice(modules)}")
        elif kind == "from-import":
            mod, syms = rng.choice(from_modules)
            sym_count = rng.randint(1, min(3, len(syms)))
            chosen = rng.sample(syms, k=sym_count)
            out.append(f"from {mod} import {', '.join(chosen)}")
        elif kind == "stmt":
            tpl = rng.choice(stmt_templates)
            arg = rng.choice(arg_names)
            other = rng.choice([a for a in arg_names if a != arg])
            out.append(tpl.format(arg=arg, other=other))
        elif kind == "decorator":
            out.append(rng.choice(decorators_simple))
        elif kind == "decorator-param":
            dec, kw = rng.choice(decorators_param)
            out.append(f"{dec}({kw}={rng.randint(1, 100)})")
        else:  # lambda
            arg = rng.choice(arg_names)
            method = rng.choice(("strip", "lower", "upper", "split", "title", "lstrip", "rstrip"))
            out.append(f"lambda {arg}: {arg}.{method}()")
    return out


def _generate_business(n: int, seed: int) -> list[str]:
    """Source C: generic business data — product codes, catch phrases.

    Faker's ``catch_phrase`` + ``bs`` produce buzzword-style strings with
    no PII shape. ``color_name`` is included for short single-word
    samples. SKUs/product codes are synthesized with neutral prefixes
    (no real company names).

    Notably AVOIDED: ``fake.company()`` (generates names like
    "Adams, Howard and Brown" that fire on PERSON_NAME); ``fake.name()``
    (literal person names).
    """
    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed + 1)
    out: list[str] = []
    # 4 buckets, ~125 each.
    for _ in range(n // 4):
        out.append(fake.catch_phrase())
    for _ in range(n // 4):
        out.append(fake.bs())
    for _ in range(n // 4):
        out.append(fake.color_name())
    while len(out) < n:
        prefix = rng.choice(("PROD", "SKU", "ITEM", "ORD", "CAT", "MFG", "REF"))
        suffix = "".join(rng.choices("ABCDEFGHIJKLMNPQRSTUVWXYZ23456789", k=rng.randint(5, 9)))
        out.append(f"{prefix}-{suffix}")
    return out[:n]


def _generate_numeric(n: int, seed: int) -> list[str]:
    """Source D: numeric non-PII values with units.

    Avoids 9-15 digit sequences (would collide with SSN/CC/phone shapes)
    by capping integer values at 6 digits and always pairing with a unit
    or context word.
    """
    rng = random.Random(seed)
    units = ["kg", "lb", "m", "ft", "mph", "kph", "°C", "°F", "Pa", "kPa", "Hz", "kHz"]
    out: list[str] = []
    per_kind = n // 5
    # Measurements with units.
    for _ in range(per_kind):
        v = rng.randint(1, 999999)
        u = rng.choice(units)
        if rng.random() < 0.3:
            v_float = round(v + rng.random(), rng.randint(1, 3))
            out.append(f"{v_float} {u}")
        else:
            out.append(f"{v} {u}")
    # Scores.
    for _ in range(per_kind):
        score = round(rng.uniform(0, 100), 2)
        out.append(f"score: {score}")
    # Counts.
    for _ in range(per_kind):
        cnt = rng.randint(1, 99999)
        out.append(f"count = {cnt}")
    # Ratings (small-denominator fractions).
    for _ in range(per_kind):
        num = round(rng.uniform(0, 5), 1)
        out.append(f"rating: {num}/5")
    # Plain numbers (with magnitude variation, but capped).
    while len(out) < n:
        kind = rng.choice(("int", "float", "scientific"))
        if kind == "int":
            out.append(str(rng.randint(0, 999999)))
        elif kind == "float":
            out.append(str(round(rng.uniform(0, 9999), rng.randint(1, 4))))
        else:
            mantissa = round(rng.uniform(1, 10), 2)
            exp = rng.choice((-10, -5, -2, 2, 5, 10))
            out.append(f"{mantissa}e{exp}")
    return out[:n]


def _generate_prose(n: int, seed: int) -> list[str]:
    """Source E: documentation-style prose without PII.

    Synthesized sentence templates with a neutral vocabulary — no person
    names, addresses, dates, or other PII shapes. The point is to give
    the detector long-form text where every shape it might fire on is
    actually a generic word.
    """
    rng = random.Random(seed)
    subjects = [
        "The system",
        "This module",
        "The function",
        "A request",
        "The handler",
        "Each consumer",
        "The pipeline",
        "An incoming event",
        "The validator",
        "A worker",
    ]
    verbs = [
        "processes",
        "validates",
        "parses",
        "transforms",
        "filters",
        "normalizes",
        "encodes",
        "decodes",
        "queues",
        "discards",
    ]
    objects = [
        "the input payload",
        "the configuration block",
        "the response body",
        "the staging buffer",
        "the routing table",
        "the retry queue",
        "the cache invalidation set",
        "the schema descriptor",
        "the build manifest",
        "the dependency graph",
    ]
    qualifiers = [
        "before forwarding it downstream.",
        "and emits a structured event.",
        "according to the configured policy.",
        "without blocking the caller.",
        "and updates the local cache.",
        "in deterministic order.",
        "with bounded retry attempts.",
        "while preserving invariants.",
        "and logs a debug breadcrumb.",
        "on each invocation.",
    ]
    out: list[str] = []
    for _ in range(n):
        s = rng.choice(subjects)
        v = rng.choice(verbs)
        o = rng.choice(objects)
        q = rng.choice(qualifiers)
        out.append(f"{s} {v} {o} {q}")
    return out


_SOURCE_GENERATORS = {
    "config": _generate_config,
    "code": _generate_code,
    "business": _generate_business,
    "numeric": _generate_numeric,
    "prose": _generate_prose,
}


def load_diverse_negative_corpus(
    *,
    values_per_source: int = DEFAULT_VALUES_PER_SOURCE,
    seed: int = DEFAULT_SEED,
    sources: tuple[str, ...] = NEGATIVE_SOURCE_IDS,
) -> dict[str, list[str]]:
    """Generate the diverse NEGATIVE corpus.

    Returns ``{source_id: [values]}`` so callers can route values per
    source for contamination diagnostics. Use
    :func:`flatten_negative_corpus` to flatten when a single list is
    needed.

    The seed is applied per-source with a small offset so altering one
    generator's value count doesn't cascade into other generators'
    output (each generator gets a stable RNG stream).
    """
    out: dict[str, list[str]] = {}
    for i, source in enumerate(sources):
        if source not in _SOURCE_GENERATORS:
            raise ValueError(f"Unknown NEGATIVE source: {source!r}; valid: {NEGATIVE_SOURCE_IDS}")
        out[source] = _SOURCE_GENERATORS[source](values_per_source, seed + i)
    return out


def flatten_negative_corpus(corpus: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Flatten ``{source: [values]}`` into ``[(source, value), ...]``.

    Preserves source provenance per value, which the contamination test
    uses to attribute leaks back to a specific generator.
    """
    return [(source, value) for source, values in corpus.items() for value in values]
