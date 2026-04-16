"""Sprint 12 Item #2: ingest public-domain first-name + surname lists.

Builds ``data_classifier/patterns/name_lists.json`` from two public-domain
US federal data sources:

1. **Surnames** — US Census Bureau 2010 Surname Frequency Data.
   Source: https://www2.census.gov/topics/genealogy/2010surnames/names.zip
   Format: ``Names_2010Census.csv`` with columns name, rank, count, ...
   License: public domain (17 U.S.C. § 105 — works of US federal government).

2. **First names** — US Social Security Administration Baby Names.
   Source: https://www.ssa.gov/oact/babynames/names.zip
   Format: 144 yearly files ``yob{YYYY}.txt`` with rows ``name,sex,count``.
   License: public domain (17 U.S.C. § 105 — works of US federal government).

The script aggregates SSA yearly counts across all years, sorts by total,
takes the top-N, filters to lowercase ASCII of length ``MIN_TOKEN_LENGTH``
or longer, and emits a single JSON file consumed by
``data_classifier.engines.heuristic_engine.compute_dictionary_name_match_ratio``.

SSA direct downloads are CDN-blocked for automated fetchers (HTTP 403);
this script reads from local zip files that have been pre-downloaded
(direct for Census, via Internet Archive mirror for SSA — both are
publicly-accessible snapshots of the same underlying public-domain data).
The script does NOT fetch data from the network; it only reads local
zip files and writes the curated JSON. Network fetches are a manual
step, documented in the docstring below.

Manual pre-download steps:

    # Census 2010 surnames (direct, works from CI and CDN):
    curl -L -o /tmp/census_names.zip \\
        https://www2.census.gov/topics/genealogy/2010surnames/names.zip

    # SSA baby names (direct 403s; use Internet Archive mirror):
    curl -L -o /tmp/ssa_names.zip \\
        'https://web.archive.org/web/2025/https://www.ssa.gov/oact/babynames/names.zip'

    # Run the ingestion:
    python -m scripts.ingest_name_lists \\
        --census /tmp/census_names.zip \\
        --ssa /tmp/ssa_names.zip \\
        --out data_classifier/patterns/name_lists.json

The generated JSON commits alongside the script. It is not regenerated
at build time. Re-run this script only when updating the curated name
lists (e.g., next Census or a new SSA year).

Note on filter parameters: ``MIN_TOKEN_LENGTH = 4`` matches the
``_CONTENT_WORDS_MIN_LEN = 5`` floor used by ``compute_dictionary_word_ratio``
with one character less, because names are shorter on average than
content words ("John" is a valid first name, "john" at length 4 is a
sensible minimum). Below 4, too many English words collide with short
names ("al", "jo", "ed") and the feature becomes noise.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

TOP_N_SURNAMES: int = 5000
TOP_N_FIRST_NAMES: int = 5000
MIN_TOKEN_LENGTH: int = 4


def _normalize(name: str) -> str:
    """Lowercase + strip. Returns empty string if the input is non-ASCII
    or contains any non-alpha characters (names with apostrophes, hyphens,
    or spaces are excluded from the match dictionary — the tokenizer on
    the read side splits on ``[a-z]+`` so those entries would never match
    anyway)."""
    clean = name.strip().lower()
    if not clean.isascii() or not clean.isalpha():
        return ""
    return clean


def load_census_surnames(zip_path: Path, top_n: int) -> list[str]:
    """Load the top-N surnames from the Census 2010 surnames zip.

    Parses ``Names_2010Census.csv`` inside the zip. Keeps the rows with
    rank 1..top_n, lowercases and filters to ASCII-alpha only, returns
    a sorted-by-rank list (most common first).
    """
    with ZipFile(zip_path) as zf:
        with zf.open("Names_2010Census.csv") as f:
            header = f.readline().decode("utf-8").strip()
            if not header.startswith("name,rank,count"):
                raise ValueError(f"unexpected Census CSV header: {header!r}")
            surnames: list[tuple[int, str]] = []
            for raw in f:
                row = raw.decode("utf-8").strip().split(",")
                if len(row) < 3:
                    continue
                name = _normalize(row[0])
                if not name or len(name) < MIN_TOKEN_LENGTH:
                    continue
                try:
                    rank = int(row[1])
                except ValueError:
                    continue
                surnames.append((rank, name))
    surnames.sort(key=lambda entry: entry[0])
    return [name for _, name in surnames[:top_n]]


def load_ssa_first_names(zip_path: Path, top_n: int) -> list[str]:
    """Load the top-N first names from the SSA baby-names zip.

    Iterates every ``yob{YYYY}.txt`` file inside the zip, aggregates the
    count column across all years to get a single cumulative count per
    name, sorts descending, filters to ASCII-alpha of length
    ``MIN_TOKEN_LENGTH``+, and returns the top-N in most-common-first
    order.
    """
    cumulative: Counter[str] = Counter()
    with ZipFile(zip_path) as zf:
        yearly_files = [n for n in zf.namelist() if n.startswith("yob") and n.endswith(".txt")]
        if not yearly_files:
            raise ValueError(f"no yob*.txt files found in {zip_path}")
        for year_file in yearly_files:
            with zf.open(year_file) as f:
                for raw in f:
                    row = raw.decode("utf-8").strip().split(",")
                    if len(row) < 3:
                        continue
                    name = _normalize(row[0])
                    if not name or len(name) < MIN_TOKEN_LENGTH:
                        continue
                    try:
                        count = int(row[2])
                    except ValueError:
                        continue
                    cumulative[name] += count
    # Sort by cumulative count descending, then alphabetical for ties.
    sorted_names = sorted(
        cumulative.items(),
        key=lambda entry: (-entry[1], entry[0]),
    )
    return [name for name, _ in sorted_names[:top_n]]


def build_manifest(
    first_names: list[str],
    surnames: list[str],
) -> dict:
    """Assemble the final JSON manifest with sources, filter parameters,
    and the two lists. Lists are stored in most-common-first order so a
    downstream consumer that wants a smaller subset can just slice."""
    return {
        "first_names": first_names,
        "surnames": surnames,
        "min_token_length": MIN_TOKEN_LENGTH,
        "sources": [
            {
                "name": "US Social Security Administration Baby Names (national)",
                "url": "https://www.ssa.gov/oact/babynames/names.zip",
                "retrieved_via": (
                    "Internet Archive mirror — "
                    "https://web.archive.org/web/2025/https://www.ssa.gov/oact/babynames/names.zip. "
                    "SSA direct downloads are CDN-blocked for automated fetchers (HTTP 403). "
                    "The Internet Archive snapshot is byte-identical to the SSA-hosted zip."
                ),
                "license": ("Public domain (17 U.S.C. § 105 — works of US federal government)"),
                "top_n": TOP_N_FIRST_NAMES,
                "aggregation": ("Sum of per-year counts across all yearly files (yob1880.txt through yob2023.txt)"),
            },
            {
                "name": "US Census Bureau 2010 Surname Frequency Data",
                "url": "https://www2.census.gov/topics/genealogy/2010surnames/names.zip",
                "retrieved_via": "direct",
                "license": ("Public domain (17 U.S.C. § 105 — works of US federal government)"),
                "top_n": TOP_N_SURNAMES,
                "aggregation": "Top N by census-assigned rank column",
            },
        ],
        "filter_rules": [
            "Lowercased before comparison",
            f"Minimum token length: {MIN_TOKEN_LENGTH}",
            "ASCII-alpha only (rejects names with apostrophes, hyphens, or non-Latin characters)",
            "Duplicates across the two lists are allowed — a token that is "
            "both a common first name and a common surname appears in both",
        ],
    }


def write_manifest(path: Path, manifest: dict) -> None:
    """Write the manifest as pretty-printed JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=True)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest US Census surnames + SSA first names into "
            "data_classifier/patterns/name_lists.json. "
            "See the module docstring for manual pre-download steps."
        ),
    )
    parser.add_argument(
        "--census",
        type=Path,
        required=True,
        help="Path to the pre-downloaded Census 2010 surnames zip",
    )
    parser.add_argument(
        "--ssa",
        type=Path,
        required=True,
        help="Path to the pre-downloaded SSA baby-names zip",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output path for the generated name_lists.json",
    )
    args = parser.parse_args(argv)

    if not args.census.is_file():
        print(f"error: Census zip not found at {args.census}", file=sys.stderr)
        return 2
    if not args.ssa.is_file():
        print(f"error: SSA zip not found at {args.ssa}", file=sys.stderr)
        return 2

    print(f"Loading surnames from {args.census} ...", file=sys.stderr)
    surnames = load_census_surnames(args.census, TOP_N_SURNAMES)
    print(f"  {len(surnames)} surnames retained", file=sys.stderr)

    print(f"Loading first names from {args.ssa} ...", file=sys.stderr)
    first_names = load_ssa_first_names(args.ssa, TOP_N_FIRST_NAMES)
    print(f"  {len(first_names)} first names retained", file=sys.stderr)

    manifest = build_manifest(first_names, surnames)
    write_manifest(args.out, manifest)
    print(f"Wrote {args.out}", file=sys.stderr)
    print(
        f"  first_names: {len(first_names)}, surnames: {len(surnames)}, min_token_length: {MIN_TOKEN_LENGTH}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
