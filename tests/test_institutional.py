"""Tests for the curated institutional (campus) data center registry.

The registry is hand-maintained, which is exactly why it needs tests: the
guardrails that keep an unsourced or misfiled facility out of the published
dataset are the only thing standing between a typo and a bad public number.
"""

from __future__ import annotations

import pytest

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.scrapers.institutional import (
    REGISTRY,
    InstitutionalFacility,
    facilities_to_county_counts,
    load_registry,
)


def _facility(**overrides) -> InstitutionalFacility:
    """A valid registry entry, with fields overridable per test."""
    defaults = {
        "name": "Test Data Center",
        "institution": "Test University",
        "county_raw": "Fulton County",
        "city": "Atlanta",
        "stage": "operational",
        "source_url": "https://example.edu/announcement",
    }
    return InstitutionalFacility(**{**defaults, **overrides})


class TestRegistryValidation:
    """Every rule that keeps a bad hand-entered record out of the dataset."""

    def test_shipped_registry_validates(self):
        assert load_registry() == REGISTRY

    def test_every_shipped_entry_has_a_public_source_url(self):
        # The core promise of a curated source: a reader can check every row.
        for facility in REGISTRY:
            assert facility.source_url.startswith("https://"), facility.name

    def test_missing_source_url_raises(self):
        with pytest.raises(ValueError, match="no source_url"):
            load_registry([_facility(source_url="")])

    def test_whitespace_only_source_url_raises(self):
        with pytest.raises(ValueError, match="no source_url"):
            load_registry([_facility(source_url="   ")])

    def test_unknown_stage_raises(self):
        with pytest.raises(ValueError, match="stage"):
            load_registry([_facility(stage="under construction")])

    def test_county_outside_georgia_raises(self):
        # Guards the failure mode this source is most exposed to: a well-known
        # institution that is not actually in Georgia.
        with pytest.raises(ValueError, match="does not resolve"):
            load_registry([_facility(county_raw="Wake County")])

    def test_nonsense_county_raises(self):
        with pytest.raises(ValueError, match="does not resolve"):
            load_registry([_facility(county_raw="Not A County")])


class TestCountyCounts:
    def test_all_counties_present_and_zero_filled(self):
        counts = facilities_to_county_counts(load_registry())
        assert len(counts) == GEORGIA_COUNTY_COUNT
        assert counts["Echols County, Georgia"] == 0

    def test_counts_match_the_registry_total(self):
        counts = facilities_to_county_counts(load_registry())
        assert sum(counts.values()) == len(REGISTRY)

    def test_multiple_facilities_in_one_county_accumulate(self):
        counts = facilities_to_county_counts(
            [_facility(name="A"), _facility(name="B"), _facility(name="C")]
        )
        assert counts["Fulton County, Georgia"] == 3

    def test_county_name_is_normalized_to_tracker_form(self):
        # Registry entries are written as "Clarke County"; the join key is the
        # full tracker form, and nothing hand-types it.
        counts = facilities_to_county_counts([_facility(county_raw="Clarke County")])
        assert counts["Clarke County, Georgia"] == 1


# --- Overlap with the permit record -------------------------------------------
#
# A campus data center is not automatically absent from the state permit record.
# Coda holds one under "Data Center Atlanta, LLC", a name that never mentions
# Georgia Tech, so the two records were only connected by street address. Counting
# it in both places inflated the statewide union by one, and these pin the fix.

from ga_data_center_tracker.scrapers.institutional import (  # noqa: E402
    facilities_not_already_counted,
)


def test_coda_records_its_permit_overlap():
    coda = next(f for f in REGISTRY if "Coda" in f.name)
    assert coda.epd_airs_number == "121-00941"


def test_facilities_without_an_overlap_have_no_airs_number():
    for f in REGISTRY:
        if "Coda" not in f.name:
            assert f.epd_airs_number == ""


def test_overlapping_facilities_are_excluded_from_the_union():
    fresh = facilities_not_already_counted(load_registry())
    names = {f.name for f in fresh}
    assert "Coda Data Center" not in names
    assert {"Boyd Data Center", "Horizon supercomputer site"} <= names


def test_county_counts_still_include_the_overlapping_facility():
    # dc_institutional_n answers "how many institutional data centers does this
    # county have," and Fulton has two. Only the statewide union deduplicates.
    counts = facilities_to_county_counts(load_registry())
    assert counts["Fulton County, Georgia"] == 2


def test_overlap_marker_survives_validation():
    assert len(load_registry()) == len(REGISTRY)
