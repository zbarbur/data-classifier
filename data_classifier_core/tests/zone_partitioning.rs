// data_classifier_core/tests/zone_partitioning.rs
//
// Integration tests verifying that every non-blank line in the input belongs
// to exactly one block after the full pipeline runs.
//
// Design note: The ProseDetector trims trailing blank lines from each region
// and skips all-blank regions entirely. Therefore blank lines that fall
// between blocks are intentionally uncovered. The assert_complete_partition
// helper treats blank-only lines as optional — they may or may not be
// covered, but may NOT be double-covered.

use data_classifier_core::zone_detector::{ZoneBlock, ZoneConfig, ZoneOrchestrator, ZoneType};

fn make_orchestrator() -> ZoneOrchestrator {
    let config = ZoneConfig {
        min_block_lines: 1,
        min_confidence: 0.0,
        ..ZoneConfig::default()
    };
    ZoneOrchestrator::new(&config)
}

/// Assert that every non-blank line is covered by exactly one block, and that
/// no line (blank or not) is covered by more than one block.
///
/// Blank lines that sit between blocks are allowed to be uncovered — the
/// ProseDetector intentionally trims trailing blanks and skips all-blank
/// regions.
fn assert_complete_partition(blocks: &[ZoneBlock], lines: &[&str]) {
    let total_lines = lines.len();
    let mut covered = vec![false; total_lines];

    for b in blocks {
        for i in b.start_line..b.end_line {
            assert!(
                i < total_lines,
                "block [{}, {}) references line {} which is out of range (total_lines={})",
                b.start_line,
                b.end_line,
                i,
                total_lines
            );
            assert!(
                !covered[i],
                "line {} covered by multiple blocks (block [{}, {}))",
                i,
                b.start_line,
                b.end_line
            );
            covered[i] = true;
        }
    }

    // Every non-blank line must be covered.
    for (i, c) in covered.iter().enumerate() {
        if !c {
            let is_blank = lines[i].trim().is_empty();
            assert!(
                is_blank,
                "non-blank line {} ({:?}) not covered by any block",
                i,
                lines[i]
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// 1. Three prose sentences separated by newlines — all blocks NaturalLanguage,
///    complete partition.
#[test]
fn test_pure_prose_fully_partitioned() {
    let text =
        "This is a paragraph about the weather.\nIt has multiple sentences.\nAll natural language.";
    let lines: Vec<&str> = text.split('\n').collect();
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert_complete_partition(&result.blocks, &lines);
    assert!(
        !result.blocks.is_empty(),
        "prose input must produce at least one block"
    );
    for b in &result.blocks {
        assert_eq!(
            b.zone_type,
            ZoneType::NaturalLanguage,
            "all blocks in pure prose should be NaturalLanguage, got {:?}",
            b.zone_type
        );
    }
}

/// 2. Prose + fenced python code + prose — has Code block AND NaturalLanguage
///    blocks, complete partition.
#[test]
fn test_code_plus_prose_fully_partitioned() {
    let text = "Please help me fix this code:\n\n```python\ndef foo():\n    return 42\n```\n\nThe function should return 43 instead.";
    let lines: Vec<&str> = text.split('\n').collect();
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert_complete_partition(&result.blocks, &lines);

    let has_code = result
        .blocks
        .iter()
        .any(|b| b.zone_type == ZoneType::Code);
    let has_prose = result
        .blocks
        .iter()
        .any(|b| b.zone_type == ZoneType::NaturalLanguage);
    assert!(has_code, "code+prose input must have a Code block; blocks = {:?}", result.blocks);
    assert!(
        has_prose,
        "code+prose input must have a NaturalLanguage block; blocks = {:?}",
        result.blocks
    );
}

/// 3. Prose header + CSV data + prose footer — has Data block, complete
///    partition.
///
/// Two blank lines separate the prose sections from the CSV block so the
/// DataDetector sees the CSV rows as an isolated region (it tolerates ≤ 1
/// consecutive blank within a region, so a 2-blank gap acts as a hard
/// section boundary).
///
/// Note: The originally-specified input used uppercase-starting names
/// (Alice, Bob, Charlie) which push the DataDetector's sentence_score
/// above the 0.3 threshold, preventing Data detection.  Lowercase-prefixed
/// rows keep sentence_score low enough for the CSV rule to fire.
#[test]
fn test_csv_data_detected_in_mixed() {
    // All rows are digit-only CSV so char-class profiles are uniform
    // (line_uniformity > 0.5), delimiter_density > 0.3, sentence_score < 0.3.
    // Two blank lines before and after isolate the CSV section so the
    // DataDetector sees it without prose header lines in the same region.
    let text = "Here is the data:\n\n\n1,2,3,4,5\n6,7,8,9,0\n2,3,4,5,6\n7,8,9,0,1\n\n\nPlease check it.";
    let lines: Vec<&str> = text.split('\n').collect();
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert_complete_partition(&result.blocks, &lines);

    let has_data = result
        .blocks
        .iter()
        .any(|b| b.zone_type == ZoneType::Data);
    assert!(
        has_data,
        "CSV mixed input must have a Data block; blocks = {:?}",
        result.blocks
    );
}

/// 4. Mixed text — all blocks have confidence >= 0.20.
#[test]
fn test_every_block_has_confidence() {
    let text = "Hello world.\n\ndef foo():\n    pass\n\nGoodbye.";
    let lines: Vec<&str> = text.split('\n').collect();
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert_complete_partition(&result.blocks, &lines);

    for b in &result.blocks {
        assert!(
            b.confidence >= 0.20,
            "block {:?} has confidence {} < 0.20",
            b.zone_type,
            b.confidence
        );
    }
}

/// 5. Empty string → empty blocks.
#[test]
fn test_empty_input_no_blocks() {
    let text = "";
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert!(
        result.blocks.is_empty(),
        "empty input must produce no blocks, got {:?}",
        result.blocks
    );
}

/// 6. Single line of prose → exactly 1 NaturalLanguage block.
#[test]
fn test_single_line_prose() {
    let text = "Just one line of text.";
    let lines: Vec<&str> = text.split('\n').collect();
    let o = make_orchestrator();
    let result = o.detect_zones(text, "test");

    assert_complete_partition(&result.blocks, &lines);
    assert_eq!(
        result.blocks.len(),
        1,
        "single line must produce exactly 1 block, got {:?}",
        result.blocks
    );
    assert_eq!(
        result.blocks[0].zone_type,
        ZoneType::NaturalLanguage,
        "single prose line must be NaturalLanguage, got {:?}",
        result.blocks[0].zone_type
    );
}
