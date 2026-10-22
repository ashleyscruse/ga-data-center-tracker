"""Tests for the curated announced data center registry.

Same guardrails as the institutional registry: an unsourced or misfiled
hand-entered record must not reach the published dataset.
"""

from __future__ import annotations

import pytest

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.scrapers.announced import (
    REGISTRY,
    AnnouncedFacility,
    facilities_to_county_counts,
    load_registry,
)


def _facility(**overrides) -> AnnouncedFacility:
    defaults = {
        "name": "Test Campus",
        "developer": "Test Developer",
        "county_raw": "Effingham County",
        "city": "",
        "stage": "planned",
        "source_url": "https://example.com/announcement",
    }
    return AnnouncedFacility(**{**defaults, **overrides})


def test_shipped_registry_validates():
    assert load_registry() == REGISTRY


def test_every_shipped_entry_has_a_public_source_url():
    for facility in REGISTRY:
        assert facility.source_url.startswith("https://"), facility.name


def test_missing_source_url_raises():
    with pytest.raises(ValueError, match="no source_url"):
        load_registry([_facility(source_url=" ")])


def test_unknown_stage_raises():
    with pytest.raises(ValueError, match="stage"):
        load_registry([_facility(stage="under construction")])


def test_county_outside_georgia_raises():
    with pytest.raises(ValueError, match="does not resolve"):
        load_registry([_facility(county_raw="Jasper County, South Carolina")])


def test_counts_are_zero_filled_to_every_county():
    counts = facilities_to_county_counts([_facility()])
    assert len(counts) == GEORGIA_COUNTY_COUNT
    assert counts["Effingham County, Georgia"] == 1
    assert sum(counts.values()) == 1


def test_camellia_is_in_effingham():
    camellia = [f for f in REGISTRY if f.name == "Project Camellia"]
    assert len(camellia) == 1
    assert facilities_to_county_counts(camellia)["Effingham County, Georgia"] == 1
