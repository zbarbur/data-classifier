"""Smoke test for the gliner-context research track.

Purpose:
  1. Confirm fastino/gliner2-base-v1 loads from the local HF cache (zero network).
  2. Confirm extract_entities(text, dict_of_label_to_desc) is a live API path
     that propagates descriptions into the model's internal schema.
  3. Prove that descriptions actually influence predictions by comparing a
     dict-with-descriptions call vs a flat-list call on the same text.

Run:
    .venv/bin/python scripts/research/gliner_context_smoke.py
"""
from __future__ import annotations

import json
import time


def main() -> int:
    print("=" * 72)
    print("gliner-context smoke test — fastino/gliner2-base-v1 from local cache")
    print("=" * 72)

    t0 = time.perf_counter()
    from gliner2 import GLiNER2
    model = GLiNER2.from_pretrained("fastino/gliner2-base-v1")
    t_load = time.perf_counter() - t0
    print(f"\n[1] Model loaded in {t_load:.2f}s (cache hit = zero network)")

    # Synthetic column — mimics how production packages samples
    column_name = "email_address"
    table_name = "users"
    description = "user's primary contact email, required, unique"
    values = [
        "alice@example.com",
        "bob.smith@acme.co.uk",
        "charlie+filter@test.org",
        "david.jones@data.gov",
        "eve@university.edu",
    ]
    text = " ; ".join(values)
    print(f"\n[2] Input text ({len(values)} values):\n    {text}")

    # --- Call A: flat list of labels (what production does with urchade v1) ---
    labels_list = ["person", "email", "street address", "organization", "phone number"]
    t0 = time.perf_counter()
    result_a = model.extract_entities(text, labels_list, threshold=0.5, include_confidence=True)
    t_a = time.perf_counter() - t0
    print(f"\n[3] Flat list labels: {t_a*1000:.0f}ms")
    print(f"    result: {json.dumps(result_a, indent=2, default=str)[:600]}")

    # --- Call B: dict of label -> description (what v2 production builds) ---
    labels_dict = {
        "person": "Names of people or individuals, including first and last names",
        "email": "Email addresses including international domains and subdomains",
        "street address": "Street names, roads, avenues, physical locations",
        "organization": "Company names, institutions, agencies, or organizational entities",
        "phone number": "Telephone numbers in any international format",
    }
    t0 = time.perf_counter()
    result_b = model.extract_entities(text, labels_dict, threshold=0.5, include_confidence=True)
    t_b = time.perf_counter() - t0
    print(f"\n[4] Dict labels with descriptions: {t_b*1000:.0f}ms")
    print(f"    result: {json.dumps(result_b, indent=2, default=str)[:600]}")

    # --- Call C: S1 natural-language prompt (what we're proposing to measure) ---
    prompt_c = (
        f"Column '{column_name}' from table '{table_name}'. "
        f"Description: {description}. "
        f"Sample values: {', '.join(values)}"
    )
    t0 = time.perf_counter()
    result_c = model.extract_entities(prompt_c, labels_dict, threshold=0.5, include_confidence=True)
    t_c = time.perf_counter() - t0
    print(f"\n[5] S1 — NL prompt with context: {t_c*1000:.0f}ms")
    print(f"    prompt: {prompt_c[:150]}...")
    print(f"    result: {json.dumps(result_c, indent=2, default=str)[:600]}")

    # --- Compare: do descriptions actually change the result? ---
    ents_a = set()
    ents_b = set()
    for r, bag in ((result_a, ents_a), (result_b, ents_b)):
        for label, matches in r.get("entities", {}).items():
            for m in matches:
                txt = m.get("text", "") if isinstance(m, dict) else str(m)
                bag.add((label, txt))

    print("\n[6] Comparison: flat-list vs dict-with-descriptions")
    print(f"    flat list entities:  {sorted(ents_a)}")
    print(f"    dict+desc entities:  {sorted(ents_b)}")
    print(f"    ⚠ identical?         {ents_a == ents_b}")
    if ents_a == ents_b:
        print("    → descriptions did NOT change this prediction (expected for easy email case)")
    else:
        print("    → descriptions CHANGED the prediction — S2 has real signal")

    print("\n" + "=" * 72)
    print("Smoke test complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
