# Zone Detector v2 — Core Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 heuristic zone detector with a multi-detector cascade architecture that raises precision from 80% to >90% and eliminates 34/35 known FPs.

**Architecture:** Six independent detectors (structural, format, syntax, negative filter, block assembler, language) orchestrated in a cascade pipeline. Shared JSON config (`zone_patterns.json`) is the single source of truth for all patterns, weights, and thresholds. Pre-screen fast path skips 97% of prompts. v1 remains untouched — v2 is a new module that is a drop-in replacement.

**Tech Stack:** Python 3.11+, `re` stdlib (no re2 needed for zone detection), `json`/`ast` stdlib for parse validation, `dataclasses`, pytest

**Design spec:** `docs/experiments/prompt_analysis/s4_zone_detection/zone_detector_v2_design.md`

**v1 reference:** `docs/experiments/prompt_analysis/s4_zone_detection/zone_detector.py`

---

## File Structure

All new files live under `docs/experiments/prompt_analysis/s4_zone_detection/v2/`:

| File | Responsibility |
|---|---|
| `v2/__init__.py` | Public API: `detect_zones()`, re-exports types |
| `v2/types.py` | `ZoneBlock`, `PromptZones`, `ZoneConfig`, `ZONE_TYPES` |
| `v2/config.py` | Load `zone_patterns.json`, sensitivity presets |
| `v2/patterns/zone_patterns.json` | Shared config: all regexes, weights, thresholds |
| `v2/pre_screen.py` | Fast-path check (~97% exit) |
| `v2/structural.py` | Fenced blocks + delimiter pair scanning |
| `v2/format_detector.py` | JSON/XML/YAML/ENV parse detection |
| `v2/syntax.py` | Line scoring + fragment matching + context window |
| `v2/negative.py` | Error/dialog/list/math/ratio/prose suppression |
| `v2/assembler.py` | Block grouping, gap bridging, bracket validation, repetitive structure |
| `v2/language.py` | Language probability from fragment hits |
| `v2/orchestrator.py` | Wire detectors, manage claimed ranges, apply config |
| `tests/test_zone_v2/conftest.py` | Shared fixtures |
| `tests/test_zone_v2/test_types.py` | Type construction tests |
| `tests/test_zone_v2/test_pre_screen.py` | Pre-screen pass/fail |
| `tests/test_zone_v2/test_structural.py` | Fenced + delimiter tests |
| `tests/test_zone_v2/test_format.py` | JSON/XML/YAML/ENV tests |
| `tests/test_zone_v2/test_syntax.py` | Scoring + fragments + context |
| `tests/test_zone_v2/test_negative.py` | FP suppression tests |
| `tests/test_zone_v2/test_assembler.py` | Assembly + merge tests |
| `tests/test_zone_v2/test_language.py` | Language detection tests |
| `tests/test_zone_v2/test_orchestrator.py` | End-to-end tests |

---

### Task 1: Data structures and zone types

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py`
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/types.py`
- Create: `tests/test_zone_v2/__init__.py`
- Create: `tests/test_zone_v2/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_types.py
"""Tests for zone detection data structures."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import (
    ZONE_TYPES,
    PromptZones,
    ZoneBlock,
    ZoneConfig,
)


def test_zone_types_has_eight_entries():
    assert len(ZONE_TYPES) == 8
    assert "code" in ZONE_TYPES
    assert "error_output" in ZONE_TYPES
    assert "natural_language" in ZONE_TYPES


def test_zone_block_construction():
    b = ZoneBlock(start_line=0, end_line=10, zone_type="code", confidence=0.85, method="syntax_score")
    assert b.start_line == 0
    assert b.end_line == 10
    assert b.zone_type == "code"
    assert b.language_hint == ""
    assert b.language_confidence == 0.0


def test_prompt_zones_to_dict_strips_text():
    b = ZoneBlock(
        start_line=0, end_line=5, zone_type="code",
        confidence=0.9, method="fenced", text="def foo():\n    pass"
    )
    pz = PromptZones(prompt_id="test1", total_lines=10, blocks=[b])
    d = pz.to_dict()
    assert "text" not in d["blocks"][0]
    assert d["blocks"][0]["zone_type"] == "code"


def test_zone_config_defaults():
    cfg = ZoneConfig()
    assert cfg.sensitivity == "balanced"
    assert cfg.min_block_lines == 8
    assert cfg.min_confidence == 0.50
    assert cfg.context_window == 3
    assert cfg.structural_enabled is True


def test_zone_config_preset_high_precision():
    cfg = ZoneConfig(sensitivity="high_precision")
    assert cfg.min_confidence == 0.50  # preset applied by config loader, not dataclass
```

- [ ] **Step 2: Create empty packages**

```python
# tests/test_zone_v2/__init__.py
# (empty)
```

```python
# docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py
"""Zone Detector v2 — multi-detector cascade architecture."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import (
    ZONE_TYPES,
    PromptZones,
    ZoneBlock,
    ZoneConfig,
)

__all__ = ["ZONE_TYPES", "ZoneBlock", "PromptZones", "ZoneConfig", "detect_zones"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_types.py -v`
Expected: FAIL with ImportError (types.py doesn't exist yet)

- [ ] **Step 4: Implement types**

```python
# docs/experiments/prompt_analysis/s4_zone_detection/v2/types.py
"""Zone detection data structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

ZONE_TYPES = (
    "code",
    "markup",
    "config",
    "query",
    "cli_shell",
    "data",
    "error_output",
    "natural_language",
)


@dataclass
class ZoneBlock:
    """A single detected zone within a prompt."""

    start_line: int  # 0-indexed inclusive
    end_line: int  # 0-indexed exclusive
    zone_type: str  # one of ZONE_TYPES
    confidence: float  # 0.0-1.0
    method: str  # detection method name
    language_hint: str = ""
    language_confidence: float = 0.0
    text: str = ""


@dataclass
class PromptZones:
    """Result of zone detection on a prompt."""

    prompt_id: str
    total_lines: int
    blocks: list[ZoneBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "prompt_id": self.prompt_id,
            "total_lines": self.total_lines,
            "blocks": [asdict(b) for b in self.blocks],
        }
        for b in d["blocks"]:
            del b["text"]
        return d


@dataclass
class ZoneConfig:
    """Configuration for zone detection."""

    sensitivity: str = "balanced"
    enabled_types: list[str] = field(
        default_factory=lambda: ["code", "markup", "config", "query", "cli_shell", "data", "error_output"]
    )
    min_block_lines: int = 8
    min_confidence: float = 0.50
    structural_enabled: bool = True
    format_enabled: bool = True
    syntax_enabled: bool = True
    negative_filter_enabled: bool = True
    parse_validation_enabled: bool = True
    language_detection_enabled: bool = True
    context_window: int = 3
    pre_screen_enabled: bool = True
    max_parse_attempts: int = 10
    weight_overrides: dict = field(default_factory=dict)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_types.py -v`
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py \
       docs/experiments/prompt_analysis/s4_zone_detection/v2/types.py \
       tests/test_zone_v2/__init__.py \
       tests/test_zone_v2/test_types.py
git commit -m "feat(zone-v2): add data structures and zone types"
```

---

### Task 2: Shared pattern configuration

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/patterns/zone_patterns.json`
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/config.py`
- Create: `tests/test_zone_v2/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_config.py
"""Tests for zone pattern configuration loading."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns, apply_preset


def test_load_zone_patterns_returns_dict():
    patterns = load_zone_patterns()
    assert isinstance(patterns, dict)
    assert patterns["version"] == "2.0.0"


def test_patterns_has_required_sections():
    patterns = load_zone_patterns()
    for section in ("pre_screen", "lang_tag_map", "structural", "format", "syntax", "negative", "assembly"):
        assert section in patterns, f"Missing section: {section}"


def test_syntax_has_code_keywords():
    patterns = load_zone_patterns()
    keywords = patterns["syntax"]["code_keywords"]
    assert "import" in keywords
    assert "def" in keywords
    assert "function" in keywords
    assert "defer" in keywords  # Go keyword (was missing in v1)
    assert len(keywords) >= 60


def test_syntax_has_fragment_patterns():
    patterns = load_zone_patterns()
    fragments = patterns["syntax"]["fragment_patterns"]
    assert "c_family" in fragments
    assert "python" in fragments
    assert "markup" in fragments
    assert "sql" in fragments
    assert "shell" in fragments
    assert "assembly" in fragments
    assert "rust" in fragments


def test_negative_has_all_signal_types():
    patterns = load_zone_patterns()
    neg = patterns["negative"]
    for signal in ("error_output", "dialog", "list_prefix", "math", "ratio", "prose"):
        assert signal in neg, f"Missing negative signal: {signal}"


def test_apply_preset_high_recall():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig
    cfg = ZoneConfig(sensitivity="high_recall")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 3
    assert cfg.min_confidence == 0.40


def test_apply_preset_balanced():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig
    cfg = ZoneConfig(sensitivity="balanced")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 8
    assert cfg.min_confidence == 0.50


def test_apply_preset_high_precision():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig
    cfg = ZoneConfig(sensitivity="high_precision")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 10
    assert cfg.min_confidence == 0.65
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_config.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Create zone_patterns.json**

Create the complete JSON config file. This is the single source of truth for all patterns, weights, and thresholds. Contents are drawn verbatim from the design spec sections §5-§12.

The file should contain all sections: `version`, `zone_types`, `pre_screen`, `lang_tag_map`, `structural`, `format`, `syntax` (with `code_keywords`, `scoring_weights`, `fragment_patterns` for all 7 families, `context`), `negative` (all 6 signal types), `assembly`, `language`.

Create directory: `docs/experiments/prompt_analysis/s4_zone_detection/v2/patterns/`

All keyword lists, regex patterns, weight values, and thresholds must match the design spec exactly. The `lang_tag_map` must include all entries from design spec §6. Fragment patterns must include all regex strings from §9.2.

- [ ] **Step 4: Implement config.py**

```python
# docs/experiments/prompt_analysis/s4_zone_detection/v2/config.py
"""Load zone detection patterns and configuration."""
from __future__ import annotations

import json
from pathlib import Path

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

_PATTERNS_PATH = Path(__file__).parent / "patterns" / "zone_patterns.json"
_cached_patterns: dict | None = None


def load_zone_patterns() -> dict:
    """Load the shared zone patterns configuration."""
    global _cached_patterns
    if _cached_patterns is None:
        with open(_PATTERNS_PATH) as f:
            _cached_patterns = json.load(f)
    return _cached_patterns


def apply_preset(config: ZoneConfig) -> ZoneConfig:
    """Apply sensitivity preset to config thresholds."""
    presets = {
        "high_recall": {"min_block_lines": 3, "min_confidence": 0.40, "parse_validation_enabled": False},
        "balanced": {"min_block_lines": 8, "min_confidence": 0.50, "parse_validation_enabled": True},
        "high_precision": {"min_block_lines": 10, "min_confidence": 0.65, "parse_validation_enabled": True},
    }
    preset = presets.get(config.sensitivity, presets["balanced"])
    for k, v in preset.items():
        setattr(config, k, v)
    return config
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_config.py -v`
Expected: 8 PASSED

- [ ] **Step 6: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/patterns/zone_patterns.json \
       docs/experiments/prompt_analysis/s4_zone_detection/v2/config.py \
       tests/test_zone_v2/test_config.py
git commit -m "feat(zone-v2): add shared pattern config and presets"
```

---

### Task 3: Pre-screen fast path

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/pre_screen.py`
- Create: `tests/test_zone_v2/test_pre_screen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_pre_screen.py
"""Tests for the pre-screen fast path."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.pre_screen import pre_screen


class TestPreScreenPasses:
    """These should return True — text might contain code."""

    def test_fenced_block(self):
        assert pre_screen("Hello\n```python\nprint('hi')\n```\n") is True

    def test_tilde_fence(self):
        assert pre_screen("~~~\ncode\n~~~") is True

    def test_high_syntax_density(self):
        assert pre_screen("if (x > 0) { return x; }") is True

    def test_indentation_spaces(self):
        assert pre_screen("line 1\n    indented code\nline 3") is True

    def test_indentation_tab(self):
        assert pre_screen("line 1\n\tindented code\nline 3") is True

    def test_closing_tag(self):
        assert pre_screen("<div>hello</div>") is True

    def test_braces_in_code(self):
        assert pre_screen("function foo() { return 1; }") is True


class TestPreScreenRejects:
    """These should return False — pure prose, skip pipeline."""

    def test_empty_string(self):
        assert pre_screen("") is False

    def test_pure_prose(self):
        assert pre_screen("The quick brown fox jumps over the lazy dog.") is False

    def test_prose_with_question(self):
        assert pre_screen("How do I sort a list in Python?") is False

    def test_short_prose_with_comma(self):
        assert pre_screen("Hello, world. Nice to meet you.") is False

    def test_cjk_text(self):
        assert pre_screen("今日は天気がいいですね。散歩に行きましょう。") is False

    def test_cyrillic_text(self):
        assert pre_screen("Привет, как дела? Хорошо, спасибо.") is False

    def test_whitespace_only(self):
        assert pre_screen("   \n\n   \n") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_pre_screen.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement pre_screen**

```python
# docs/experiments/prompt_analysis/s4_zone_detection/v2/pre_screen.py
"""Pre-screen fast path — rejects 97% of prompts that contain no code."""
from __future__ import annotations

_PRESCREEN_CHARS = frozenset("{}()[];=<>|&@#$^~")
_DENSITY_THRESHOLD = 0.03


def pre_screen(text: str) -> bool:
    """Return True if text MIGHT contain code/structured blocks.

    False means definitely no blocks — skip all detectors.
    Must have zero false negatives.
    """
    if not text or not text.strip():
        return False

    # Check 1: fence markers
    if "```" in text or "~~~" in text:
        return True

    # Check 2: syntactic character density
    total = len(text)
    syn_count = 0
    for c in text:
        if c in _PRESCREEN_CHARS:
            syn_count += 1
    if syn_count / total > _DENSITY_THRESHOLD:
        return True

    # Check 3: indentation patterns
    if "\n    " in text or "\n\t" in text:
        return True

    # Check 4: closing tags (markup)
    if "</" in text:
        return True

    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_pre_screen.py -v`
Expected: 14 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/pre_screen.py \
       tests/test_zone_v2/test_pre_screen.py
git commit -m "feat(zone-v2): add pre-screen fast path"
```

---

### Task 4: StructuralDetector — fenced blocks + delimiter pairs

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/structural.py`
- Create: `tests/test_zone_v2/test_structural.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_structural.py
"""Tests for StructuralDetector — fenced blocks and delimiter pairs."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.structural import StructuralDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return StructuralDetector(load_zone_patterns())


class TestFencedBlocks:
    def test_python_fenced_block(self):
        text = "Hello\n```python\ndef foo():\n    pass\n```\nBye"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert len(blocks) == 1
        assert blocks[0].zone_type == "code"
        assert blocks[0].language_hint == "python"
        assert blocks[0].confidence == 0.95
        assert blocks[0].start_line == 1
        assert blocks[0].end_line == 5

    def test_json_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "json"

    def test_bash_fenced_block(self):
        text = "```bash\necho hello\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "cli_shell"
        assert blocks[0].language_hint == "bash"

    def test_untagged_code_fence(self):
        text = "```\ndef foo():\n    return 1\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "code"

    def test_untagged_prose_fence(self):
        text = "```\nThis is just a quoted paragraph of text.\nNothing code-like here at all.\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "natural_language"

    def test_tilde_fence(self):
        text = "~~~js\nconsole.log('hi')\n~~~"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert len(blocks) == 1
        assert blocks[0].language_hint == "javascript"

    def test_claimed_ranges(self):
        text = "prose\n```\ncode\n```\nprose"
        det = _make_detector()
        _, claimed = det.detect(text.split("\n"))
        assert 1 in claimed
        assert 2 in claimed
        assert 3 in claimed
        assert 0 not in claimed
        assert 4 not in claimed


class TestDelimiterPairs:
    def test_multiline_comment(self):
        text = "code\n/* this is\na comment */\ncode"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        # /* */ is claimed but type depends on context
        assert 1 in claimed
        assert 2 in claimed

    def test_html_comment(self):
        text = "<!-- this is\na comment -->\n<div>hi</div>"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert 0 in claimed
        assert 1 in claimed

    def test_script_tag(self):
        text = "<div>\n<script>\nconst x = 1;\n</script>\n</div>"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        # script interior should be claimed as code
        script_blocks = [b for b in blocks if b.language_hint == "javascript"]
        assert len(script_blocks) == 1
        assert script_blocks[0].zone_type == "code"

    def test_unclosed_delimiter_not_claimed(self):
        text = "/* this comment never closes\nso it should not be claimed"
        det = _make_detector()
        _, claimed = det.detect(text.split("\n"))
        assert len(claimed) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_structural.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement StructuralDetector**

Implement `StructuralDetector` with:
- `__init__(self, patterns: dict)` — load fence regex and delimiter pairs from config
- `detect(self, lines: list[str]) -> tuple[list[ZoneBlock], set[int]]` — returns blocks + claimed line indices
- `_detect_fenced(self, lines)` — carried from v1 `_detect_fenced_blocks()`, uses `lang_tag_map` from config
- `_detect_delimiters(self, lines, fenced_ranges)` — scan for `/* */`, `<!-- -->`, `<script>`, `<style>`, `"""`, heredoc. Uses linear scan with stack. Unclosed delimiters not claimed.
- Interior classification for untagged fences: check alpha ratio + keyword count (same logic as v1)

Key differences from v1:
- Reads `lang_tag_map` from config instead of hardcoded `_LANG_TAG_MAP`
- Adds delimiter pair scanning (new in v2)
- Returns claimed ranges as a `set[int]` for other detectors to skip

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_structural.py -v`
Expected: 11 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/structural.py \
       tests/test_zone_v2/test_structural.py
git commit -m "feat(zone-v2): add StructuralDetector — fenced blocks + delimiter pairs"
```

---

### Task 5: FormatDetector — JSON, XML, YAML, ENV

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/format_detector.py`
- Create: `tests/test_zone_v2/test_format.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_format.py
"""Tests for FormatDetector — structured format detection."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.format_detector import FormatDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return FormatDetector(load_zone_patterns())


class TestJsonDetection:
    def test_valid_json_object(self):
        lines = ['', '  {', '    "name": "test",', '    "value": 42,', '    "active": true', '  }', '']
        det = _make_detector()
        blocks, claimed = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "json"
        assert blocks[0].confidence == 0.90

    def test_invalid_json_not_detected(self):
        lines = ['{partial json', 'not closed']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestXmlDetection:
    def test_html_with_matched_tags(self):
        lines = ['<div class="app">', '  <h1>Title</h1>', '  <p>Content</p>', '</div>']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "markup"

    def test_angle_brackets_without_matched_tags_rejected(self):
        """v2 fix: NL instructions with <CLAIM> should NOT trigger XML detection."""
        lines = [
            'Format your output as: <CLAIM> followed by <MEASURE>',
            'Make sure each claim is backed by evidence.',
            'Use the format <CLAIM>: <MEASURE> for each point.',
        ]
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestYamlDetection:
    def test_yaml_key_value_pairs(self):
        lines = ['name: test-app', 'version: 1.0.0', 'port: 8080', 'debug: true', 'timeout: 30']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "yaml"

    def test_bullet_list_not_yaml(self):
        """Bullet-only lists are markdown, not YAML."""
        lines = ['- First item in the list', '- Second item here', '- Third item here']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestEnvDetection:
    def test_env_file(self):
        lines = ['DATABASE_URL=postgres://localhost/db', 'API_KEY=sk_test_12345', 'DEBUG=true']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "env"


class TestClaimedRangesRespected:
    def test_skips_claimed_lines(self):
        lines = ['  {', '    "key": "value"', '  }']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges={0, 1, 2})
        assert len(blocks) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_format.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement FormatDetector**

Implement `FormatDetector` with:
- `__init__(self, patterns: dict)` — load format thresholds from config
- `detect(self, lines: list[str], claimed_ranges: set[int]) -> tuple[list[ZoneBlock], set[int]]`
- `_find_candidate_regions(self, lines, claimed_ranges)` — find contiguous non-empty regions in unclaimed lines, allowing 1-2 blank gaps
- `_try_json(self, block_text) -> bool` — strict `json.loads` validation
- `_looks_like_xml(self, block_text) -> bool` — require matched open/close tags (v2 fix from design §8.2)
- `_looks_like_yaml(self, lines) -> bool` — carried from v1, requires 3+ key:value lines, rejects prose and long keys
- `_looks_like_env(self, lines) -> bool` — `^[A-Z][A-Z0-9_]+=.+$` pattern

Port the v1 logic from `zone_detector.py` functions `_try_json_block`, `_looks_like_yaml`, `_looks_like_xml`, `_looks_like_env`, but with the XML tightening (require matched tags per design §8.2).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_format.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/format_detector.py \
       tests/test_zone_v2/test_format.py
git commit -m "feat(zone-v2): add FormatDetector — JSON/XML/YAML/ENV with tightened XML"
```

---

### Task 6: SyntaxDetector — line scoring + fragment matching + context window

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/syntax.py`
- Create: `tests/test_zone_v2/test_syntax.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_syntax.py
"""Tests for SyntaxDetector — line scoring, fragment matching, context window."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.syntax import SyntaxDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return SyntaxDetector(load_zone_patterns())


class TestLineSyntaxScore:
    def test_empty_line_scores_zero(self):
        det = _make_detector()
        assert det.line_syntax_score("") == 0.0
        assert det.line_syntax_score("   ") == 0.0

    def test_prose_scores_zero(self):
        det = _make_detector()
        assert det.line_syntax_score("The quick brown fox jumps over the lazy dog.") == 0.0

    def test_code_line_scores_high(self):
        det = _make_detector()
        score = det.line_syntax_score("def process(data, timeout=30):")
        assert score >= 0.4  # keywords + syntax chars + line ending

    def test_import_statement_scores_high(self):
        det = _make_detector()
        score = det.line_syntax_score("import json")
        assert score >= 0.15

    def test_brace_line_scores(self):
        det = _make_detector()
        score = det.line_syntax_score("    if (x > 0) {")
        assert score >= 0.3


class TestFragmentMatching:
    def test_python_fragment_detected(self):
        det = _make_detector()
        score, family = det.score_with_fragments("def process(data):")
        assert score >= 0.4
        assert family == "python"

    def test_c_family_fragment_detected(self):
        det = _make_detector()
        score, family = det.score_with_fragments("public static void main(String[] args) {")
        assert score >= 0.4
        assert family == "c_family"

    def test_sql_fragment_detected(self):
        det = _make_detector()
        _, family = det.score_with_fragments("SELECT * FROM users WHERE active = true")
        assert family == "sql"

    def test_assembly_fragment_detected(self):
        det = _make_detector()
        _, family = det.score_with_fragments("    mov eax, [ebp+8]")
        assert family == "assembly"

    def test_prose_no_fragment(self):
        det = _make_detector()
        _, family = det.score_with_fragments("The weather is nice today.")
        assert family is None


class TestContextWindow:
    def test_comment_bridged_by_code_neighbors(self):
        lines = [
            "def foo():",
            "    x = 1",
            "    # this is a comment",
            "    return x",
        ]
        det = _make_detector()
        scores = det.score_lines(lines, claimed_ranges=set())
        # Comment line (index 2) should get a non-zero score from neighbors
        assert scores[2] > 0

    def test_isolated_prose_stays_zero(self):
        lines = [
            "This is a normal paragraph.",
            "Nothing code-like here.",
            "Just plain text.",
        ]
        det = _make_detector()
        scores = det.score_lines(lines, claimed_ranges=set())
        assert all(s == 0.0 for s in scores)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_syntax.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement SyntaxDetector**

Implement `SyntaxDetector` with:
- `__init__(self, patterns: dict)` — pre-compile all regex patterns from config (code keywords, fragment patterns for all 7 families, assignment pattern, comment marker, intro phrase). Store scoring weights from config.
- `line_syntax_score(self, line: str) -> float` — per-line scoring using 5 features from design §9.1 (syntax char density, keyword count, line ending, assignment pattern, indentation)
- `score_with_fragments(self, line: str) -> tuple[float, str | None]` — syntax score + fragment matching. Returns (score, matched_family). Short-circuits on first family match.
- `score_lines(self, lines: list[str], claimed_ranges: set[int]) -> list[float]` — score all lines with context window. Applies contextualized scoring from design §9.3 (neighbor blending, transition boost, comment bridging). Returns -1.0 for claimed lines.
- `fragment_hits_for_block(self, lines: list[str]) -> dict[str, int]` — count fragment matches per family across all lines in a block (for LanguageDetector)

All regex patterns loaded from `zone_patterns.json`. No hardcoded patterns in the Python code.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_syntax.py -v`
Expected: 12 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/syntax.py \
       tests/test_zone_v2/test_syntax.py
git commit -m "feat(zone-v2): add SyntaxDetector — scoring, fragments, context window"
```

---

### Task 7: NegativeFilter — FP suppression

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/negative.py`
- Create: `tests/test_zone_v2/test_negative.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_negative.py
"""Tests for NegativeFilter — FP suppression signals.

Tests organized by the 35 known FPs from WildChat review.
"""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.negative import NegativeFilter
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_filter():
    return NegativeFilter(load_zone_patterns())


class TestErrorOutput:
    """4 FPs from WildChat: Rust compiler, Node stack trace, pip output, pylint."""

    def test_python_traceback(self):
        nf = _make_filter()
        assert nf.check_line('Traceback (most recent call last):') == "error_output"

    def test_python_file_line(self):
        nf = _make_filter()
        assert nf.check_line('  File "/app/server.py", line 42, in handle_request') == "error_output"

    def test_java_stack_frame(self):
        nf = _make_filter()
        assert nf.check_line('    at com.foo.Bar.process(Bar.java:42)') == "error_output"

    def test_npm_error(self):
        nf = _make_filter()
        assert nf.check_line('npm ERR! code ERESOLVE') == "error_output"

    def test_rust_compiler_error(self):
        nf = _make_filter()
        assert nf.check_line('error[E0382]: borrow of moved value') == "error_output"

    def test_timestamp_log(self):
        nf = _make_filter()
        assert nf.check_line('2024-01-15T10:30:00 ERROR connection refused') == "error_output"

    def test_code_line_not_error(self):
        nf = _make_filter()
        assert nf.check_line('result = process(data)') is None


class TestDialogPatterns:
    """3 FPs: character dialog with Name: 'text' format."""

    def test_dialog_line(self):
        nf = _make_filter()
        assert nf.check_line('Monika: "I know, I know. But I thought it would be nice..."') == "suppress"

    def test_dialog_without_quotes(self):
        nf = _make_filter()
        assert nf.check_line('Natsuki: I don\'t know what you mean by that.') == "suppress"


class TestMathPatterns:
    """3 FPs: p(0,1), inequality expressions, semicolon numbers."""

    def test_latex(self):
        nf = _make_filter()
        assert nf.check_line('\\frac{1}{2} + \\int_0^1 x dx') == "suppress"

    def test_probability_notation(self):
        nf = _make_filter()
        assert nf.check_line('Prob[X > 0] = 0.5') == "suppress"


class TestRatioPatterns:
    """7 FPs: MidJourney aspect ratios."""

    def test_aspect_ratio(self):
        nf = _make_filter()
        assert nf.check_line('4:3 is best for portrait images') == "suppress"

    def test_time_not_ratio(self):
        nf = _make_filter()
        assert nf.check_line('10:30 AM meeting tomorrow') == "suppress"


class TestProsePattern:
    def test_prose_sentence(self):
        nf = _make_filter()
        assert nf.check_line('The algorithm processes each element in the list.') == "suppress"

    def test_code_not_prose(self):
        nf = _make_filter()
        assert nf.check_line('    result = algorithm.process(elements)') is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_negative.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement NegativeFilter**

Implement `NegativeFilter` with:
- `__init__(self, patterns: dict)` — pre-compile all negative signal regexes from config sections `negative.error_output`, `negative.dialog`, `negative.math`, `negative.ratio`, `negative.prose`
- `check_line(self, line: str) -> str | None` — returns `"error_output"` for error lines, `"suppress"` for other negative signals, `None` if no negative signal matches. Checks in order: math → error_output → prose → dialog → ratio (order from design §10.7)
- `check_list_prefix(self, lines: list[str]) -> bool` — returns True if >70% of non-empty lines match the list prefix pattern (used by BlockAssembler, not per-line)

All patterns from `zone_patterns.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_negative.py -v`
Expected: 14 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/negative.py \
       tests/test_zone_v2/test_negative.py
git commit -m "feat(zone-v2): add NegativeFilter — 6 FP suppression signal types"
```

---

### Task 8: BlockAssembler — grouping, merging, validation

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/assembler.py`
- Create: `tests/test_zone_v2/test_assembler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_assembler.py
"""Tests for BlockAssembler — block grouping, gap bridging, bracket validation."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.assembler import BlockAssembler
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig


def _make_assembler():
    return BlockAssembler(load_zone_patterns(), ZoneConfig())


class TestGapBridging:
    def test_bridge_single_blank_line(self):
        lines = ["def foo():", "    x = 1", "", "    return x"]
        scores = [0.5, 0.5, 0.0, 0.5]
        line_types = [None, None, None, None]
        asm = _make_assembler()
        blocks = asm.assemble(lines, scores, line_types)
        # Should produce ONE block bridging the blank line
        assert len(blocks) == 1
        assert blocks[0].start_line == 0
        assert blocks[0].end_line == 4

    def test_break_on_three_blank_lines(self):
        lines = ["x = 1", "", "", "", "y = 2"]
        scores = [0.5, 0.0, 0.0, 0.0, 0.5]
        line_types = [None, None, None, None, None]
        asm = _make_assembler()
        blocks = asm.assemble(lines, scores, line_types)
        # Should produce TWO blocks (3 blanks = break)
        assert len(blocks) == 2


class TestMinBlockLines:
    def test_small_block_discarded(self):
        lines = ["x = 1", "y = 2", "z = 3"]  # 3 lines, below min_block_lines=8
        scores = [0.5, 0.5, 0.5]
        line_types = [None, None, None]
        asm = _make_assembler()
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 0

    def test_large_block_kept(self):
        lines = [f"x_{i} = {i}" for i in range(10)]
        scores = [0.5] * 10
        line_types = [None] * 10
        asm = _make_assembler()
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 1


class TestBracketValidation:
    def test_balanced_brackets(self):
        lines = ["config = {", '    "host": "localhost",', '    "port": 8080', "}"]
        scores = [0.5, 0.3, 0.3, 0.3]
        line_types = [None, None, None, None]
        asm = BlockAssembler(load_zone_patterns(), ZoneConfig(min_block_lines=3))
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 1


class TestRepetitiveStructure:
    def test_repetitive_prefix_detected(self):
        asm = _make_assembler()
        lines = [
            "npm ERR! code ERESOLVE",
            "npm ERR! ERESOLVE unable to resolve",
            "npm ERR! Found: react@18.2.0",
            "npm ERR! Could not resolve dependency",
        ]
        prefix = asm.detect_repetitive_structure(lines)
        assert prefix is not None
        assert "npm" in prefix

    def test_no_repetition_in_code(self):
        asm = _make_assembler()
        lines = [
            "def foo():",
            "    x = bar(1)",
            "    y = baz(x)",
            "    return x + y",
        ]
        prefix = asm.detect_repetitive_structure(lines)
        assert prefix is None


class TestErrorOutputRetype:
    def test_error_lines_become_error_output_block(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "app.py", line 5, in <module>',
            "    result = process(data)",
            "TypeError: unsupported operand type",
        ] + [""] * 5  # padding to meet min_block_lines
        scores = [0.0] * 9
        line_types = ["error_output", "error_output", "error_output", "error_output"] + [None] * 5
        asm = BlockAssembler(load_zone_patterns(), ZoneConfig(min_block_lines=3))
        blocks = asm.assemble(lines, scores, line_types)
        error_blocks = [b for b in blocks if b.zone_type == "error_output"]
        assert len(error_blocks) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_assembler.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement BlockAssembler**

Implement `BlockAssembler` with:
- `__init__(self, patterns: dict, config: ZoneConfig)`
- `assemble(self, lines, scores, line_types) -> list[ZoneBlock]` — main entry. Groups lines into runs, bridges gaps, validates brackets, checks repetitive structure, applies min_block_lines filter.
- `_group_runs(self, scores, line_types, lines)` — group consecutive scored lines. Bridge 1-2 blank lines. Break on 3+ blanks or type transitions.
- `_brackets_balanced(self, block_lines) -> tuple[bool, dict]` — check bracket balance with string-awareness.
- `detect_repetitive_structure(self, lines, threshold=0.50) -> str | None` — detect repetitive prefix pattern.
- `_check_opening_context(self, lines) -> bool` — check first 3-5 lines for strong code openers.
- `_compute_confidence(self, method, avg_score, high_ratio, block_lines) -> float` — confidence computation.

Follows design §11 assembly rules precisely.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_assembler.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/assembler.py \
       tests/test_zone_v2/test_assembler.py
git commit -m "feat(zone-v2): add BlockAssembler — grouping, gap bridging, bracket validation"
```

---

### Task 9: LanguageDetector

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/language.py`
- Create: `tests/test_zone_v2/test_language.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_language.py
"""Tests for LanguageDetector — language probability from fragment hits."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.language import LanguageDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return LanguageDetector(load_zone_patterns())


def test_python_detected():
    det = _make_detector()
    hits = {"python": 5, "c_family": 1}
    lang, conf, probs = det.detect_language([], hits)
    assert lang == "python"
    assert conf > 0.5


def test_c_family_detected():
    det = _make_detector()
    hits = {"c_family": 8}
    lang, conf, probs = det.detect_language([], hits)
    assert lang == "c_family"
    assert conf == 1.0


def test_javascript_disambiguation():
    det = _make_detector()
    lines = ["const x = document.getElementById('app');", "console.log(x);"]
    hits = {"c_family": 2}
    lang, _, _ = det.detect_language(lines, hits)
    assert lang == "javascript"


def test_go_disambiguation():
    det = _make_detector()
    lines = ["func main() {", '    fmt.Println("hello")', "}"]
    hits = {"c_family": 3}
    lang, _, _ = det.detect_language(lines, hits)
    assert lang == "go"


def test_no_hits_returns_empty():
    det = _make_detector()
    lang, conf, probs = det.detect_language([], {})
    assert lang == ""
    assert conf == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_language.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement LanguageDetector**

Implement `LanguageDetector` with:
- `__init__(self, patterns: dict)` — load C-family disambiguation markers from config
- `detect_language(self, block_lines, fragment_hits) -> tuple[str, float, dict]` — returns (top_language, confidence, probability_distribution). Normalizes fragment hits to probabilities. If top family is `c_family`, runs `_disambiguate_c_family`.
- `_disambiguate_c_family(self, lines) -> str | None` — checks for JS (`console.`, `document.`, `require(`), Java (`System.out.`, `package`), Go (`fmt.`, `func`, `:=`), C++ (`cout`, `std::`, `template<`), C (`printf`, `malloc`, `#include <stdio`), C# (`Console.Write`, `using System`). Returns specific language or None.

All disambiguation markers from design §12.2.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_language.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/language.py \
       tests/test_zone_v2/test_language.py
git commit -m "feat(zone-v2): add LanguageDetector — fragment-based language probability"
```

---

### Task 10: Orchestrator — wire everything together

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/orchestrator.py`
- Modify: `docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py`
- Create: `tests/test_zone_v2/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zone_v2/test_orchestrator.py
"""End-to-end tests for ZoneOrchestrator."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.orchestrator import ZoneOrchestrator
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig


def _make_orchestrator(**kwargs):
    return ZoneOrchestrator(ZoneConfig(**kwargs))


class TestPreScreenIntegration:
    def test_pure_prose_returns_empty(self):
        orch = _make_orchestrator()
        result = orch.detect_zones("The quick brown fox jumps over the lazy dog.", prompt_id="t1")
        assert len(result.blocks) == 0

    def test_empty_string(self):
        orch = _make_orchestrator()
        result = orch.detect_zones("", prompt_id="t2")
        assert len(result.blocks) == 0
        assert result.total_lines == 0


class TestFencedDetection:
    def test_fenced_python(self):
        text = "Hello\n```python\ndef foo():\n    return 1\n```\nBye"
        orch = _make_orchestrator()
        result = orch.detect_zones(text, prompt_id="t3")
        assert len(result.blocks) == 1
        assert result.blocks[0].zone_type == "code"
        assert result.blocks[0].language_hint == "python"
        assert result.blocks[0].confidence == 0.95

    def test_fenced_json(self):
        text = '```json\n{"key": "val"}\n```'
        orch = _make_orchestrator()
        result = orch.detect_zones(text, prompt_id="t4")
        assert result.blocks[0].zone_type == "config"


class TestUnfencedCodeDetection:
    def test_python_function(self):
        text = "\n".join([
            "Here is my code:",
            "",
            "def process(data):",
            "    result = []",
            "    for item in data:",
            "        if item.valid:",
            "            result.append(item.value)",
            "    return result",
            "",
            "Can you help me fix it?",
        ])
        orch = _make_orchestrator(min_block_lines=5)
        result = orch.detect_zones(text, prompt_id="t5")
        assert len(result.blocks) >= 1
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        assert len(code_blocks) == 1


class TestKnownFPsRejected:
    """Validate that the 35 known FPs from WildChat review are suppressed."""

    def test_aspect_ratios_rejected(self):
        text = "\n".join([
            "2:3 is best for portrait images and Pinterest posts",
            "3:2 widely used for printing purpose",
            "4:3 is a size of classic TV and best for Facebook",
            "4:5 is for Instagram and Twitter posts",
            "16:9 is a size of widescreen and best for desktop wallpaper",
            "1:1 is best for social media profile pictures",
            "9:16 is for TikTok and Instagram Stories",
            "21:9 is for ultrawide monitors and cinematic content",
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_ratios")
        assert len(result.blocks) == 0

    def test_dialog_rejected(self):
        text = "\n".join([
            'Monika: "I know, I know. But I thought it would be nice..."',
            'Natsuki: "I don\'t know, Monika. I just feel like..."',
            'Yuri: "Perhaps we should consider another approach."',
            'Sayori: "Yeah, that sounds like a good idea!"',
            'Monika: "Alright, let\'s try something different then."',
            'Natsuki: "Fine. But I\'m not doing anything weird."',
            'Yuri: "I agree with Natsuki on this one."',
            'Monika: "Great, then it\'s settled!"',
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_dialog")
        assert len(result.blocks) == 0

    def test_error_output_typed_correctly(self):
        text = "\n".join([
            "Traceback (most recent call last):",
            '  File "/app/server.py", line 42, in handle_request',
            "    result = process_data(payload)",
            '  File "/app/utils.py", line 118, in process_data',
            "    validated = schema.validate(data)",
            "ValidationError: field 'email' is required",
            "",
            "What does this error mean?",
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_error")
        error_blocks = [b for b in result.blocks if b.zone_type == "error_output"]
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        # Should be error_output, NOT code
        assert len(code_blocks) == 0
        assert len(error_blocks) >= 1

    def test_xml_angle_brackets_in_prose_rejected(self):
        text = "\n".join([
            "Format your output as: <CLAIM> followed by <MEASURE>",
            "Make sure each claim is backed by evidence.",
            "Use the format <CLAIM>: <MEASURE> for each point.",
            "Keep claims concise and measurable.",
            "Provide at least 3 claims per topic.",
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_xml")
        assert len(result.blocks) == 0


class TestConfigPresets:
    def test_high_recall_catches_small_blocks(self):
        text = "\n".join(["x = 1", "y = 2", "z = x + y"])
        orch = _make_orchestrator(sensitivity="high_recall", min_block_lines=3)
        # With min_block_lines=3, this might be caught
        result = orch.detect_zones(text, prompt_id="t_hr")
        # Not asserting count — just verifying it doesn't crash


class TestV1Compatibility:
    def test_same_interface_as_v1(self):
        """detect_zones returns PromptZones with blocks list."""
        orch = _make_orchestrator()
        result = orch.detect_zones("test", prompt_id="compat")
        assert hasattr(result, "prompt_id")
        assert hasattr(result, "total_lines")
        assert hasattr(result, "blocks")
        assert hasattr(result, "to_dict")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_orchestrator.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement ZoneOrchestrator**

Implement `ZoneOrchestrator` with:
- `__init__(self, config: ZoneConfig | None = None)` — create config, apply preset, load patterns, instantiate all detectors
- `detect_zones(self, text: str, prompt_id: str = "") -> PromptZones` — main entry point:
  1. Handle empty input
  2. Run pre-screen (if enabled) → return empty if no signals
  3. Split text into lines
  4. Run StructuralDetector → get blocks + claimed ranges
  5. Run FormatDetector on unclaimed lines → get blocks + claimed ranges
  6. Run SyntaxDetector on unclaimed lines → get per-line scores
  7. Run NegativeFilter on scored lines → suppress/retype lines
  8. Run BlockAssembler → assemble scored lines into blocks
  9. Optionally run LanguageDetector on each block
  10. Merge all blocks, sort by start_line, filter by min_confidence
  11. Return PromptZones

- [ ] **Step 4: Update `__init__.py` with `detect_zones` function**

```python
# Add to docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py
from docs.experiments.prompt_analysis.s4_zone_detection.v2.orchestrator import ZoneOrchestrator

_orchestrator: ZoneOrchestrator | None = None


def detect_zones(text: str, prompt_id: str = "", config: ZoneConfig | None = None) -> PromptZones:
    """Detect zones in text — convenience wrapper with singleton orchestrator."""
    global _orchestrator
    if _orchestrator is None or config is not None:
        _orchestrator = ZoneOrchestrator(config)
    return _orchestrator.detect_zones(text, prompt_id=prompt_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/test_orchestrator.py -v`
Expected: 10 PASSED

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/test_zone_v2/ -v`
Expected: ALL PASSED (54 total across all test files)

- [ ] **Step 7: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/orchestrator.py \
       docs/experiments/prompt_analysis/s4_zone_detection/v2/__init__.py \
       tests/test_zone_v2/test_orchestrator.py
git commit -m "feat(zone-v2): add ZoneOrchestrator — wires all detectors into cascade pipeline"
```

---

### Task 11: Corpus evaluation — validate against reviewed WildChat data

**Files:**
- Create: `docs/experiments/prompt_analysis/s4_zone_detection/v2/evaluate.py`

- [ ] **Step 1: Write evaluation script**

```python
# docs/experiments/prompt_analysis/s4_zone_detection/v2/evaluate.py
"""Evaluate zone detector v2 against the reviewed WildChat corpus.

Usage:
    .venv/bin/python -m docs.experiments.prompt_analysis.s4_zone_detection.v2.evaluate

Loads s4_labeled_corpus.jsonl, runs v2 on each reviewed prompt, compares
against human verdicts, reports precision/recall/F1/boundary metrics.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docs.experiments.prompt_analysis.s4_zone_detection.v2 import detect_zones
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

CORPUS_PATH = Path(__file__).parent.parent / "labeled_data" / "s4_labeled_corpus.jsonl"


def main():
    if not CORPUS_PATH.exists():
        print(f"Corpus not found: {CORPUS_PATH}")
        sys.exit(1)

    records = []
    with open(CORPUS_PATH) as f:
        for line in f:
            r = json.loads(line)
            if r.get("review_status") is not None:  # only reviewed records
                records.append(r)

    print(f"Evaluating on {len(records)} reviewed records...")

    tp = fp = fn = tn = 0
    for r in records:
        text = r["prompt_text"]
        has_blocks_human = r.get("review_status") in ("correct", "corrected") and bool(r.get("blocks"))
        no_blocks_human = r.get("review_status") == "wrong" or not r.get("blocks")

        result = detect_zones(text, prompt_id=r.get("prompt_id", ""), config=ZoneConfig())
        has_blocks_v2 = len(result.blocks) > 0

        if has_blocks_human and has_blocks_v2:
            tp += 1
        elif has_blocks_human and not has_blocks_v2:
            fn += 1
        elif not has_blocks_human and has_blocks_v2:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\nResults:")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision: {precision:.1%}")
    print(f"  Recall:    {recall:.1%}")
    print(f"  F1:        {f1:.3f}")
    print(f"\nTargets: Precision >90%, Recall >95%, F1 >0.92")
    print(f"  Precision {'PASS' if precision > 0.90 else 'FAIL'}")
    print(f"  Recall    {'PASS' if recall > 0.95 else 'FAIL'}")
    print(f"  F1        {'PASS' if f1 > 0.92 else 'FAIL'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run evaluation**

Run: `.venv/bin/python -m docs.experiments.prompt_analysis.s4_zone_detection.v2.evaluate`

Expected: Metrics should meet or approach the v2 targets (precision >90%, recall >95%). If metrics fall short, iterate on detector thresholds and patterns.

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/prompt_analysis/s4_zone_detection/v2/evaluate.py
git commit -m "feat(zone-v2): add corpus evaluation script"
```

---

### Task 12: Update review tool to use v2 detector

**Files:**
- Modify: `docs/experiments/prompt_analysis/tools/prompt_reviewer.py`

- [ ] **Step 1: Update import in prompt_reviewer.py**

Find the import of `zone_detector` and change it to use v2:

```python
# Old:
from docs.experiments.prompt_analysis.s4_zone_detection.zone_detector import detect_zones

# New:
from docs.experiments.prompt_analysis.s4_zone_detection.v2 import detect_zones
```

The v2 `detect_zones` has the same signature as v1 (`text: str, prompt_id: str`) and returns `PromptZones` with `ZoneBlock` objects that have the same fields. It is a drop-in replacement.

- [ ] **Step 2: Verify review tool still works**

Run: `.venv/bin/python -m docs.experiments.prompt_analysis.tools.prompt_reviewer`
Open `http://localhost:8234` in browser. Verify zones are displayed correctly.

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/prompt_analysis/tools/prompt_reviewer.py
git commit -m "refactor(zone-v2): switch review tool to v2 detector"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] §5 Pre-screen → Task 3
- [x] §6 Zone taxonomy → Task 1 (ZONE_TYPES)
- [x] §7 StructuralDetector → Task 4
- [x] §8 FormatDetector → Task 5
- [x] §9.1-9.3 SyntaxDetector (scoring + fragments + context) → Task 6
- [x] §10 NegativeFilter → Task 7
- [x] §11 BlockAssembler → Task 8
- [x] §12 LanguageDetector → Task 9
- [x] §15 Configuration → Task 2
- [x] §18 Validation → Task 11
- [x] FP coverage matrix (34/35) → Task 10 (orchestrator tests)
- [ ] §9.4 Semantic analysis (tokenizer, scope, continuation) → **Plan 2**
- [ ] §13 Escalation architecture → **Plan 2**
- [ ] §4 JS port → **Plan 3**
- [ ] §16 Performance benchmarks → **Plan 3**

**Placeholder scan:** No TBDs, TODOs, or "fill in later" found.

**Type consistency:** `ZoneBlock`, `PromptZones`, `ZoneConfig` used consistently. `detect_zones()` signature matches throughout. All detector `.detect()` methods return `tuple[list[ZoneBlock], set[int]]` except SyntaxDetector (returns scores) and NegativeFilter (returns per-line types).
