"""Tests for the county reference layer."""

from __future__ import annotations

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.counties import (
    County,
    load_reference,
    name_to_fips,
    normalize_county,
)


def test_reference_has_all_counties():
    counties = load_reference()
    assert len(counties) == GEORGIA_COUNTY_COUNT


def test_reference_fips_are_georgia_and_unique():
    counties = load_reference()
    fips = [c.fips for c in counties]
    assert all(f.startswith("13") and len(f) == 5 for f in fips)
    assert len(set(fips)) == GEORGIA_COUNTY_COUNT


def test_tracker_name_format():
    fulton = County(name="Fulton County", fips="13121")
    assert fulton.tracker_name == "Fulton County, Georgia"


def test_known_fips_present():
    mapping = {c.name: c.fips for c in load_reference()}
    assert mapping["Fulton County"] == "13121"
    assert mapping["DeKalb County"] == "13089"


def test_normalize_county_variants():
    assert normalize_county("Fulton") == "Fulton County, Georgia"
    assert normalize_county("fulton county") == "Fulton County, Georgia"
    assert normalize_county("FULTON COUNTY, GEORGIA") == "Fulton County, Georgia"
    assert normalize_county("Not A County") is None
    assert normalize_county("") is None


def test_name_to_fips_accepts_multiple_forms():
    mapping = name_to_fips()
    assert mapping["fulton"] == "13121"
    assert mapping["fulton county"] == "13121"
    assert mapping["fulton county, georgia"] == "13121"
