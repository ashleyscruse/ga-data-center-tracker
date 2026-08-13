"""Pipeline orchestration.

Ties the stages together: ensure the county reference exists, run each source
scraper, aggregate to per-county indicators, and write the GT-conformant
``.xlsx`` deliverable.

This is the single entry point a future maintainer (or Ashley, a year from now)
runs to regenerate the dataset. As more scrapers land, register them here and add
their variables to the assembled dataset.

Sources currently wired in:

  * **Georgia EPD Air Protection Branch** (``ga_epd_air``) -> permitted facilities,
    county-resolved from the AIRS number, with issuance dates. The primary facility
    source: it is state-level, dated, and reaches the construction-permitting stage.
  * **EPA FRS** (``epa_frs``) -> federally registered facilities. Retained as an
    independent cross-check on EPD rather than a substitute for it.
  * **Georgia Tech EPIcenter Ordinance Hub** (``epicenter``) -> local government
    response: which counties have adopted a data center ordinance, and which have
    adopted a moratorium. This is the community engagement strand's first source.

The facility sources are reported as separate variables. They are not merged into a
single facility count, because reconciling them requires entity resolution across
differing operator names and addresses, and a silently wrong merge is worse in a
published dataset than two honestly separate counts. See ``docs/methodology.md``.

Run:  ``python -m ga_data_center_tracker.pipeline --out data/processed/ga_data_centers.xlsx``
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .counties import (
    REFERENCE_CSV_PATH,
    build_reference_csv,
    load_reference,
    normalize_county,
)
from .delivery import (
    Dataset,
    Variable,
    build_long_rows,
    build_transformed_rows,
    write_workbook,
)
from .scrapers import epa_frs, epd_permit_docs, epicenter, ga_epd_air, institutional

# Facilities first permitted in this year or later count as the current buildout.
# 2023 is the inflection point in the EPD permit record: before it, Georgia issued
# roughly one data center air permit a year.
BUILDOUT_START_YEAR = 2023

# Uniform column set for the Original sheet, so records from every source stack
# into one table.
ORIGINAL_COLUMNS = [
    "source",
    "source_id",
    "name",
    "county",
    "county_fips",
    "stage",
    "first_permit_date",
    "latest_permit_date",
    "permit_count",
    "permit_types",
    "city",
    "address",
    "operating_status",
    "program",
    # From the permit PDFs for EPD facilities; hand-entered for institutional ones.
    "zip_code",
    # Public citation: the permit PDF for EPD rows, the announcement for curated ones.
    "source_url",
    "note",
]


def ensure_reference() -> None:
    """Make sure the county reference table exists before anything joins on it."""
    if not REFERENCE_CSV_PATH.exists():
        build_reference_csv()


def _epd_original_rows(facilities, addresses=None) -> list[dict[str, object]]:
    """Flatten EPD facility records into the shared Original-sheet schema.

    ``addresses`` comes from the permit PDFs (see ``epd_permit_docs``); the search
    grid itself publishes no address. A facility whose permit is a scanned image,
    or which has no permit PDF at all, simply keeps empty address fields.
    """
    addresses = addresses or {}
    rows = []
    for f in facilities:
        row: dict[str, object] = {col: "" for col in ORIGINAL_COLUMNS}
        addr = addresses.get(f.airs_number)
        if addr is not None:
            row.update(
                {
                    "address": addr.street,
                    "city": addr.city,
                    "zip_code": addr.zip_code,
                    "source_url": addr.pdf_url,
                }
            )
        row.update(
            {
                "source": f.source,
                "source_id": f.airs_number,
                "name": f.name,
                "county": f.county or "",
                "county_fips": f.county_fips or "",
                "stage": f.stage,
                "first_permit_date": (
                    f.first_permit_date.isoformat() if f.first_permit_date else ""
                ),
                "latest_permit_date": (
                    f.latest_permit_date.isoformat() if f.latest_permit_date else ""
                ),
                "permit_count": f.permit_count,
                "permit_types": f.permit_types,
            }
        )
        rows.append(row)
    return rows


def _frs_original_rows(records) -> list[dict[str, object]]:
    """Flatten FRS facility records into the shared Original-sheet schema."""
    rows = []
    for r in records:
        row: dict[str, object] = {col: "" for col in ORIGINAL_COLUMNS}
        row.update(
            {
                "source": r.source,
                "source_id": r.registry_id,
                "name": r.name,
                "county": r.county or "",
                "county_fips": r.county_fips or "",
                "stage": r.stage,
                "city": r.city,
                "address": r.address,
                "operating_status": r.operating_status,
                "program": r.program,
            }
        )
        rows.append(row)
    return rows


def _institutional_original_rows(facilities) -> list[dict[str, object]]:
    """Flatten institutional facility records into the shared Original-sheet schema."""
    rows = []
    fips_by_name = {c.tracker_name: c.fips for c in load_reference()}
    for f in facilities:
        row: dict[str, object] = {col: "" for col in ORIGINAL_COLUMNS}
        tracker_name = normalize_county(f.county_raw)
        row.update(
            {
                "source": f.source,
                "source_id": f.institution,
                "name": f.name,
                "county": tracker_name or "",
                "county_fips": fips_by_name.get(tracker_name, ""),
                "stage": f.stage,
                "city": f.city,
                "source_url": f.source_url,
                "note": f.note,
            }
        )
        rows.append(row)
    return rows


def run(
    out_path: Path,
    *,
    max_lookups: int | None = None,
    skip_frs: bool = False,
    skip_epicenter: bool = False,
    verbose: bool = True,
) -> Path:
    """Run the full pipeline and write the deliverable workbook.

    Args:
        out_path: where to write the ``.xlsx``.
        max_lookups: cap FRS per-ID lookups, for quick test runs.
        skip_frs: skip the FRS pass. FRS requires thousands of per-ID lookups and
            takes far longer than EPD, so this allows a fast EPD-only rebuild.
        skip_epicenter: skip the EPIcenter pass. Useful while its redistribution
            terms are still being confirmed with Georgia Tech.
        verbose: print progress.
    """
    ensure_reference()
    pulled_on = date.today().isoformat()
    counties = load_reference()
    county_values: dict[str, dict[str, object]] = {c.tracker_name: {} for c in counties}
    original_rows: list[dict[str, object]] = []
    variables: list[Variable] = []

    # --- Georgia EPD air permits ------------------------------------------------
    if verbose:
        print("Scraping Georgia EPD air permits (permitted facilities)...")
    permits = ga_epd_air.scrape_data_center_permits(verbose=verbose)
    epd_facilities = ga_epd_air.permits_to_facilities(permits)

    # Addresses live in the permit PDFs, not the search grid. Cached on disk, so
    # this is a no-op after the first run.
    if verbose:
        print("Reading facility addresses from permit PDFs...")
    epd_addresses = epd_permit_docs.fetch_addresses(epd_facilities, verbose=False)
    if verbose:
        print(f"  {len(epd_addresses)}/{len(epd_facilities)} facilities have an address")
        for airs, derived, printed in epd_permit_docs.county_disagreements(
            epd_addresses, epd_facilities
        ):
            print(f"  WARNING {airs}: AIRS says {derived}, permit says {printed}")
    epd_counts = ga_epd_air.facilities_to_county_counts(epd_facilities)
    epd_recent = ga_epd_air.facilities_to_recent_county_counts(
        epd_facilities, since_year=BUILDOUT_START_YEAR
    )
    for county in counties:
        county_values[county.tracker_name]["dc_permitted_n"] = epd_counts[county.tracker_name]
        county_values[county.tracker_name]["dc_permitted_recent_n"] = epd_recent[
            county.tracker_name
        ]
    original_rows += _epd_original_rows(epd_facilities, epd_addresses)
    variables += [
        Variable(
            varname="dc_permitted_n",
            definition=(
                "Count of data center facilities in the county holding a Georgia EPD "
                "air permit, cumulative across all issuance years."
            ),
            units="facilities",
            source="Georgia EPD Air Protection Branch, Air Permit Search Engine",
            vintage="current permit database snapshot",
            date_pulled=pulled_on,
            original_name="Issued air permits, SIC 7374 (Data Processing and Preparation)",
            transformations=(
                "Searched by SIC code 7374; county derived from the 3-digit county FIPS "
                "prefix of the AIRS number; permit records collapsed to one row per "
                "facility (AIRS number); counted by county."
            ),
        ),
        Variable(
            varname="dc_permitted_recent_n",
            definition=(
                "Count of data center facilities in the county whose first Georgia EPD "
                f"air permit was issued in {BUILDOUT_START_YEAR} or later."
            ),
            units="facilities",
            source="Georgia EPD Air Protection Branch, Air Permit Search Engine",
            vintage="current permit database snapshot",
            date_pulled=pulled_on,
            original_name="Issued air permits, SIC 7374 (Data Processing and Preparation)",
            transformations=(
                "As dc_permitted_n, then restricted to facilities whose earliest permit "
                f"issuance date falls in {BUILDOUT_START_YEAR} or later. Separates the "
                "current buildout from the pre-existing facility stock."
            ),
        ),
    ]

    # --- EPA FRS ----------------------------------------------------------------
    if not skip_frs:
        if verbose:
            print("Scraping EPA FRS (federally registered facilities)...")
        frs_records = epa_frs.scrape_georgia_data_centers(
            max_lookups=max_lookups, verbose=verbose
        )
        frs_counts = epa_frs.records_to_county_counts(frs_records)
        for county in counties:
            county_values[county.tracker_name]["dc_frs_n"] = frs_counts[county.tracker_name]
        original_rows += _frs_original_rows(frs_records)
        variables.append(
            Variable(
                varname="dc_frs_n",
                definition=(
                    "Count of facilities in the county listed in the EPA Facility Registry "
                    "Service under NAICS 518210 (Data Processing, Hosting, and Related "
                    "Services). An independent federal cross-check on the EPD permit count."
                ),
                units="facilities",
                source="EPA Facility Registry Service (FRS)",
                vintage="current FRS snapshot",
                date_pulled=pulled_on,
                original_name="NAICS 518210 facilities, FRS",
                transformations=(
                    "Filtered to Georgia; county-matched by FIPS; deduplicated by registry_id."
                ),
            )
        )

    # --- Georgia Tech EPIcenter: local government response -----------------------
    if not skip_epicenter:
        if verbose:
            print("Fetching Georgia Tech EPIcenter Ordinance Hub (local response)...")
        hub = epicenter.fetch_hub_data(verbose=verbose)
        unresolved = epicenter.unresolved_moratoria(hub.moratoria)
        if unresolved and verbose:
            print(
                "  manual review: moratoria whose jurisdiction did not resolve to a "
                f"county: {[m.jurisdiction for m in unresolved]}"
            )
        ordinance_flags = epicenter.regulations_to_ordinance_flags(hub.regulations)
        stage_counts = epicenter.points_to_stage_counts(
            hub.facility_points, verbose=verbose
        )
        moratoria_ever = epicenter.moratoria_to_county_counts(hub.moratoria)
        moratoria_active = epicenter.moratoria_to_county_counts(
            hub.moratoria, active_on=date.today()
        )
        for county in counties:
            name = county.tracker_name
            county_values[name].update(stage_counts[name])
            county_values[name]["dc_ordinance"] = ordinance_flags[name]
            county_values[name]["dc_moratorium_n"] = moratoria_ever[name]
            county_values[name]["dc_moratorium_active_n"] = moratoria_active[name]
            county_values[name]["dc_local_action"] = int(
                ordinance_flags[name] == 1 or moratoria_ever[name] > 0
            )
        _EPIC_STAGE_DOCS = {
            "dc_mapped_n": (
                "Count of data center facilities mapped in the county at any "
                "development stage: operational, under construction, or planned.",
                "One row per facility from the Hub's development symbol map; each "
                "point's latitude and longitude resolved to a county via the Census "
                "geocoder, then counted by county. Not taken from the regulations "
                "choropleth, whose stage columns are 0/1 presence flags rather than "
                "counts.",
            ),
            "dc_operational_n": (
                "Count of data center facilities in the county that are operating.",
                "As dc_mapped_n, restricted to points whose published stage is "
                "'operational'.",
            ),
            "dc_construction_n": (
                "Count of data center facilities in the county under construction.",
                "As dc_mapped_n, restricted to points whose published stage is "
                "'construction'.",
            ),
            "dc_planned_n": (
                "Count of data center facilities in the county that are announced or "
                "planned but not yet under construction.",
                "As dc_mapped_n, restricted to points whose published stage is "
                "'planned'.",
            ),
        }
        variables += [
            Variable(
                varname=varname,
                definition=definition,
                units="facilities",
                source=epicenter.ATTRIBUTION,
                vintage="current Hub snapshot",
                date_pulled=pulled_on,
                original_name="Data Center Development in Georgia (per-facility symbol map)",
                transformations=transformation,
            )
            for varname, (definition, transformation) in _EPIC_STAGE_DOCS.items()
        ]
        variables += [
            Variable(
                varname="dc_ordinance",
                definition=(
                    "1 if the county has adopted a land-use ordinance addressing data "
                    "centers, 0 otherwise."
                ),
                units="flag (0/1)",
                source=epicenter.ATTRIBUTION,
                vintage="current Hub snapshot",
                date_pulled=pulled_on,
                original_name="Data Center Regulations in Georgia (county ordinance status)",
                transformations=(
                    "Read from the Hub's per-county regulation table, keyed by 5-digit "
                    "county FIPS and validated against the county reference table."
                ),
            ),
            Variable(
                varname="dc_moratorium_n",
                definition=(
                    "Count of data center moratoria adopted in the county, including "
                    "moratoria adopted by municipalities within it, and including "
                    "moratoria that have since expired."
                ),
                units="moratoria",
                source=epicenter.ATTRIBUTION,
                vintage="current Hub snapshot",
                date_pulled=pulled_on,
                original_name="Data Center Moratoria in Georgia",
                transformations=(
                    "County jurisdictions matched directly; municipal jurisdictions "
                    "assigned to their containing county via an explicit lookup table. "
                    "Expired moratoria are retained, because an expired moratorium is "
                    "still evidence that the community formally responded."
                ),
            ),
            Variable(
                varname="dc_moratorium_active_n",
                definition=(
                    "Count of data center moratoria in force in the county on the date "
                    "the dataset was pulled."
                ),
                units="moratoria",
                source=epicenter.ATTRIBUTION,
                vintage="current Hub snapshot",
                date_pulled=pulled_on,
                original_name="Data Center Moratoria in Georgia",
                transformations=(
                    "As dc_moratorium_n, restricted to moratoria whose start date has "
                    "passed and whose expiration date has not. A moratorium with no "
                    "parsable start date is excluded rather than assumed active."
                ),
            ),
            Variable(
                varname="dc_local_action",
                definition=(
                    "1 if the county has either a data center ordinance or a recorded "
                    "moratorium, 0 otherwise. A single flag for whether local government "
                    "has formally acted on data center siting."
                ),
                units="flag (0/1)",
                source=epicenter.ATTRIBUTION,
                vintage="current Hub snapshot",
                date_pulled=pulled_on,
                original_name="Derived",
                transformations=(
                    "Logical OR of dc_ordinance and dc_moratorium_n > 0. Unweighted and "
                    "deliberately simple, so it can be read without consulting a formula."
                ),
            ),
        ]

    # --- Institutional (campus) data centers -------------------------------------
    # Curated, not scraped: campus facilities appear in no statewide register. See
    # scrapers/institutional.py for why they are counted and why they are kept as a
    # separate variable rather than added to the EPIcenter count.
    if verbose:
        print("Loading institutional (campus) data center registry...")
    inst_facilities = institutional.load_registry()
    inst_counts = institutional.facilities_to_county_counts(inst_facilities)
    for county in counties:
        county_values[county.tracker_name]["dc_institutional_n"] = inst_counts[
            county.tracker_name
        ]
    original_rows += _institutional_original_rows(inst_facilities)
    variables.append(
        Variable(
            varname="dc_institutional_n",
            definition=(
                "Count of institutional data centers in the county: purpose-built "
                "facilities housing university or college research computing at data "
                "center scale. Counted separately because campus facilities appear in "
                "neither the state air permit record nor the commercial development "
                "map, and a county's full footprint is the union of this variable and "
                "dc_mapped_n, not their sum."
            ),
            units="facilities",
            source=institutional.SOURCE_NAME,
            vintage="compiled from public announcements and trade coverage",
            date_pulled=pulled_on,
            original_name="Institutional announcements and trade press (per-facility URLs on the Original sheet)",
            transformations=(
                "Hand-compiled against a published inclusion rule; each facility "
                "carries a public source URL, enforced in code, and is assigned to its "
                "county via the reference table."
            ),
        )
    )

    long_rows = build_long_rows(county_values)
    transformed_rows = build_transformed_rows(county_values)

    dataset = Dataset(
        original_rows=original_rows,
        long_rows=long_rows,
        transformed_rows=transformed_rows,
        variables=variables,
        notes=(
            "Phase 5 draft dataset. Facility counts by stage from the Georgia Tech "
            "EPIcenter development map; permitted facilities with dates from Georgia "
            "EPD air permits; institutional (campus) facilities from a curated, "
            "source-cited registry; local government response from the EPIcenter "
            "Ordinance Hub. Facility variables are NOT additive: see the additivity "
            "rules in docs/data_dictionary.md. EPIcenter-derived variables are "
            "attributed to Georgia Tech and their redistribution terms are pending "
            "confirmation."
        ),
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
        help="Cap FRS per-ID lookups for a quick test run (default: process all).",
    )
    parser.add_argument(
        "--skip-frs",
        action="store_true",
        help="Skip the slow EPA FRS pass and build from Georgia EPD only.",
    )
    parser.add_argument(
        "--skip-epicenter",
        action="store_true",
        help="Skip the Georgia Tech EPIcenter pass (local ordinance and moratorium data).",
    )
    args = parser.parse_args()
    run(
        args.out,
        max_lookups=args.max_lookups,
        skip_frs=args.skip_frs,
        skip_epicenter=args.skip_epicenter,
    )


if __name__ == "__main__":
    main()
