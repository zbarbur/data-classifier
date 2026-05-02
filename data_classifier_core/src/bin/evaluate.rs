//! Corpus evaluator — measures detection accuracy, boundary accuracy,
//! and throughput. Mirrors Python evaluate.py for parity comparison.
//!
//! Usage:
//!   cargo run --release --bin evaluate -- <patterns.json> <corpus.jsonl> [--output results.jsonl]

use data_classifier_core::zone_detector::{PromptZones, ZoneConfig, ZoneOrchestrator};
use serde_json::Value;
use std::collections::HashSet;
use std::io::{BufRead, Write};
use std::time::Instant;
use std::{env, fs, io, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: evaluate <patterns.json> <corpus.jsonl> [--output results.jsonl]");
        process::exit(1);
    }

    let patterns_path = &args[1];
    let corpus_path = &args[2];
    let output_path = args
        .iter()
        .position(|a| a == "--output")
        .and_then(|i| args.get(i + 1))
        .map(|s| s.as_str());

    // Load patterns
    let patterns_str = fs::read_to_string(patterns_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {}: {}", patterns_path, e);
        process::exit(1);
    });
    let patterns: Value = serde_json::from_str(&patterns_str).unwrap_or_else(|e| {
        eprintln!("Failed to parse patterns JSON: {}", e);
        process::exit(1);
    });

    let config = ZoneConfig {
        min_block_lines: 8,
        min_confidence: 0.50,
        ..ZoneConfig::default()
    };
    let orchestrator = ZoneOrchestrator::from_patterns(&patterns, &config);

    // Load corpus
    let file = fs::File::open(corpus_path).unwrap_or_else(|e| {
        eprintln!("Failed to open {}: {}", corpus_path, e);
        process::exit(1);
    });
    let reader = io::BufReader::new(file);

    let mut records: Vec<Value> = Vec::new();
    let mut skipped_unreviewed = 0;

    for line in reader.lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        if line.trim().is_empty() {
            continue;
        }
        let r: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let (has_blocks, gt_blocks) = ground_truth(&r);
        match has_blocks {
            None => {
                skipped_unreviewed += 1;
            }
            Some(hb) => {
                let mut rec = r.clone();
                rec["_gt_has_blocks"] = Value::Bool(hb);
                rec["_gt_blocks"] = Value::Array(gt_blocks);
                records.push(rec);
            }
        }
    }

    println!("Corpus: {} total records", records.len() + skipped_unreviewed);
    println!("  Reviewed (evaluated): {}", records.len());
    println!("  Unreviewed (skipped): {}", skipped_unreviewed);
    println!();

    // --- Evaluate ---
    let mut tp = 0u32;
    let mut fp = 0u32;
    let mut r#fn = 0u32;
    let mut tn = 0u32;

    let mut boundary_jaccards: Vec<f64> = Vec::new();
    let mut boundary_recalls: Vec<f64> = Vec::new();
    let mut boundary_precisions: Vec<f64> = Vec::new();
    let mut block_count_ratios: Vec<f64> = Vec::new();

    let mut output_file: Option<fs::File> = output_path.map(|p| {
        fs::File::create(p).unwrap_or_else(|e| {
            eprintln!("Failed to create output file {}: {}", p, e);
            process::exit(1);
        })
    });

    let start = Instant::now();

    for rec in &records {
        let text = rec["text"].as_str().unwrap_or("");
        if text.is_empty() {
            continue;
        }

        let prompt_id = rec["prompt_id"].as_str().unwrap_or("");
        let has_real_blocks = rec["_gt_has_blocks"].as_bool().unwrap_or(false);
        let gt_blocks = rec["_gt_blocks"].as_array().cloned().unwrap_or_default();

        let result: PromptZones = orchestrator.detect_zones(text, prompt_id);
        let has_v2_blocks = !result.blocks.is_empty();

        // Detection accuracy
        match (has_real_blocks, has_v2_blocks) {
            (true, true) => tp += 1,
            (true, false) => r#fn += 1,
            (false, true) => fp += 1,
            (false, false) => tn += 1,
        }

        // Boundary accuracy (records with human-marked ranges)
        if !gt_blocks.is_empty() && has_v2_blocks {
            let gt_lines = line_set_from_value(&gt_blocks);
            let v2_lines: HashSet<usize> = result
                .blocks
                .iter()
                .flat_map(|b| b.start_line..b.end_line)
                .collect();

            if !gt_lines.is_empty() {
                let jacc = jaccard(&gt_lines, &v2_lines);
                boundary_jaccards.push(jacc);

                let b_recall =
                    gt_lines.intersection(&v2_lines).count() as f64 / gt_lines.len() as f64;
                boundary_recalls.push(b_recall);

                if !v2_lines.is_empty() {
                    let b_prec = gt_lines.intersection(&v2_lines).count() as f64
                        / v2_lines.len() as f64;
                    boundary_precisions.push(b_prec);
                }

                let gt_count = gt_blocks.len();
                let v2_count = result.blocks.len();
                if gt_count > 0 {
                    block_count_ratios.push(v2_count as f64 / gt_count as f64);
                }
            }
        }

        // Write per-prompt results for parity comparison
        if let Some(ref mut f) = output_file {
            let blocks_json: Vec<Value> = result
                .blocks
                .iter()
                .map(|b| {
                    serde_json::json!({
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                        "zone_type": b.zone_type,
                        "confidence": (b.confidence * 1000.0).round() / 1000.0,
                        "method": b.method,
                        "language_hint": b.language_hint,
                    })
                })
                .collect();

            let out = serde_json::json!({
                "prompt_id": prompt_id,
                "has_blocks": has_v2_blocks,
                "block_count": result.blocks.len(),
                "blocks": blocks_json,
            });
            writeln!(f, "{}", serde_json::to_string(&out).unwrap()).unwrap();
        }
    }

    let elapsed = start.elapsed();
    let elapsed_secs = elapsed.as_secs_f64();
    let total = (tp + fp + r#fn + tn) as f64;

    let precision = if (tp + fp) > 0 {
        tp as f64 / (tp + fp) as f64
    } else {
        0.0
    };
    let recall = if (tp + r#fn) > 0 {
        tp as f64 / (tp + r#fn) as f64
    } else {
        0.0
    };
    let f1 = if (precision + recall) > 0.0 {
        2.0 * precision * recall / (precision + recall)
    } else {
        0.0
    };

    println!(
        "=== Detection Accuracy ({} records, {:.1}s) ===",
        total as u32, elapsed_secs
    );
    println!("  TP={}  FP={}  FN={}  TN={}", tp, fp, r#fn, tn);
    println!("  Precision: {:.1}%", precision * 100.0);
    println!("  Recall:    {:.1}%", recall * 100.0);
    println!("  F1:        {:.3}", f1);
    println!("  Throughput: {:.0} prompts/sec", total / elapsed_secs);
    println!();

    if !boundary_jaccards.is_empty() {
        let avg_jacc = mean(&boundary_jaccards);
        let avg_b_recall = mean(&boundary_recalls);
        let avg_b_prec = if boundary_precisions.is_empty() {
            0.0
        } else {
            mean(&boundary_precisions)
        };
        let avg_frag = if block_count_ratios.is_empty() {
            0.0
        } else {
            mean(&block_count_ratios)
        };
        let median_jacc = median(&boundary_jaccards);
        let median_b_recall = median(&boundary_recalls);

        println!(
            "=== Boundary Accuracy ({} records with human-marked ranges) ===",
            boundary_jaccards.len()
        );
        println!(
            "  Line-level Jaccard:     mean={:.1}%  median={:.1}%",
            avg_jacc * 100.0,
            median_jacc * 100.0
        );
        println!(
            "  Boundary recall:        mean={:.1}%  median={:.1}%",
            avg_b_recall * 100.0,
            median_b_recall * 100.0
        );
        println!("  Boundary precision:     mean={:.1}%", avg_b_prec * 100.0);
        println!(
            "  Fragmentation ratio:    mean={:.2}x  (1.0 = perfect, >1 = over-split)",
            avg_frag
        );
        println!();
    }

    println!("=== Targets ===");
    println!(
        "  Detection precision >90%:   {} ({:.1}%)",
        if precision > 0.90 { "PASS" } else { "FAIL" },
        precision * 100.0
    );
    println!(
        "  Detection recall >95%:      {} ({:.1}%)",
        if recall > 0.95 { "PASS" } else { "FAIL" },
        recall * 100.0
    );
    println!(
        "  Detection F1 >0.92:         {} ({:.3})",
        if f1 > 0.92 { "PASS" } else { "FAIL" },
        f1
    );
    if !boundary_jaccards.is_empty() {
        let avg_b_recall = mean(&boundary_recalls);
        let avg_frag = mean(&block_count_ratios);
        println!(
            "  Boundary recall >85%:       {} ({:.1}%)",
            if avg_b_recall > 0.85 { "PASS" } else { "FAIL" },
            avg_b_recall * 100.0
        );
        println!(
            "  Fragmentation <1.3x:        {} ({:.2}x)",
            if avg_frag < 1.3 { "PASS" } else { "FAIL" },
            avg_frag
        );
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn ground_truth(record: &Value) -> (Option<bool>, Vec<Value>) {
    let review = record.get("review").unwrap_or(&Value::Null);
    let correct = review.get("correct");

    if correct.is_none() || correct == Some(&Value::Null) {
        return (None, Vec::new());
    }

    let actual_blocks: Vec<Value> = review
        .get("actual_blocks")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    if correct == Some(&Value::Bool(true)) {
        if !actual_blocks.is_empty() {
            return (Some(true), actual_blocks);
        }
        let heuristic = record
            .get("heuristic_has_blocks")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        return (Some(heuristic), Vec::new());
    }

    let has = !actual_blocks.is_empty();
    (Some(has), actual_blocks)
}

fn line_set_from_value(blocks: &[Value]) -> HashSet<usize> {
    let mut lines = HashSet::new();
    for b in blocks {
        let s = b
            .get("start_line")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize;
        let e = b
            .get("end_line")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize;
        for idx in s..e {
            lines.insert(idx);
        }
    }
    lines
}

fn jaccard(a: &HashSet<usize>, b: &HashSet<usize>) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    let union_size = a.union(b).count();
    if union_size == 0 {
        return 1.0;
    }
    a.intersection(b).count() as f64 / union_size as f64
}

fn mean(v: &[f64]) -> f64 {
    if v.is_empty() {
        0.0
    } else {
        v.iter().sum::<f64>() / v.len() as f64
    }
}

fn median(v: &[f64]) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    let mut sorted = v.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    sorted[sorted.len() / 2]
}
