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
