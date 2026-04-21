"""Heuristic zone detector — identifies code/structured blocks within prompts.

Detects four coarse zone types:
  - code: programming language source (Python, JS, Java, C, etc.)
  - structured_data: JSON, YAML, XML, TOML, INI, CSV, env files
  - cli_shell: shell commands, terminal output, CLI invocations
  - natural_language: prose, instructions, questions (default)

Returns a list of ZoneBlock spans per prompt with start/end line indices,
detected type, confidence, and detection method.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# Zone types
# ---------------------------------------------------------------------------

ZONE_TYPES = ("code", "markup", "config", "query", "cli_shell", "data", "natural_language")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ZoneBlock:
    start_line: int  # 0-indexed inclusive
    end_line: int  # 0-indexed exclusive
    zone_type: str
    confidence: float  # 0.0-1.0
    method: str  # detection method name
    language_hint: str = ""  # e.g. "python", "json", "bash"
    text: str = ""  # the actual block text


@dataclass
class PromptZones:
    prompt_id: str
    total_lines: int
    blocks: list[ZoneBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "prompt_id": self.prompt_id,
            "total_lines": self.total_lines,
            "blocks": [asdict(b) for b in self.blocks],
        }
        # Strip text from serialization (too large for JSONL)
        for b in d["blocks"]:
            del b["text"]
        return d


# ---------------------------------------------------------------------------
# Heuristic: fenced code blocks (``` ... ```)
# ---------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})\s*(\w+)?\s*$")
_FENCE_CLOSE = re.compile(r"^(`{3,}|~{3,})\s*$")

# Map common language tags to our coarse types
_LANG_TAG_MAP = {
    # code
    "python": "code", "py": "code", "javascript": "code", "js": "code",
    "typescript": "code", "ts": "code", "java": "code", "c": "code",
    "cpp": "code", "c++": "code", "csharp": "code", "cs": "code",
    "go": "code", "golang": "code", "rust": "code", "ruby": "code",
    "rb": "code", "php": "code", "swift": "code", "kotlin": "code",
    "scala": "code", "r": "code", "lua": "code", "perl": "code",
    "dart": "code", "haskell": "code", "hs": "code", "elixir": "code",
    "clojure": "code", "jsx": "code", "tsx": "code", "vue": "code",
    "svelte": "code", "matlab": "code", "julia": "code",
    "objective-c": "code", "objc": "code", "groovy": "code",
    "powershell": "code", "ps1": "code", "vb": "code", "vba": "code",
    "sql": "code", "graphql": "code", "gql": "code",
    "html": "code", "css": "code", "scss": "code", "sass": "code",
    "less": "code",
    # structured_data
    "json": "structured_data", "yaml": "structured_data",
    "yml": "structured_data", "xml": "structured_data",
    "toml": "structured_data", "ini": "structured_data",
    "csv": "structured_data", "tsv": "structured_data",
    "env": "structured_data", "dotenv": "structured_data",
    "properties": "structured_data", "plist": "structured_data",
    "hcl": "structured_data", "tf": "structured_data",
    # cli_shell
    "bash": "cli_shell", "sh": "cli_shell", "shell": "cli_shell",
    "zsh": "cli_shell", "fish": "cli_shell", "bat": "cli_shell",
    "cmd": "cli_shell", "console": "cli_shell", "terminal": "cli_shell",
    # ambiguous — default to code
    "text": "natural_language", "txt": "natural_language",
    "plaintext": "natural_language", "markdown": "natural_language",
    "md": "natural_language",
}


def _detect_fenced_blocks(lines: list[str]) -> list[ZoneBlock]:
    """Detect ``` fenced blocks with optional language tags."""
    blocks = []
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN.match(lines[i].strip())
        if m:
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            lang_tag = (m.group(2) or "").lower()
            start = i
            # Find closing fence
            j = i + 1
            while j < len(lines):
                cm = _FENCE_CLOSE.match(lines[j].strip())
                if cm and cm.group(1)[0] == fence_char and len(cm.group(1)) >= fence_len:
                    break
                j += 1
            # j is closing fence or end of lines
            end = min(j + 1, len(lines))
            block_text = "\n".join(lines[start:end])
            # Determine zone type from language tag
            if lang_tag:
                zone_type = _LANG_TAG_MAP.get(lang_tag, "code")
            else:
                # No language tag — check if content is actually code or just quoted prose
                inner_lines = [l for l in lines[start + 1:end - 1] if l.strip()]
                if inner_lines:
                    alpha_ratios = [
                        sum(c.isalpha() or c.isspace() for c in l) / max(len(l), 1)
                        for l in inner_lines
                    ]
                    avg_alpha = sum(alpha_ratios) / len(alpha_ratios)
                    # High alpha ratio + no code keywords = prose in backticks
                    kw_hits = sum(1 for l in inner_lines if _CODE_KEYWORDS.search(l))
                    syn_hits = sum(
                        1 for l in inner_lines
                        if len(_SYNTACTIC_CHARS.findall(l)) / max(len(l), 1) > 0.05
                    )
                    if avg_alpha > 0.80 and kw_hits == 0 and syn_hits < len(inner_lines) * 0.2:
                        zone_type = "natural_language"
                    else:
                        zone_type = "code"
                else:
                    zone_type = "code"
            blocks.append(ZoneBlock(
                start_line=start, end_line=end,
                zone_type=zone_type, confidence=0.95,
                method="fenced", language_hint=lang_tag or "",
                text=block_text,
            ))
            i = end
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------------------
# Heuristic: parse-based detection (JSON, YAML, XML)
# ---------------------------------------------------------------------------

def _try_json_block(text: str) -> bool:
    """Check if text is valid JSON (object or array)."""
    text = text.strip()
    if not text:
        return False
    if (text.startswith("{") and text.endswith("}")) or \
       (text.startswith("[") and text.endswith("]")):
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False
    return False


def _looks_like_yaml(lines: list[str]) -> bool:
    """Heuristic YAML detection — requires key: value pairs, not just bullet lists.

    Bullet lists (``- item``) alone are common in natural language (markdown).
    YAML requires *mapping* lines (``key: value``).  List items only count
    when they appear alongside mappings (nested YAML).
    """
    # key: value  (word chars in key, colon, then value — not just "word: " which matches prose)
    kv_pattern = re.compile(r"^(\s*)[\w_.-]+\s*:\s+\S.*$")
    list_pattern = re.compile(r"^\s*-\s+.+$")

    kv_lines = sum(1 for l in lines if kv_pattern.match(l))
    list_lines = sum(1 for l in lines if list_pattern.match(l))
    non_empty = sum(1 for l in lines if l.strip())

    # Must have at least 3 key:value lines — bullet-only blocks are markdown, not YAML
    if kv_lines < 3:
        return False

    # Reject if most lines are prose sentences (high alpha ratio)
    prose_lines = sum(
        1 for l in lines if l.strip() and
        sum(c.isalpha() or c.isspace() for c in l.strip()) / max(len(l.strip()), 1) > 0.85
    )
    if prose_lines / max(non_empty, 1) > 0.5:
        return False

    # Reject if "key" parts are long phrases (real YAML keys are short identifiers)
    long_key_lines = 0
    for l in lines:
        m = re.match(r"^(\s*)(.*?)\s*:\s+\S", l)
        if m:
            key = m.group(2).strip()
            if len(key.split()) > 3:  # YAML keys are rarely multi-word phrases
                long_key_lines += 1
    if long_key_lines > kv_lines * 0.5:
        return False

    yaml_lines = kv_lines + list_lines
    return yaml_lines / max(non_empty, 1) > 0.5


def _looks_like_xml(text: str) -> bool:
    """Heuristic XML/HTML detection."""
    text = text.strip()
    # Must have opening and closing tags
    has_open = bool(re.search(r"<\w+[\s>]", text))
    has_close = bool(re.search(r"</\w+>", text))
    tag_count = len(re.findall(r"</?[\w]+", text))
    return has_open and has_close and tag_count >= 3


def _looks_like_env(lines: list[str]) -> bool:
    """Detect .env / KEY=VALUE format."""
    env_pattern = re.compile(r"^[A-Z][A-Z0-9_]+=.+$")
    env_lines = sum(1 for l in lines if env_pattern.match(l.strip()))
    return env_lines >= 2 and env_lines / max(len(lines), 1) > 0.5


def _looks_like_csv(lines: list[str]) -> bool:
    """Detect CSV/TSV — consistent delimiter count across lines.

    Tightened to reject prose paragraphs that happen to contain commas.
    Requires: short average line length (real CSV rows are compact),
    consistent field count, and low alpha-word density per field.
    """
    non_empty = [l for l in lines if l.strip()]
    if len(non_empty) < 3:
        return False

    # Prose paragraphs tend to be long; CSV rows are compact
    avg_len = sum(len(l) for l in non_empty) / len(non_empty)
    if avg_len > 200:
        return False

    for delim in (",", "\t", "|"):
        counts = [l.count(delim) for l in non_empty]
        if not counts or counts[0] < 2:
            continue
        # All lines should have same delimiter count (±1)
        if not all(abs(c - counts[0]) <= 1 for c in counts):
            continue
        # Check that fields look like data, not prose sentences
        # Prose: fields are long multi-word phrases.  CSV: fields are short values.
        sample_fields = non_empty[0].split(delim)
        avg_field_len = sum(len(f.strip()) for f in sample_fields) / max(len(sample_fields), 1)
        if avg_field_len > 60:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Heuristic: syntax signal scoring (unfenced code detection)
# ---------------------------------------------------------------------------

_CODE_KEYWORDS = re.compile(
    r"\b(?:import|from|def|class|function|return|if|else|elif|"
    r"for|while|try|except|catch|throw|new|var|let|const|"
    r"public|private|protected|static|void|int|string|bool|float|"
    r"package|interface|implements|extends|override|async|await|"
    r"lambda|yield|raise|assert|include|require|module|export|"
    r"struct|enum|trait|impl|fn|match|use|pub|mut|"
    r"println|printf|fmt|console|System|std)\b"
)

_SHELL_INDICATORS = re.compile(
    r"(?:^\s*(?:\$|>>>)\s+\w|"  # prompt indicators (removed bare > — too common in prose)
    r"^\s*(?:sudo|cd|ls|cat|grep|awk|sed|find|chmod|chown|mkdir|rm|cp|mv|"
    r"curl|wget|docker|kubectl|git|npm|pip|brew|apt|yum|"
    r"ssh|scp|tar|unzip|make|cmake|"
    r"export|source|echo|alias|"
    r"systemctl|service|journalctl)\b)",
    re.MULTILINE
)
# Removed from shell: python, node, java, gcc — these are code keywords not shell-specific
# Removed: set, unset, which, whereis, head, tail, sort, wc, xargs — too generic

_SYNTACTIC_CHARS = re.compile(r"[{}()\[\];=<>|&!@#$^*/\\~]")

# Negative signals — lines that look syntactic but are actually prose/math
_MATH_PATTERN = re.compile(
    r"(?:Prob\[|P\[|E\[|Var\[|∩|∪|≤|≥|⊂|⊆|∈|∉|→|←|↔|∀|∃|∅|"
    r"\bprobab\w+\b|\bexpected\b|\bvariance\b|\bstatistic\w*\b|"
    r"\btheorem\b|\blemma\b|\bproof\b|\bcorollary\b|\bhypothesis\b|"
    r"\bcos\b|\bsin\b|\btan\b|\blog\b|\bexp\b|\bsqrt\b|"
    r"\\frac|\\begin|\\end|\\sum|\\int|\\alpha|\\beta|\\theta|\\phi)"
)

# Prose sentences: start with capital, mostly alpha, end with period
_PROSE_SENTENCE = re.compile(r"^[A-Z][a-z].*[.!?]$")


def _line_syntax_score(line: str) -> float:
    """Score a single line for code-likeness (0.0-1.0).

    Includes negative signals for math notation and natural-language
    sentences that happen to contain syntactic characters.
    """
    stripped = line.strip()
    if not stripped:
        return 0.0

    # Negative: math/statistics notation — brackets and equals signs are notation, not code
    if _MATH_PATTERN.search(stripped):
        return 0.0

    # Negative: prose sentence (starts capital, ends punctuation, mostly words)
    alpha_ratio = sum(c.isalpha() or c.isspace() for c in stripped) / max(len(stripped), 1)
    if _PROSE_SENTENCE.match(stripped) and alpha_ratio > 0.75:
        return 0.0

    score = 0.0

    # Syntactic character density
    syn_count = len(_SYNTACTIC_CHARS.findall(stripped))
    syn_density = syn_count / max(len(stripped), 1)
    if syn_density > 0.15:
        score += 0.3
    elif syn_density > 0.08:
        score += 0.15

    # Code keywords
    kw_count = len(_CODE_KEYWORDS.findall(stripped))
    if kw_count >= 2:
        score += 0.3
    elif kw_count >= 1:
        score += 0.15

    # Ends with { or ; or : (code-like line endings)
    if stripped.endswith(("{", ";", ")", "]", ",")):
        score += 0.1

    # Assignment pattern — tighten: require identifier = value, not "Prob[A] = 0.7"
    if re.match(r"^\s*[a-z_]\w*\s*[:=]", stripped):
        score += 0.1

    # Indentation (code tends to be indented)
    if line != stripped and len(line) - len(line.lstrip()) >= 2:
        score += 0.05

    return min(score, 1.0)


def _score_shell(lines: list[str]) -> float:
    """Score a block for shell/CLI likeness."""
    total = len([l for l in lines if l.strip()])
    if total == 0:
        return 0.0
    shell_hits = len(_SHELL_INDICATORS.findall("\n".join(lines)))
    prompt_lines = sum(1 for l in lines if re.match(r"^\s*\$\s", l))
    pipe_lines = sum(1 for l in lines if "|" in l and any(
        cmd in l for cmd in ("grep", "awk", "sed", "sort", "head", "tail", "wc", "xargs", "cut", "tr")
    ))
    return min((shell_hits + prompt_lines * 2 + pipe_lines) / max(total, 1), 1.0)


# ---------------------------------------------------------------------------
# Block segmentation — find contiguous non-NL blocks in unfenced regions
# ---------------------------------------------------------------------------

def _segment_unfenced(lines: list[str], fenced_ranges: set[int]) -> list[ZoneBlock]:
    """Find code/structured blocks in unfenced regions using line-level scoring."""
    blocks = []
    i = 0
    while i < len(lines):
        if i in fenced_ranges or not lines[i].strip():
            i += 1
            continue

        # Try multi-line structured detection first
        # Look ahead for a contiguous block of non-empty lines
        j = i
        while j < len(lines) and j not in fenced_ranges and lines[j].strip():
            j += 1
        # Also extend through single blank lines if surrounded by content
        while j < len(lines) and j not in fenced_ranges:
            if not lines[j].strip():
                # Check if next non-empty line continues the block
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines) and k not in fenced_ranges and k - j <= 2:
                    j = k + 1
                    continue
            elif lines[j].strip():
                j += 1
                continue
            break

        block_lines = lines[i:j]
        block_text = "\n".join(block_lines)
        non_empty = [l for l in block_lines if l.strip()]

        # Minimum block size — small blocks are noisy (math snippets, error lines, etc.)
        # Fenced blocks already handled above; unfenced needs >= 5 non-empty lines
        if len(non_empty) < 5:
            i = j if j > i else i + 1
            continue

        # Try structured data detection
        detected = False

        if _try_json_block(block_text):
            blocks.append(ZoneBlock(
                start_line=i, end_line=j, zone_type="config",
                confidence=0.90, method="json_parse",
                language_hint="json", text=block_text,
            ))
            detected = True

        elif _looks_like_yaml(non_empty):
            blocks.append(ZoneBlock(
                start_line=i, end_line=j, zone_type="config",
                confidence=0.80, method="yaml_heuristic",
                language_hint="yaml", text=block_text,
            ))
            detected = True

        elif _looks_like_xml(block_text):
            blocks.append(ZoneBlock(
                start_line=i, end_line=j, zone_type="markup",
                confidence=0.80, method="xml_heuristic",
                language_hint="xml", text=block_text,
            ))
            detected = True

        elif _looks_like_env(non_empty):
            blocks.append(ZoneBlock(
                start_line=i, end_line=j, zone_type="config",
                confidence=0.85, method="env_heuristic",
                language_hint="env", text=block_text,
            ))
            detected = True

        # csv_heuristic and shell_heuristic removed — 0% accuracy in review

        if not detected:
            # Try code detection via line-level syntax scoring
            line_scores = [_line_syntax_score(l) for l in non_empty]
            avg_score = sum(line_scores) / max(len(line_scores), 1)
            high_score_ratio = sum(1 for s in line_scores if s >= 0.25) / max(len(line_scores), 1)

            if avg_score >= 0.25 and high_score_ratio >= 0.5 and len(non_empty) >= 3:
                # Trim leading/trailing prose lines (high alpha ratio = natural language)
                trim_start = i
                trim_end = j
                all_scores = [_line_syntax_score(l) for l in lines[i:j]]
                while trim_start < trim_end and all_scores[trim_start - i] < 0.1:
                    s = lines[trim_start].strip()
                    alpha = sum(c.isalpha() or c.isspace() for c in s) / max(len(s), 1)
                    if alpha > 0.8 and s:
                        trim_start += 1
                    else:
                        break
                while trim_end > trim_start and all_scores[trim_end - 1 - i] < 0.1:
                    s = lines[trim_end - 1].strip()
                    alpha = sum(c.isalpha() or c.isspace() for c in s) / max(len(s), 1)
                    if alpha > 0.8 and s:
                        trim_end -= 1
                    else:
                        break
                trimmed_text = "\n".join(lines[trim_start:trim_end])
                blocks.append(ZoneBlock(
                    start_line=trim_start, end_line=trim_end, zone_type="code",
                    confidence=min(0.4 + avg_score, 0.85),
                    method="syntax_score",
                    language_hint="", text=trimmed_text,
                ))

        i = j if j > i else i + 1

    return blocks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_zones(text: str, prompt_id: str = "") -> PromptZones:
    """Detect code/structured blocks within a prompt.

    Returns PromptZones with a list of ZoneBlock spans.
    Only non-natural-language blocks are returned (natural_language is the default
    for any unclassified region).
    """
    lines = text.split("\n")
    result = PromptZones(prompt_id=prompt_id, total_lines=len(lines))

    # Phase 1: fenced blocks (high confidence)
    fenced = _detect_fenced_blocks(lines)
    result.blocks.extend(fenced)

    # Build set of line indices covered by fenced blocks
    fenced_ranges = set()
    for b in fenced:
        fenced_ranges.update(range(b.start_line, b.end_line))

    # Phase 2: unfenced blocks (lower confidence)
    unfenced = _segment_unfenced(lines, fenced_ranges)
    result.blocks.extend(unfenced)

    # Sort by start_line
    result.blocks.sort(key=lambda b: b.start_line)

    return result
