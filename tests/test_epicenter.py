"""Tests for the Georgia Tech EPIcenter Ordinance Hub scraper.

Covers the parsing and aggregation layer: chart discovery from the Hub page, the
moratoria table's unnamed jurisdiction column, city-to-county assignment, the
active-on-date logic, and the ordinance flag. Network calls are not exercised.
"""

from __future__ import annotations

from datetime import date

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.scrapers.epicenter import (
    Moratorium,
    _parse_date,
    _resolve_jurisdiction,
    discover_chart_urls,
    moratoria_to_county_counts,
    parse_moratoria,
    parse_regulations,
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
