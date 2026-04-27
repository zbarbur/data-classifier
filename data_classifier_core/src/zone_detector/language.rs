//! LanguageDetector — language probability from fragment hits.
//!
//! Mirrors Python language.py. Called per-block by the Orchestrator.
//! Receives fragment_hits from SyntaxDetector.fragment_hits_for_block().
//! Enriches ZoneBlocks with language_hint and language_confidence.

use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;

/// Detect programming language from fragment family hits and disambiguation markers.
pub struct LanguageDetector {
    /// Per-language disambiguation patterns for C-family languages.
    c_family_markers: Vec<(String, Vec<Regex>)>,
}

impl LanguageDetector {
    pub fn new(patterns: &Value) -> Self {
        let lang_cfg = patterns.get("language").unwrap_or(&Value::Null);
        let raw_markers = lang_cfg
            .get("c_family_markers")
            .and_then(|v| v.as_object());

        let c_family_markers: Vec<(String, Vec<Regex>)> = raw_markers
            .map(|obj| {
                obj.iter()
                    .map(|(lang, pats)| {
                        let compiled: Vec<Regex> = pats
                            .as_array()
                            .map(|arr| {
                                arr.iter()
                                    .filter_map(|p| p.as_str().and_then(|s| Regex::new(s).ok()))
                                    .collect()
                            })
                            .unwrap_or_default();
                        (lang.clone(), compiled)
                    })
                    .collect()
            })
            .unwrap_or_default();

        Self { c_family_markers }
    }

    /// Compute language from fragment family hit counts.
    ///
    /// Returns `(top_language, confidence, full_distribution)`.
    pub fn detect_language(
        &self,
        block_lines: &[&str],
        fragment_hits: &HashMap<String, usize>,
    ) -> (String, f64, HashMap<String, f64>) {
        if fragment_hits.is_empty() {
            return (String::new(), 0.0, HashMap::new());
        }

        // Normalize to probability distribution
        let total: usize = fragment_hits.values().sum();
        let mut distribution: HashMap<String, f64> = fragment_hits
            .iter()
            .map(|(family, count)| (family.clone(), *count as f64 / total as f64))
            .collect();

        // Find top family
        let top_family = distribution
            .iter()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
            .map(|(k, _)| k.clone())
            .unwrap_or_default();
        let top_conf = *distribution.get(&top_family).unwrap_or(&0.0);

        // C-family disambiguation
        if top_family == "c_family" && top_conf > 0.5 && !block_lines.is_empty() {
            if let Some(specific) = self.disambiguate_c_family(block_lines) {
                if let Some(val) = distribution.remove("c_family") {
                    distribution.insert(specific.clone(), val);
                }
                return (specific, top_conf, distribution);
            }
        }

        (top_family, top_conf, distribution)
    }

    /// Identify the specific C-family language from marker patterns.
    fn disambiguate_c_family(&self, lines: &[&str]) -> Option<String> {
        let joined = lines.join("\n");
        let mut scores: HashMap<&str, usize> = HashMap::new();

        for (lang, compiled_pats) in &self.c_family_markers {
            let count = compiled_pats
                .iter()
                .filter(|pat| pat.is_match(&joined))
                .count();
            if count > 0 {
                scores.insert(lang, count);
            }
        }

        if scores.is_empty() {
            return None;
        }

        scores
            .into_iter()
            .max_by_key(|&(_, count)| count)
            .map(|(lang, _)| lang.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_detector() -> LanguageDetector {
        LanguageDetector::new(&serde_json::json!({
            "language": {
                "c_family_markers": {
                    "javascript": ["\\bconsole\\.\\w+", "\\bdocument\\.\\w+"],
                    "python": ["\\bdef\\s+\\w+", "\\bimport\\s+\\w+"],
                    "java": ["\\bSystem\\.out\\.", "\\bpublic\\s+static\\s+void\\s+main"]
                }
            }
        }))
    }

    #[test]
    fn test_empty_hits() {
        let d = make_detector();
        let (lang, conf, _) = d.detect_language(&[], &HashMap::new());
        assert!(lang.is_empty());
        assert_eq!(conf, 0.0);
    }

    #[test]
    fn test_python_dominant() {
        let d = make_detector();
        let mut hits = HashMap::new();
        hits.insert("python".to_string(), 5);
        hits.insert("c_family".to_string(), 1);
        let (lang, conf, _) = d.detect_language(&[], &hits);
        assert_eq!(lang, "python");
        assert!(conf > 0.5);
    }

    #[test]
    fn test_c_family_disambiguated_to_javascript() {
        let d = make_detector();
        let mut hits = HashMap::new();
        hits.insert("c_family".to_string(), 10);
        let lines = vec![
            "console.log('hello');",
            "document.getElementById('app');",
        ];
        let (lang, _, _) = d.detect_language(&lines, &hits);
        assert_eq!(lang, "javascript");
    }

    #[test]
    fn test_c_family_disambiguated_to_java() {
        let d = make_detector();
        let mut hits = HashMap::new();
        hits.insert("c_family".to_string(), 10);
        let lines = vec![
            "public static void main(String[] args) {",
            "    System.out.println(\"hello\");",
            "}",
        ];
        let (lang, _, _) = d.detect_language(&lines, &hits);
        assert_eq!(lang, "java");
    }

    #[test]
    fn test_c_family_no_markers_stays_c_family() {
        let d = make_detector();
        let mut hits = HashMap::new();
        hits.insert("c_family".to_string(), 10);
        // Lines with no language-specific markers
        let lines = vec![
            "int x = 0;",
            "x++;",
        ];
        let (lang, _, _) = d.detect_language(&lines, &hits);
        assert_eq!(lang, "c_family");
    }

    #[test]
    fn test_c_family_below_threshold_no_disambiguation() {
        let d = make_detector();
        let mut hits = HashMap::new();
        hits.insert("c_family".to_string(), 3);
        hits.insert("python".to_string(), 4);
        // c_family is not dominant (< 50%), so no disambiguation
        let lines = vec!["console.log('hi');"];
        let (lang, _, _) = d.detect_language(&lines, &hits);
        assert_eq!(lang, "python"); // python wins by hit count
    }
}
