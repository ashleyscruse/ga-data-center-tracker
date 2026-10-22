"""Announced data center registry.

Facilities documented in public reporting that no other source in this pipeline
reaches. A newly announced campus can be months ahead of its first air permit and
of the development map, and a dataset meant to show where pressure is arriving
should not miss the largest project in the state because the paperwork lags.

This registry exists because of one such case. Project Camellia, OpenAI's campus
in Effingham County, was announced in July 2026. It holds no Georgia EPD air
permit under any SIC code as of the July 2026 permit pull and does not appear on
the EPIcenter development map. It was surfaced by the crosswalk against Science
for Georgia's data center map (``notebooks/crosswalk_science_for_georgia.py``).

Same rules as the institutional registry: curated by hand, every record carries a
public ``source_url``, and the build refuses a record without one. Facilities are
added here only when they are absent from every other source; once one appears in
the permit record or on the development map, its entry is removed so it is never
counted twice. ``dc_announced_n`` is therefore additive with the union of the
other facility variables.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..counties import load_reference, normalize_county

SOURCE_NAME = "Announced data center registry (curated, see docs/methodology.md)"

STAGES = {"operational", "construction", "planned"}


@dataclass(frozen=True)
class AnnouncedFacility:
    """One publicly announced data center absent from every other source."""

    name: str
    developer: str
    county_raw: str
    city: str
    stage: str
    source_url: str
    note: str = ""
    source: str = SOURCE_NAME


REGISTRY: list[AnnouncedFacility] = [
    AnnouncedFacility(
        name="Project Camellia",
        developer="OpenAI",
        county_raw="Effingham County",
        city="",
        stage="planned",
        source_url="https://thecurrentga.org/2026/07/22/20-billion-openai-data-center-to-open-in-effingham-county/",
        note=(
            "Campus between State Route 21 and Hodgeville Road, about 1,400 acres. "
            "Announced July 2026. No Georgia EPD air permit under any SIC code in "
            "Effingham County as of the July 2026 pull, and not on the EPIcenter "
            "development map. Listed as planned on Science for Georgia's map; "
            "site clearing has been reported, so stage moves to 'construction' "
            "once a public source confirms it."
        ),
    ),
]


def load_registry(
    registry: list[AnnouncedFacility] | None = None,
) -> list[AnnouncedFacility]:
    """Validate the registry and return it. Raises on any unsourced or unresolvable row."""
    records = REGISTRY if registry is None else registry
    valid_counties = {c.tracker_name for c in load_reference()}
    for facility in records:
        if not facility.source_url.strip():
            raise ValueError(
                f"Announced registry entry {facility.name!r} has no source_url. "
                "Every announced facility must be publicly verifiable."
            )
        if facility.stage not in STAGES:
            raise ValueError(
                f"Announced registry entry {facility.name!r} has stage "
                f"{facility.stage!r}; expected one of {sorted(STAGES)}."
            )
        tracker_name = normalize_county(facility.county_raw)
        if tracker_name is None or tracker_name not in valid_counties:
            raise ValueError(
                f"Announced registry entry {facility.name!r} has county "
                f"{facility.county_raw!r}, which does not resolve to a Georgia county."
            )
    return list(records)


def facilities_to_county_counts(facilities: list[AnnouncedFacility]) -> dict[str, int]:
    """Per-county count of announced facilities, zero-filled to all 159."""
    counts = {c.tracker_name: 0 for c in load_reference()}
    for facility in facilities:
        tracker_name = normalize_county(facility.county_raw)
        if tracker_name in counts:
            counts[tracker_name] += 1
    return counts
