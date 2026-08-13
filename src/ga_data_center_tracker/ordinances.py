"""Ordinance and moratorium dataset, delivered in the Solutions Tracker format.

The main workbook carries local-government response as four county-level counts.
That is the right shape for a tracker measure, but it throws away the records
underneath: which jurisdiction adopted what, when it started, when it expired. A
county reading ``dc_moratorium_n = 1`` cannot tell you that the moratorium was
adopted by a city inside it, ran ninety days, and lapsed in May.

This module builds a companion workbook that keeps both. Same five sheets, same
county join key, so it loads exactly like the facility dataset, but its
``Original`` sheet is one row per ordinance or moratorium rather than one row per
facility.

**Six county-level variables**, two more than the main workbook carries:

  * ``dc_ordinance``              county has adopted a data center ordinance
  * ``dc_moratorium_n``           moratoria ever adopted, including expired ones
  * ``dc_moratorium_active_n``    in force on the pull date
  * ``dc_moratorium_expired_n``   adopted and since lapsed
  * ``dc_moratorium_city_n``      adopted by a municipality rather than the county
  * ``dc_local_action``           either an ordinance or a moratorium

The expired and municipal counts exist because both are load-bearing here and both
are invisible in a single total. Every one of Georgia's moratoria has now lapsed,
so a reader who sees only ``dc_moratorium_active_n`` would conclude nothing ever
happened. And a moratorium adopted by a city is recorded against its county, which
is correct for a county-level tracker but hides that the county itself never acted.

Source: Georgia Tech EPIcenter's Georgia Data Center Ordinance Hub, attributed
throughout. See ``docs/methodology.md``.

Run:  ``python -m ga_data_center_tracker.ordinances --out data/processed/ga_data_center_ordinances.xlsx``
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .counties import load_reference
from .delivery import (
    Dataset,
    Variable,
    build_long_rows,
    build_transformed_rows,
    write_workbook,
)
from .scrapers import epicenter

ORIGINAL_COLUMNS = [
    "record_type",       # "ordinance" or "moratorium"
    "jurisdiction",      # as published, e.g. "Griffin, GA"
    "jurisdiction_type", # "county" or "city"
    "county",
    "county_fips",
    "start_date",
    "expiration_date",
    "status",            # "active", "expired", or "adopted" for ordinances
    "note",
    "source",
]


def _moratorium_status(m, on: date) -> str:
    if m.is_active(on):
        return "active"
    if m.expiration_date and m.expiration_date < on:
        return "expired"
    return "unknown"


def build(hub: epicenter.HubData, *, on: date | None = None) -> Dataset:
    """Assemble the ordinance dataset from a Hub fetch."""
    on = on or date.today()
    counties = load_reference()
    fips_by_name = {c.tracker_name: c.fips for c in counties}
    pulled_on = on.isoformat()

    ordinance_flags = epicenter.regulations_to_ordinance_flags(hub.regulations)
    moratoria_ever = epicenter.moratoria_to_county_counts(hub.moratoria)
    moratoria_active = epicenter.moratoria_to_county_counts(hub.moratoria, active_on=on)

    expired: dict[str, int] = {c.tracker_name: 0 for c in counties}
    by_city: dict[str, int] = {c.tracker_name: 0 for c in counties}
    for m in hub.moratoria:
        if not m.county or m.county not in expired:
            continue
        if _moratorium_status(m, on) == "expired":
            expired[m.county] += 1
        if m.jurisdiction_type == "city":
            by_city[m.county] += 1

    county_values: dict[str, dict[str, object]] = {}
    for c in counties:
        name = c.tracker_name
        county_values[name] = {
            "dc_ordinance": ordinance_flags[name],
            "dc_moratorium_n": moratoria_ever[name],
            "dc_moratorium_active_n": moratoria_active[name],
            "dc_moratorium_expired_n": expired[name],
            "dc_moratorium_city_n": by_city[name],
            "dc_local_action": int(ordinance_flags[name] == 1 or moratoria_ever[name] > 0),
        }

    # --- Original sheet: the records themselves -------------------------------
    original: list[dict[str, object]] = []
    for m in sorted(hub.moratoria, key=lambda x: (x.county or "zz", x.jurisdiction)):
        row = {col: "" for col in ORIGINAL_COLUMNS}
        row.update(
            {
                "record_type": "moratorium",
                "jurisdiction": m.jurisdiction,
                "jurisdiction_type": m.jurisdiction_type,
                "county": m.county or "",
                "county_fips": fips_by_name.get(m.county or "", ""),
                "start_date": m.start_date.isoformat() if m.start_date else "",
                "expiration_date": m.expiration_date.isoformat() if m.expiration_date else "",
                "status": _moratorium_status(m, on),
                "note": m.note,
                "source": epicenter.ATTRIBUTION,
            }
        )
        original.append(row)

    # Ordinance counties carry no per-record detail upstream; the Hub publishes a
    # flag per county rather than the ordinance text or its adoption date. One row
    # each, so the record exists and its thinness is visible rather than implied.
    for r in sorted(hub.regulations, key=lambda x: x.county or "zz"):
        if not r.has_ordinance or not r.county:
            continue
        row = {col: "" for col in ORIGINAL_COLUMNS}
        row.update(
            {
                "record_type": "ordinance",
                "jurisdiction": r.county,
                "jurisdiction_type": "county",
                "county": r.county,
                "county_fips": r.county_fips,
                "status": "adopted",
                "note": "Hub publishes an adoption flag per county, without a date.",
                "source": epicenter.ATTRIBUTION,
            }
        )
        original.append(row)

    src = epicenter.ATTRIBUTION
    variables = [
        Variable(
            varname="dc_ordinance",
            definition="1 if the county has adopted a land-use ordinance addressing data centers, 0 otherwise.",
            units="flag (0/1)", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Data Center Regulations in Georgia (county ordinance status)",
            transformations="Read from the Hub's per-county regulation table, keyed by 5-digit county FIPS.",
        ),
        Variable(
            varname="dc_moratorium_n",
            definition=(
                "Count of data center moratoria adopted in the county, including those adopted by "
                "municipalities within it, and including moratoria that have since expired."
            ),
            units="moratoria", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Data Center Moratoria in Georgia",
            transformations=(
                "County jurisdictions matched directly; municipal jurisdictions assigned to their "
                "containing county via an explicit lookup. Expired moratoria retained, because an "
                "expired moratorium is still evidence the community formally responded."
            ),
        ),
        Variable(
            varname="dc_moratorium_active_n",
            definition="Count of moratoria in force in the county on the date the dataset was pulled.",
            units="moratoria", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Data Center Moratoria in Georgia",
            transformations=(
                "As dc_moratorium_n, restricted to moratoria whose start date has passed and whose "
                "expiration date has not. A moratorium with no parsable start date is excluded "
                "rather than assumed active."
            ),
        ),
        Variable(
            varname="dc_moratorium_expired_n",
            definition="Count of moratoria adopted in the county that have since lapsed.",
            units="moratoria", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Data Center Moratoria in Georgia",
            transformations=(
                "Moratoria whose expiration date falls before the pull date. Reported separately "
                "because every Georgia moratorium has now lapsed, so the active count alone reads "
                "as though nothing ever happened."
            ),
        ),
        Variable(
            varname="dc_moratorium_city_n",
            definition=(
                "Count of the county's moratoria that were adopted by a municipality within it "
                "rather than by the county government."
            ),
            units="moratoria", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Data Center Moratoria in Georgia",
            transformations=(
                "Jurisdictions published as cities, assigned to their containing county. Separated "
                "because a city moratorium counted at county level would otherwise imply the county "
                "itself acted."
            ),
        ),
        Variable(
            varname="dc_local_action",
            definition=(
                "1 if the county has either a data center ordinance or a recorded moratorium, 0 "
                "otherwise. A single flag for whether local government has formally acted."
            ),
            units="flag (0/1)", source=src, vintage="current Hub snapshot", date_pulled=pulled_on,
            original_name="Derived",
            transformations="Logical OR of dc_ordinance and dc_moratorium_n > 0. Unweighted and deliberately simple.",
        ),
    ]

    return Dataset(
        original_rows=original,
        long_rows=build_long_rows(county_values),
        transformed_rows=build_transformed_rows(county_values),
        variables=variables,
        notes=(
            "Local government response to data center siting, by county. Companion to the facility "
            "dataset and built on the same county join key. Source: Georgia Tech EPIcenter's Georgia "
            "Data Center Ordinance Hub, attributed throughout; redistribution terms pending "
            "confirmation. The Original sheet carries one row per ordinance or moratorium."
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ordinance and moratorium dataset.")
    parser.add_argument(
        "--out", type=Path, default=Path("data/processed/ga_data_center_ordinances.xlsx")
    )
    args = parser.parse_args()

    print("Fetching the Georgia Tech EPIcenter Ordinance Hub...")
    hub = epicenter.fetch_hub_data(verbose=True)
    unresolved = epicenter.unresolved_moratoria(hub.moratoria)
    if unresolved:
        print(f"  manual review: {[m.jurisdiction for m in unresolved]}")

    dataset = build(hub)
    written = write_workbook(dataset, args.out)
    ords = sum(1 for r in dataset.original_rows if r["record_type"] == "ordinance")
    mors = sum(1 for r in dataset.original_rows if r["record_type"] == "moratorium")
    print(f"\n{ords} ordinances, {mors} moratoria -> {written}")


if __name__ == "__main__":
    main()
