"""EPA Facility Registry Service (FRS) scraper.

This is the template scraper: pull -> resolve -> county-match -> typed records.
Other source scrapers follow the same shape.

FRS is a federal registry of facilities regulated under environmental programs.
Data centers that file for air / backup-generator permits appear here classified
under NAICS 518210 (Data Processing, Hosting, and Related Services). FRS therefore
captures *permitted / operational* facilities, not proposals, and only those that
triggered an environmental program. That partial coverage is expected and is
documented in the methodology; FRS is one input, cross-checked against others.

The EPA Envirofacts auto-join across FRS tables hits a server-side type-cast bug,
so this module joins in Python across three single-table queries:

  1. FRS_NAICS (naics_code = 518210)            -> program-system IDs nationwide
  2. FRS_PROGRAM_FACILITY (by pgm_sys_id)        -> registry_id + state (keep GA)
  3. FRS_FACILITY_SITE (by registry_id)          -> county FIPS, name, address

Records are deduplicated by registry_id and county-matched to the tracker form
``X County, Georgia`` via the county reference table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from ..counties import load_reference, normalize_county

EFSERVICE = "https://data.epa.gov/efservice"
DATA_CENTER_NAICS = "518210"

# Program-system acronyms that are state-specific. If the NAICS record came from
# one of these and it is not Georgia's, the facility cannot be in Georgia, so we
# skip the per-ID lookup. Saves ~25% of network calls. National programs (AIR,
# EIS, RCRAINFO, ICIS, ...) are not state-bound and are always looked up.
_NON_GA_STATE_PROGRAMS = {
    "CA-CERS", "CA-ENVIROVIEW", "CARB-TCH", "NJ-NJEMS", "MN-TEMPO", "MD-TEMPO",
    "MO-DNR", "MS-ENSITE", "PA-EFACTS", "TX-TCEQ ACR", "MA-EPICS",
}

_FIPS_TO_TRACKER: dict[str, str] = {}  # county FIPS -> tracker name, populated lazily


@dataclass
class FacilityRecord:
    """One Georgia data center facility as resolved from FRS."""

    registry_id: str
    name: str
    county: str | None          # "Fulton County, Georgia" or None if unresolved
    county_fips: str | None
    city: str = ""
    address: str = ""
    operating_status: str = ""
    program: str = ""           # FRS program acronym the NAICS record came from
    source: str = "EPA FRS"
    stage: str = "operational"  # FRS captures permitted/operational facilities


def _get_json(url: str, *, timeout: int = 60, retries: int = 3) -> list[dict]:
    """GET an efservice URL and return parsed rows, with simple retry/backoff."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"Envirofacts error: {data['error']}")
            return data if isinstance(data, list) else []
        except Exception as exc:  # network / JSON / server error
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


def fetch_data_center_naics_records() -> list[dict]:
    """All nationwide FRS_NAICS rows classified as data centers (NAICS 518210)."""
    return _get_json(f"{EFSERVICE}/FRS_NAICS/naics_code/{DATA_CENTER_NAICS}/JSON")


def fetch_program_facility(pgm_sys_id: str) -> dict | None:
    """Look up a program-facility record by its program-system ID."""
    rows = _get_json(f"{EFSERVICE}/FRS_PROGRAM_FACILITY/pgm_sys_id/{pgm_sys_id}/JSON")
    return rows[0] if rows else None


def fetch_facility_site(registry_id: str) -> dict | None:
    """Look up the master facility-site record (county FIPS, name) by registry ID."""
    rows = _get_json(f"{EFSERVICE}/FRS_FACILITY_SITE/registry_id/{registry_id}/JSON")
    return rows[0] if rows else None


def _fips_to_tracker() -> dict[str, str]:
    global _FIPS_TO_TRACKER
    if not _FIPS_TO_TRACKER:
        _FIPS_TO_TRACKER = {c.fips: c.tracker_name for c in load_reference()}
    return _FIPS_TO_TRACKER


def _resolve_county(site: dict) -> tuple[str | None, str | None]:
    """Resolve a facility site to (tracker county name, FIPS).

    Prefer the FIPS the record carries; fall back to matching the county name.
    """
    fips = (site.get("std_county_fips") or site.get("fips_code") or "").strip()
    mapping = _fips_to_tracker()
    if fips in mapping:
        return mapping[fips], fips
    # Fall back to the standardized county name.
    name = site.get("std_county_name") or site.get("county_name") or ""
    tracker = normalize_county(name)
    if tracker:
        return tracker, next((c.fips for c in load_reference() if c.tracker_name == tracker), None)
    return None, fips or None


def scrape_georgia_data_centers(
    *,
    max_lookups: int | None = None,
    sleep: float = 0.1,
    verbose: bool = False,
) -> list[FacilityRecord]:
    """Scrape Georgia data center facilities from EPA FRS.

    Args:
        max_lookups: cap the number of per-ID lookups (for quick test runs).
            ``None`` processes every data-center NAICS record.
        sleep: seconds to pause between requests (be polite to the API).
        verbose: print progress.

    Returns deduplicated ``FacilityRecord``s for Georgia.
    """
    naics_rows = fetch_data_center_naics_records()
    candidates = [
        r for r in naics_rows
        if r.get("pgm_sys_id") and r.get("pgm_sys_acrnm") not in _NON_GA_STATE_PROGRAMS
    ]
    if max_lookups is not None:
        candidates = candidates[:max_lookups]

    by_registry: dict[str, FacilityRecord] = {}
    skipped = 0
    for i, row in enumerate(candidates):
        pgm_sys_id = row["pgm_sys_id"]
        program = row.get("pgm_sys_acrnm", "")
        # A single bad ID (occasional FRS 500s) must not abort the whole run.
        try:
            pf = fetch_program_facility(pgm_sys_id)
            time.sleep(sleep)
            if not pf or (pf.get("state_code") or "").upper() != "GA":
                continue
            registry_id = pf.get("registry_id")
            if not registry_id or registry_id in by_registry:
                continue
            site = fetch_facility_site(registry_id)
            time.sleep(sleep)
        except RuntimeError as exc:
            skipped += 1
            if verbose:
                print(f"[{i + 1}/{len(candidates)}] skip {pgm_sys_id}: {exc}")
            continue
        if not site:
            continue
        county, fips = _resolve_county(site)
        by_registry[registry_id] = FacilityRecord(
            registry_id=registry_id,
            name=site.get("primary_name") or pf.get("primary_name") or "",
            county=county,
            county_fips=fips,
            city=site.get("city_name") or "",
            address=site.get("location_address") or "",
            operating_status=site.get("operating_status") or "",
            program=program,
        )
        if verbose:
            rec = by_registry[registry_id]
            print(f"[{i + 1}/{len(candidates)}] GA: {rec.name} -> {rec.county}")

    if verbose and skipped:
        print(f"(skipped {skipped} records that errored upstream)")
    return list(by_registry.values())


def records_to_county_counts(records: list[FacilityRecord]) -> dict[str, int]:
    """Aggregate facility records to a per-county count (tracker county -> count).

    Every Georgia county is present, defaulting to 0, so the result is dense and
    ready for the Long sheet. Records with an unresolved county are skipped and
    should be sent to manual review.
    """
    counts = {c.tracker_name: 0 for c in load_reference()}
    for rec in records:
        if rec.county and rec.county in counts:
            counts[rec.county] += 1
    return counts
