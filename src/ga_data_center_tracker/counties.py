"""Georgia county reference data.

The Solutions Tracker joins on county name in the exact form ``X County, Georgia``
(e.g. ``Fulton County, Georgia``). This module is the single source of truth for
that string and its FIPS code, so nothing downstream hand-types a county name.

The reference table is built from the U.S. Census Bureau's authoritative national
county file, filtered to Georgia (state FIPS 13). Run ``build_reference_csv`` (or
``python -m ga_data_center_tracker.counties``) to regenerate
``data/reference/ga_counties.csv``.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

import requests

from . import GEORGIA_COUNTY_COUNT, GEORGIA_STATE_FIPS

# Authoritative source: Census Bureau 2020 national county codes (pipe-delimited).
CENSUS_NATIONAL_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt"
)

# data/reference/ga_counties.csv, resolved relative to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_CSV_PATH = _REPO_ROOT / "data" / "reference" / "ga_counties.csv"

REFERENCE_FIELDS = ["county", "county_fips", "county_name", "state"]


@dataclass(frozen=True)
class County:
    """A single Georgia county."""

    name: str          # "Fulton County" (as Census names it)
    fips: str          # 5-digit FIPS, e.g. "13121"

    @property
    def tracker_name(self) -> str:
        """County in the Solutions Tracker convention: ``Fulton County, Georgia``."""
        return f"{self.name}, Georgia"


def fetch_georgia_counties(url: str = CENSUS_NATIONAL_COUNTY_URL) -> list[County]:
    """Fetch and parse Georgia's counties from the Census national county file.

    Raises ``ValueError`` if the result is not exactly 159 counties, which guards
    against a silently truncated or changed upstream file.
    """
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    counties: list[County] = []
    reader = csv.DictReader(io.StringIO(response.text), delimiter="|")
    for row in reader:
        if row["STATE"] != "GA":
            continue
        fips = f"{row['STATEFP']}{row['COUNTYFP']}"
        counties.append(County(name=row["COUNTYNAME"].strip(), fips=fips))

    counties.sort(key=lambda c: c.fips)

    if len(counties) != GEORGIA_COUNTY_COUNT:
        raise ValueError(
            f"Expected {GEORGIA_COUNTY_COUNT} Georgia counties, got {len(counties)}. "
            "The upstream Census file may have changed; verify before proceeding."
        )
    for county in counties:
        if not county.fips.startswith(GEORGIA_STATE_FIPS):
            raise ValueError(f"Non-Georgia FIPS slipped through: {county.fips}")
    return counties


def build_reference_csv(
    path: Path = REFERENCE_CSV_PATH,
    url: str = CENSUS_NATIONAL_COUNTY_URL,
) -> Path:
    """Build ``data/reference/ga_counties.csv`` from the Census source.

    Columns: county (tracker form), county_fips, county_name (Census form), state.
    Returns the written path.
    """
    counties = fetch_georgia_counties(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REFERENCE_FIELDS)
        writer.writeheader()
        for county in counties:
            writer.writerow(
                {
                    "county": county.tracker_name,
                    "county_fips": county.fips,
                    "county_name": county.name,
                    "state": "Georgia",
                }
            )
    return path


def load_reference(path: Path = REFERENCE_CSV_PATH) -> list[County]:
    """Load the committed county reference table from disk."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [County(name=row["county_name"], fips=row["county_fips"]) for row in reader]


def name_to_fips(path: Path = REFERENCE_CSV_PATH) -> dict[str, str]:
    """Map both ``Fulton County`` and ``Fulton County, Georgia`` to FIPS."""
    mapping: dict[str, str] = {}
    for county in load_reference(path):
        mapping[county.name.lower()] = county.fips
        mapping[county.tracker_name.lower()] = county.fips
        # Also accept the bare county name without the "County" suffix.
        bare = county.name.lower().removesuffix(" county").strip()
        mapping[bare] = county.fips
    return mapping


def normalize_county(raw: str, path: Path = REFERENCE_CSV_PATH) -> str | None:
    """Resolve a messy county string to the tracker form ``X County, Georgia``.

    Returns ``None`` if the input does not match a known Georgia county, so callers
    can route unresolved records to manual review rather than guessing.
    """
    if not raw:
        return None
    key = raw.strip().lower().removesuffix(", georgia").strip()
    fips = name_to_fips(path).get(key)
    if fips is None:
        return None
    for county in load_reference(path):
        if county.fips == fips:
            return county.tracker_name
    return None


def main() -> None:
    """CLI entry point: regenerate the county reference CSV."""
    path = build_reference_csv()
    print(f"Wrote {GEORGIA_COUNTY_COUNT} Georgia counties to {path}")


if __name__ == "__main__":
    main()
