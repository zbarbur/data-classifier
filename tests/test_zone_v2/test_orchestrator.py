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
        text = "\n".join(
            [
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
            ]
        )
        orch = _make_orchestrator(min_block_lines=5)
        result = orch.detect_zones(text, prompt_id="t5")
        assert len(result.blocks) >= 1
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        assert len(code_blocks) == 1


class TestKnownFPsRejected:
    def test_aspect_ratios_rejected(self):
        text = "\n".join(
            [
                "2:3 is best for portrait images and Pinterest posts",
                "3:2 widely used for printing purpose",
                "4:3 is a size of classic TV and best for Facebook",
                "4:5 is for Instagram and Twitter posts",
                "16:9 is a size of widescreen and best for desktop wallpaper",
                "1:1 is best for social media profile pictures",
                "9:16 is for TikTok and Instagram Stories",
                "21:9 is for ultrawide monitors and cinematic content",
            ]
        )
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_ratios")
        assert len(result.blocks) == 0

    def test_dialog_rejected(self):
        text = "\n".join(
            [
                'Monika: "I know, I know. But I thought it would be nice..."',
                'Natsuki: "I don\'t know, Monika. I just feel like..."',
                'Yuri: "Perhaps we should consider another approach."',
                'Sayori: "Yeah, that sounds like a good idea!"',
                'Monika: "Alright, let\'s try something different then."',
                'Natsuki: "Fine. But I\'m not doing anything weird."',
                'Yuri: "I agree with Natsuki on this one."',
                'Monika: "Great, then it\'s settled!"',
            ]
        )
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_dialog")
        assert len(result.blocks) == 0

    def test_error_output_typed_correctly(self):
        text = "\n".join(
            [
                "Traceback (most recent call last):",
                '  File "/app/server.py", line 42, in handle_request',
                "    result = process_data(payload)",
                '  File "/app/utils.py", line 118, in process_data',
                "    validated = schema.validate(data)",
                "ValidationError: field 'email' is required",
                "",
                "What does this error mean?",
            ]
        )
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_error")
        error_blocks = [b for b in result.blocks if b.zone_type == "error_output"]
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        assert len(code_blocks) == 0
        assert len(error_blocks) >= 1

    def test_xml_angle_brackets_in_prose_rejected(self):
        text = "\n".join(
            [
                "Format your output as: <CLAIM> followed by <MEASURE>",
                "Make sure each claim is backed by evidence.",
                "Use the format <CLAIM>: <MEASURE> for each point.",
                "Keep claims concise and measurable.",
                "Provide at least 3 claims per topic.",
            ]
        )
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="fp_xml")
        assert len(result.blocks) == 0


class TestV1Compatibility:
    def test_same_interface_as_v1(self):
        orch = _make_orchestrator()
        result = orch.detect_zones("test", prompt_id="compat")
        assert hasattr(result, "prompt_id")
        assert hasattr(result, "total_lines")
        assert hasattr(result, "blocks")
        assert hasattr(result, "to_dict")


class TestScopeTrackerIntegration:
    def test_multiline_function_call_not_fragmented(self):
        """A function call split across lines should produce one block, not fragments."""
        text = "\n".join([
            "Here is the code:",
            "",
            "result = transform(",
            "    data,",
            "    columns=['a', 'b', 'c'],",
            "    timeout=30,",
            "    retries=3,",
            "    verbose=True,",
            "    batch_size=100,",
            ")",
            "",
            "What do you think?",
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="scope_1")
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        assert len(code_blocks) == 1, f"Expected 1 block, got {len(code_blocks)}"

    def test_python_function_body_one_block(self):
        """A Python function with comments should be one block, not fragmented."""
        text = "\n".join([
            "Here is my function:",
            "",
            "def process(data):",
            "    # validate input",
            "    if not data:",
            "        return []",
            "    # process each item",
            "    result = []",
            "    for item in data:",
            "        result.append(item.upper())",
            "    return result",
            "",
            "How can I improve it?",
        ])
        orch = _make_orchestrator(min_block_lines=3)
        result = orch.detect_zones(text, prompt_id="scope_2")
        code_blocks = [b for b in result.blocks if b.zone_type == "code"]
        assert len(code_blocks) == 1, f"Expected 1 block, got {len(code_blocks)}"
