"""Pipeline orchestration.

Ties the stages together: ensure the county reference exists, run each source
scraper, aggregate to per-county indicators, and write the GT-conformant
``.xlsx`` deliverable.

This is the single entry point a future maintainer (or Ashley, a year from now)
runs to regenerate the dataset. As more scrapers land, register them in
``SCRAPERS`` and add their variables to the assembled dataset.

Run:  ``python -m ga_data_center_tracker.pipeline --out data/processed/ga_data_centers.xlsx``
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .counties import REFERENCE_CSV_PATH, build_reference_csv, load_reference
from .delivery import Dataset, Variable, build_long_rows, write_workbook
from .scrapers import epa_frs


def ensure_reference() -> None:
    """Make sure the county reference table exists before anything joins on it."""
    if not REFERENCE_CSV_PATH.exists():
        build_reference_csv()


def run(out_path: Path, *, max_lookups: int | None = None, verbose: bool = True) -> Path:
    """Run the full pipeline and write the deliverable workbook.

    Currently wires up the EPA FRS source. Additional sources are added here as
    their scrapers come online (Georgia Power OASIS, county permits, minutes).
    """
    ensure_reference()

    if verbose:
        print("Scraping EPA FRS (operational / permitted facilities)...")
    frs_records = epa_frs.scrape_georgia_data_centers(max_lookups=max_lookups, verbose=verbose)
    frs_counts = epa_frs.records_to_county_counts(frs_records)

    # Per-county value map. As sources are added, merge their counts in here.
    county_values: dict[str, dict[str, object]] = {
        county.tracker_name: {"dc_operational_n": frs_counts[county.tracker_name]}
        for county in load_reference()
    }

    long_rows = build_long_rows(county_values)

    # Original sheet: the resolved facility-level records behind the counts.
    original_rows = [
        {
            "registry_id": r.registry_id,
            "name": r.name,
            "county": r.county,
            "county_fips": r.county_fips,
            "city": r.city,
            "address": r.address,
            "operating_status": r.operating_status,
            "program": r.program,
            "source": r.source,
        }
        for r in frs_records
    ]

    variables = [
        Variable(
            varname="dc_operational_n",
            definition="Count of operational / permitted data centers (NAICS 518210) in the county.",
            units="facilities",
            source="EPA Facility Registry Service (FRS)",
            vintage="current FRS snapshot",
            date_pulled="",  # stamped at delivery time
            original_name="NAICS 518210 facilities, FRS",
            transformations="Filtered to Georgia; county-matched by FIPS; deduplicated by registry_id.",
        ),
    ]

    dataset = Dataset(
        original_rows=original_rows,
        long_rows=long_rows,
        variables=variables,
        notes="Phase 5 draft. EPA FRS source only; more sources pending.",
    )

    written = write_workbook(dataset, out_path)
    if verbose:
        print(f"Wrote {len(original_rows)} facility records -> {written}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the GA Data Center Tracker dataset.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/ga_data_centers.xlsx"),
        help="Output .xlsx path.",
    )
    parser.add_argument(
        "--max-lookups",
        type=int,
        default=None,
        help="Cap per-ID lookups for a quick test run (default: process all).",
    )
    args = parser.parse_args()
    run(args.out, max_lookups=args.max_lookups)


if __name__ == "__main__":
    main()
