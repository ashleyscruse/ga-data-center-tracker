"""Tests for cross-source reconciliation.

Covers the aggregation and the blind-spot logic. The Census geocoder is not called; point
resolution is exercised through a pre-seeded cache so the tests stay offline and fast.
"""

from __future__ import annotations

import json
from datetime import date

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.cleaning import reconcile
from ga_data_center_tracker.cleaning.reconcile import CountyComparison, Reconciliation
from ga_data_center_tracker.scrapers.ga_epd_air import FacilityRecord


def _epd(airs, county, fips):
    return FacilityRecord(
        airs_number=airs, name="Test Facility", county=county, county_fips=fips,
        first_permit_date=date(2025, 1, 1), latest_permit_date=date(2025, 1, 1),
        permit_count=1, permit_types="SIP", sic_code="7374",
    )


def _point(lat, lon, status):
    return {"latitude": lat, "longitude": lon, "Status": status}


# Two points in Fulton, one in Cobb. Cached so no network call happens.
POINTS = [
    _point("33.7500", "-84.4000", "operational"),
    _point("33.7600", "-84.4100", "planned"),
    _point("33.9000", "-84.5000", "operational"),
]
CACHE = {
    "33.7500,-84.4000": "13121",   # Fulton
    "33.7600,-84.4100": "13121",   # Fulton
    "33.9000,-84.5000": "13067",   # Cobb
}


def _seed_cache(tmp_path, monkeypatch):
    path = tmp_path / "point_county_cache.json"
    path.write_text(json.dumps(CACHE))
    monkeypatch.setattr(reconcile, "CACHE_PATH", path)


def test_reconcile_counts_each_source_by_county(tmp_path, monkeypatch):
    _seed_cache(tmp_path, monkeypatch)
    result = reconcile.reconcile(
        epd_facilities=[_epd("121-00001", "Fulton County, Georgia", "13121")],
        epicenter_points=POINTS,
    )
    by_name = {c.county: c for c in result.counties}
    fulton = by_name["Fulton County, Georgia"]
    assert fulton.epd_permitted == 1
    assert fulton.epicenter_total == 2
    assert fulton.epicenter_operational == 1
    assert fulton.epicenter_planned == 1
    assert by_name["Cobb County, Georgia"].epicenter_total == 1
    # Every county is present, so a tracked-but-empty county reads as zero.
    assert len(result.counties) == GEORGIA_COUNTY_COUNT
    assert result.unresolved_points == 0


def test_active_counties_excludes_the_empty_ones(tmp_path, monkeypatch):
    _seed_cache(tmp_path, monkeypatch)
    result = reconcile.reconcile(
        epd_facilities=[_epd("121-00001", "Fulton County, Georgia", "13121")],
        epicenter_points=POINTS,
    )
    assert {c.county for c in result.active_counties} == {
        "Fulton County, Georgia",
        "Cobb County, Georgia",
    }


def test_blind_spots_point_in_both_directions():
    result = Reconciliation(counties=[
        # EPIcenter maps facilities here, EPD has no permit.
        CountyComparison(county="Cobb County, Georgia", county_fips="13067",
                         epicenter_total=6, epicenter_operational=5,
                         epicenter_construction=1),
        # EPD permitted here, EPIcenter's map shows nothing.
        CountyComparison(county="Forsyth County, Georgia", county_fips="13117",
                         epd_permitted=1),
        # Both agree something is here; not a blind spot either way.
        CountyComparison(county="Fulton County, Georgia", county_fips="13121",
                         epd_permitted=9, epicenter_total=45),
        # Nothing anywhere; must not appear in either list.
        CountyComparison(county="Appling County, Georgia", county_fips="13001"),
    ])
    assert [c.county for c in result.epd_blind_spots()] == ["Cobb County, Georgia"]
    assert [c.county for c in result.epicenter_blind_spots()] == ["Forsyth County, Georgia"]


def test_gap_is_signed_so_both_directions_are_visible():
    epicenter_ahead = CountyComparison(county="Cobb County, Georgia", county_fips="13067",
                                       epd_permitted=0, epicenter_total=6)
    epd_ahead = CountyComparison(county="Forsyth County, Georgia", county_fips="13117",
                                 epd_permitted=1, epicenter_total=0)
    assert epicenter_ahead.gap == 6
    assert epd_ahead.gap == -1


def test_totals_sum_across_counties():
    result = Reconciliation(counties=[
        CountyComparison(county="Fulton County, Georgia", county_fips="13121",
                         epd_permitted=9, epicenter_total=45, epicenter_operational=35),
        CountyComparison(county="Cobb County, Georgia", county_fips="13067",
                         epicenter_total=6, epicenter_operational=5),
    ])
    totals = result.totals()
    assert totals["epd_permitted"] == 9
    assert totals["epicenter_total"] == 51
    assert totals["epicenter_operational"] == 40
    assert totals["counties_with_any_activity"] == 2
