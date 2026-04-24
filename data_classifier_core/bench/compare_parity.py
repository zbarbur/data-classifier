"""Compare per-prompt results between Python and Rust implementations.

Usage:
    python compare_parity.py /tmp/python_results.jsonl /tmp/rust_results.jsonl
"""
import json
import sys
from pathlib import Path


def load_results(path: str) -> dict[str, dict]:
    results = {}
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            results[r["prompt_id"]] = r
    return results


def compare_blocks(py_blocks: list, rs_blocks: list) -> list[str]:
    """Compare block lists and return list of differences."""
    diffs = []

    if len(py_blocks) != len(rs_blocks):
        diffs.append(f"block count: py={len(py_blocks)} rs={len(rs_blocks)}")

    # Compare blocks pairwise (by start_line order)
    py_sorted = sorted(py_blocks, key=lambda b: b["start_line"])
    rs_sorted = sorted(rs_blocks, key=lambda b: b["start_line"])

    for i, (pb, rb) in enumerate(zip(py_sorted, rs_sorted)):
        if pb["start_line"] != rb["start_line"]:
            diffs.append(f"block {i}: start py={pb['start_line']} rs={rb['start_line']}")
        if pb["end_line"] != rb["end_line"]:
            diffs.append(f"block {i}: end py={pb['end_line']} rs={rb['end_line']}")
        if pb["zone_type"] != rb["zone_type"]:
            diffs.append(f"block {i}: type py={pb['zone_type']} rs={rb['zone_type']}")
        if abs(pb["confidence"] - rb["confidence"]) > 0.01:
            diffs.append(f"block {i}: conf py={pb['confidence']:.3f} rs={rb['confidence']:.3f}")
        if pb.get("method") != rb.get("method"):
            diffs.append(f"block {i}: method py={pb.get('method')} rs={rb.get('method')}")

    # Extra blocks in either side
    if len(py_sorted) > len(rs_sorted):
        for b in py_sorted[len(rs_sorted):]:
            diffs.append(f"extra py block: {b['start_line']}-{b['end_line']} {b['zone_type']}")
    if len(rs_sorted) > len(py_sorted):
        for b in rs_sorted[len(py_sorted):]:
            diffs.append(f"extra rs block: {b['start_line']}-{b['end_line']} {b['zone_type']}")

    return diffs


def main():
    if len(sys.argv) < 3:
        print("Usage: compare_parity.py <python_results.jsonl> <rust_results.jsonl>")
        sys.exit(1)

    py_results = load_results(sys.argv[1])
    rs_results = load_results(sys.argv[2])

    # Check for missing prompts
    py_ids = set(py_results.keys())
    rs_ids = set(rs_results.keys())

    if py_ids != rs_ids:
        print(f"WARNING: prompt set mismatch")
        print(f"  Only in Python: {len(py_ids - rs_ids)}")
        print(f"  Only in Rust:   {len(rs_ids - py_ids)}")
        print()

    common = py_ids & rs_ids
    total = len(common)

    # Compare each prompt
    identical = 0
    detection_diff = 0
    boundary_diff = 0
    type_diff = 0
    confidence_diff = 0
    divergent_prompts = []

    for pid in sorted(common):
        py = py_results[pid]
        rs = rs_results[pid]

        if py["has_blocks"] != rs["has_blocks"]:
            detection_diff += 1
            divergent_prompts.append((pid, "detection", f"py={py['has_blocks']} rs={rs['has_blocks']}"))
            continue

        if py["block_count"] == rs["block_count"] == 0:
            identical += 1
            continue

        diffs = compare_blocks(py["blocks"], rs["blocks"])
        if not diffs:
            identical += 1
        else:
            for d in diffs:
                if "type" in d:
                    type_diff += 1
                elif "start" in d or "end" in d or "count" in d:
                    boundary_diff += 1
                elif "conf" in d:
                    confidence_diff += 1
            divergent_prompts.append((pid, "blocks", "; ".join(diffs)))

    print(f"=== Parity Report ({total} common prompts) ===")
    print(f"  Identical:           {identical} ({identical/total:.1%})")
    print(f"  Detection diverge:   {detection_diff}")
    print(f"  Boundary diverge:    {boundary_diff}")
    print(f"  Type diverge:        {type_diff}")
    print(f"  Confidence diverge:  {confidence_diff}")
    print()

    if divergent_prompts:
        print(f"=== Divergent Prompts ({len(divergent_prompts)}) ===")
        for pid, category, detail in divergent_prompts[:20]:
            print(f"  [{category}] {pid[:12]}...  {detail}")
        if len(divergent_prompts) > 20:
            print(f"  ... and {len(divergent_prompts) - 20} more")
    else:
        print("PERFECT PARITY — all prompts produce identical results")


if __name__ == "__main__":
    main()
