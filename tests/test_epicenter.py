"""Tests for the Georgia Tech EPIcenter Ordinance Hub scraper.

Covers the parsing and aggregation layer: chart discovery from the Hub page, the
moratoria table's unnamed jurisdiction column, city-to-county assignment, the
active-on-date logic, and the ordinance flag. Network calls are not exercised.
"""

from __future__ import annotations

from datetime import date

import pytest

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.scrapers.epicenter import (
    Moratorium,
    _parse_date,
    _resolve_jurisdiction,
    discover_chart_urls,
    moratoria_to_county_counts,
    parse_moratoria,
    parse_regulations,
    points_to_stage_counts,
    regulations_to_ordinance_flags,
    unresolved_moratoria,
)

HUB_PAGE = """
<iframe title="Data Center Regulations in Georgia" aria-label="Choropleth map"
        src="https://datawrapper.dwcdn.net/i9rPV/3/"></iframe>
<iframe title="Data Center Development in Georgia" aria-label="Symbol map"
        src="https://datawrapper.dwcdn.net/rdchq/2/"></iframe>
<iframe title="States Represented in the Ordinance Hub"
        src=https://datawrapper.dwcdn.net/CoEp0/1/></iframe>
<iframe title="Data Center Moratoria in Georgia" aria-label="Range Plot"
        src="https://datawrapper.dwcdn.net/Fu9Uy/1/"></iframe>
"""

# The jurisdiction column really is published with an empty header.
MORATORIA_ROWS = [
    {
        "": "Troup County, GA",
        "Moratorium Start Date": "September 16, 2025",
        "Moratorium Expiration Date": "March 2, 2026",
        "Note": "90-day moratorium, extended for 90 more days",
    },
    {
        "": "Griffin, GA",
        "Moratorium Start Date": "January 13, 2026",
        "Moratorium Expiration Date": "July 12, 2026",
        "Note": "180-day moratorium",
    },
]

REGULATION_ROWS = [
    {"Five-Digit Code": "13121", "Operational": "1", "Under construction": "0",
     "Planned": "0", "Status": "A"},
    {"Five-Digit Code": "13045", "Operational": "1", "Under construction": "0",
     "Planned": "0", "Status": ""},
    {"Five-Digit Code": "13117", "Operational": "", "Under construction": "",
     "Planned": "", "Status": "A"},
]


def test_discover_chart_urls_finds_each_role():
    charts = discover_chart_urls(HUB_PAGE)
    assert charts["regulations"] == "https://datawrapper.dwcdn.net/i9rPV/3"
    assert charts["moratoria"] == "https://datawrapper.dwcdn.net/Fu9Uy/1"
    # Unquoted src attributes appear on the page and must still be matched.
    assert charts["development"] == "https://datawrapper.dwcdn.net/rdchq/2"


def test_parse_date_reads_long_form_dates():
    assert _parse_date("February 17, 2026") == date(2026, 2, 17)
    assert _parse_date("") is None


def test_resolve_jurisdiction_handles_counties_and_cities():
    assert _resolve_jurisdiction("Troup County, GA") == ("county", "Troup County, Georgia")
    assert _resolve_jurisdiction("Griffin, GA") == ("city", "Spalding County, Georgia")
    # An unknown city resolves to no county so it routes to manual review.
    assert _resolve_jurisdiction("Nowhere, GA") == ("city", None)


def test_parse_moratoria_reads_the_unnamed_jurisdiction_column():
    moratoria = parse_moratoria(MORATORIA_ROWS)
    assert len(moratoria) == 2
    assert moratoria[0].county == "Troup County, Georgia"
    assert moratoria[0].start_date == date(2025, 9, 16)
    # A city moratorium is recorded against its containing county.
    assert moratoria[1].jurisdiction_type == "city"
    assert moratoria[1].county == "Spalding County, Georgia"
    assert unresolved_moratoria(moratoria) == []


def test_is_active_respects_the_window():
    moratorium = Moratorium(
        jurisdiction="Troup County, GA",
        jurisdiction_type="county",
        county="Troup County, Georgia",
        start_date=date(2025, 9, 16),
        expiration_date=date(2026, 3, 2),
    )
    assert moratorium.is_active(date(2025, 12, 1))
    assert not moratorium.is_active(date(2025, 9, 1))     # before it starts
    assert not moratorium.is_active(date(2026, 7, 22))    # after it expires


def test_is_active_does_not_assume_an_unparsed_start_date():
    moratorium = Moratorium(
        jurisdiction="Somewhere County, GA",
        jurisdiction_type="county",
        county="Fulton County, Georgia",
        start_date=None,
        expiration_date=None,
    )
    assert not moratorium.is_active(date(2026, 7, 22))


def test_moratoria_counts_are_dense_and_county_assigned():
    counts = moratoria_to_county_counts(parse_moratoria(MORATORIA_ROWS))
    assert len(counts) == GEORGIA_COUNTY_COUNT
    assert counts["Troup County, Georgia"] == 1
    assert counts["Spalding County, Georgia"] == 1   # Griffin's county
    assert counts["Appling County, Georgia"] == 0


def test_ordinance_flags_read_the_status_column():
    flags = regulations_to_ordinance_flags(parse_regulations(REGULATION_ROWS))
    assert len(flags) == GEORGIA_COUNTY_COUNT
    assert flags["Fulton County, Georgia"] == 1      # 13121, Status "A"
    assert flags["Barrow County, Georgia"] == 0      # 13013, absent from the table
    assert flags["Carroll County, Georgia"] == 0     # 13045, present but blank Status
    # A county can have an ordinance with no facility counts recorded.
    assert flags["Forsyth County, Georgia"] == 1     # 13117


def test_parse_regulations_resolves_every_fips_to_a_county():
    regulations = parse_regulations(REGULATION_ROWS)
    assert all(r.county is not None for r in regulations)


# --- Facility stage counts from the development map ---------------------------
#
# The regression these guard is the one that already bit once: the regulations
# choropleth carries columns named "Operational" / "Under construction" /
# "Planned" that look like counts and are actually 0/1 presence flags. Reading
# them as counts reports 27 facilities statewide instead of 123. Stage counts
# must come from the per-facility development map.

DEVELOPMENT_POINTS = [
    # Three facilities in one county, one per stage.
    {"latitude": "33.75", "longitude": "-84.39", "Status": "operational"},
    {"latitude": "33.76", "longitude": "-84.40", "Status": "operational"},
    {"latitude": "33.77", "longitude": "-84.41", "Status": "construction"},
    # A second county, one planned facility.
    {"latitude": "33.70", "longitude": "-84.75", "Status": "planned"},
    # Outside Georgia: must not be counted anywhere.
    {"latitude": "35.78", "longitude": "-78.64", "Status": "operational"},
    # A point with an unrecognized stage still counts toward the county total.
    {"latitude": "33.78", "longitude": "-84.42", "Status": ""},
]

_FAKE_FIPS = {
    "33.75,-84.39": "13121",
    "33.76,-84.40": "13121",
    "33.77,-84.41": "13121",
    "33.78,-84.42": "13121",
    "33.70,-84.75": "13097",
    "35.78,-78.64": "37183",   # Wake County, North Carolina
}


@pytest.fixture
def no_geocoding(monkeypatch):
    """Resolve points from a fixed table instead of calling the Census geocoder."""

    def fake_resolve(points, *, sleep=0.2, verbose=False):
        resolved = {}
        unresolved = 0
        for point in points:
            key = f"{point['latitude']},{point['longitude']}"
            fips = _FAKE_FIPS.get(key, "")
            if fips.startswith("13"):
                resolved[key] = fips
            else:
                unresolved += 1
        return resolved, unresolved

    monkeypatch.setattr(
        "ga_data_center_tracker.cleaning.reconcile.resolve_points", fake_resolve
    )


def test_stage_counts_are_dense_across_all_counties(no_geocoding):
    counts = points_to_stage_counts(DEVELOPMENT_POINTS)
    assert len(counts) == GEORGIA_COUNTY_COUNT
    assert counts["Echols County, Georgia"]["dc_mapped_n"] == 0


def test_stage_counts_count_facilities_not_county_flags(no_geocoding):
    # Fulton has three facilities at the same stage plus two others. A presence
    # flag would report 1 operational here; the map reports 2.
    fulton = points_to_stage_counts(DEVELOPMENT_POINTS)["Fulton County, Georgia"]
    assert fulton["dc_operational_n"] == 2
    assert fulton["dc_construction_n"] == 1
    assert fulton["dc_planned_n"] == 0


def test_county_total_includes_points_with_an_unreadable_stage(no_geocoding):
    # The blank-status point counts toward the total but no stage, so the stages
    # sum to less than the total rather than the point being dropped.
    fulton = points_to_stage_counts(DEVELOPMENT_POINTS)["Fulton County, Georgia"]
    assert fulton["dc_mapped_n"] == 4
    stages = ("dc_operational_n", "dc_construction_n", "dc_planned_n")
    assert sum(fulton[s] for s in stages) == 3


def test_out_of_state_points_are_dropped(no_geocoding):
    counts = points_to_stage_counts(DEVELOPMENT_POINTS)
    total = sum(c["dc_mapped_n"] for c in counts.values())
    assert total == len(DEVELOPMENT_POINTS) - 1


def test_stage_counts_split_across_counties(no_geocoding):
    counts = points_to_stage_counts(DEVELOPMENT_POINTS)
    assert counts["Douglas County, Georgia"]["dc_planned_n"] == 1
    assert counts["Douglas County, Georgia"]["dc_mapped_n"] == 1
