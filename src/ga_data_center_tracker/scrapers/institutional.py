"""Institutional (campus) data center registry.

Georgia's university and college data centers are largely invisible to the other
sources in this pipeline. Most do not appear in the Georgia EPD air permit record,
because a campus facility's backup generation usually falls under the permitting
threshold that catches a commercial hyperscale campus. They do not appear on the
Georgia Tech EPIcenter development map, which tracks the commercial buildout. And
they are not listed in commercial catalogs, which track leasable colocation space
rather than owner-occupied research infrastructure.

**"Largely," not "entirely," and the exception is instructive.** Coda does hold a
state air permit, filed as "Data Center Atlanta, LLC" (AIRS 121-00941). Nothing in
that name says Georgia Tech, which is exactly why the connection was missed until
the facility's street address was read out of the permit PDF. So a campus facility
can be in the state record and still be effectively invisible, hiding behind an
operating-company name. That is a naming problem rather than a coverage problem,
and it is why ``epd_airs_number`` exists: to record the overlap once found, so the
same building is not counted twice.

Boyd (UGA) and the Horizon site (Morehouse) have no permit record at all. Clarke
County registers zero data centers in every other source in this project and
houses the University of Georgia's central research computing facility.

So institutional facilities are counted, and this module is the registry that
holds them.

**Why this source is curated rather than scraped.** There is no statewide register
of campus data centers to scrape. Each facility is documented in institutional
announcements, press releases, and trade coverage instead. The registry is
therefore assembled by hand, with one hard rule enforced in code: every record
must carry a public ``source_url``. ``load_registry`` raises on a record without
one, so an unsourced facility cannot reach the published dataset even by accident.

**Why this count is not summed into the EPIcenter facility count.** Whether
EPIcenter's development map already includes any of these facilities has not been
verified facility by facility. Adding the two counts would risk double-counting a
county. ``dc_institutional_n`` is therefore published as its own variable, and the
methodology states that a county's full footprint is the union of the two, not the
sum. See ``docs/methodology.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..counties import load_reference, normalize_county

SOURCE_NAME = "Institutional data center registry (curated, see docs/methodology.md)"

# Development stages, matching the vocabulary the EPIcenter-derived variables use.
STAGES = {"operational", "construction", "planned"}


@dataclass(frozen=True)
class InstitutionalFacility:
    """One campus or institutional data center."""

    name: str
    institution: str
    county_raw: str          # "Fulton County", resolved against the reference table
    city: str
    stage: str               # one of STAGES
    source_url: str
    note: str = ""
    source: str = SOURCE_NAME
    # Set when this facility ALSO appears in the Georgia EPD permit record, with the
    # AIRS number that proves it. A campus data center is not automatically absent
    # from the state record: Coda holds a permit under an operating-company name
    # that gives no hint it is Georgia Tech's. Recording the overlap is what stops
    # the statewide union from counting the same building twice.
    epd_airs_number: str = ""


# The registry. Every entry is verifiable from its source_url.
#
# Inclusion rule (see docs/methodology.md): a purpose-built facility housing
# institutionally operated compute at data center scale. A departmental server
# closet or a rack in a wiring room does not qualify. A named, sited machine room
# built to house a research computing system does.
REGISTRY: list[InstitutionalFacility] = [
    InstitutionalFacility(
        name="Coda Data Center",
        institution="Georgia Institute of Technology",
        county_raw="Fulton County",
        city="Atlanta",
        stage="operational",
        source_url="https://ece.gatech.edu/news/2023/12/georgia-tech-award-equips-codas-data-center-new-supercomputer",
        epd_airs_number="121-00941",
        note=(
            "Data center in the Coda building at 756 West Peachtree Street NW, Tech "
            "Square. 9.6 MW. Home of PACE, the Phoenix and Hive clusters. ALSO in the "
            "state permit record as 'Data Center Atlanta, LLC' (AIRS 121-00941), a "
            "name that gives no indication it is Georgia Tech's; the two were "
            "connected by street address, not by name."
        ),
    ),
    InstitutionalFacility(
        name="Horizon supercomputer site",
        institution="Morehouse College",
        county_raw="Fulton County",
        city="Atlanta",
        stage="planned",
        source_url="https://www.datacenterdynamics.com/en/news/atlantas-morehouse-college-receives-5m-grant-from-nsf-to-house-supercomputer/",
        note=(
            "Site to house Horizon, part of the NSF Leadership-Class Computing "
            "Facility. Initial $5M NSF award for site construction. Stage is 'planned' "
            "rather than 'construction' pending a public construction-start date."
        ),
    ),
    InstitutionalFacility(
        name="Boyd Data Center",
        institution="University of Georgia",
        county_raw="Clarke County",
        city="Athens",
        stage="operational",
        source_url="https://www.datacenterdynamics.com/en/news/university-of-georgia-invests-24m-in-26-gpus-and-3tb-memory-nodes-for-sapelo2-hpc-cluster/",
        note=(
            "Houses the GACRC Sapelo2 cluster, 38,000+ cores, with a $2.4M GPU "
            "expansion. The university's central research computing facility."
        ),
    ),
]


def load_registry(
    registry: list[InstitutionalFacility] | None = None,
) -> list[InstitutionalFacility]:
    """Validate the registry and return it.

    Enforces the two rules that keep this source publishable: every record carries
    a public source URL, and every record's county and stage resolve against the
    project's own vocabularies. Any violation raises, because a curated source with
    a silently bad row is worse than one that refuses to build.
    """
    records = REGISTRY if registry is None else registry
    valid_counties = {c.tracker_name for c in load_reference()}
    for facility in records:
        if not facility.source_url.strip():
            raise ValueError(
                f"Institutional registry entry {facility.name!r} has no source_url. "
                "Every institutional facility must be publicly verifiable."
            )
        if facility.stage not in STAGES:
            raise ValueError(
                f"Institutional registry entry {facility.name!r} has stage "
                f"{facility.stage!r}; expected one of {sorted(STAGES)}."
            )
        tracker_name = normalize_county(facility.county_raw)
        if tracker_name is None or tracker_name not in valid_counties:
            raise ValueError(
                f"Institutional registry entry {facility.name!r} has county "
                f"{facility.county_raw!r}, which does not resolve to a Georgia county."
            )
    return list(records)


def facilities_not_already_counted(
    facilities: list[InstitutionalFacility],
) -> list[InstitutionalFacility]:
    """Institutional facilities that no other source in this pipeline already has.

    Used when totalling facilities statewide. ``dc_institutional_n`` deliberately
    counts every campus facility, because "how many institutional data centers does
    this county have" is a real question. But a facility that also holds a state air
    permit is already inside ``dc_permitted_n``, so adding it again would inflate the
    union. Coda is the case that proves the point: it is a campus data center *and*
    a permitted one.
    """
    return [f for f in facilities if not f.epd_airs_number]


def facilities_to_county_counts(
    facilities: list[InstitutionalFacility],
) -> dict[str, int]:
    """Per-county count of institutional data centers, zero-filled to all 159."""
    counts = {c.tracker_name: 0 for c in load_reference()}
    for facility in facilities:
        tracker_name = normalize_county(facility.county_raw)
        if tracker_name in counts:
            counts[tracker_name] += 1
    return counts
