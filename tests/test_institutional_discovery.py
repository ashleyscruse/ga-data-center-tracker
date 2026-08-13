"""Tests for the NSF-based institutional discovery pass.

The value of this module is entirely in its filters: it turns a noisy federal
award search into a short reviewable list. A filter that is silently too narrow
produces an empty worklist that looks like "there is nothing to find," which is
the worst possible failure here. These tests pin the filters against real award
titles pulled from the Georgia results. No network access.
"""

from __future__ import annotations

from ga_data_center_tracker.scrapers.institutional_discovery import (
    Candidate,
    format_report,
    is_computing_hardware,
    normalize_institution,
)

# Real titles from the Georgia award record.
CC_STAR = "CC* Compute: Integrating Georgia Tech into the Open Science Grid"
CC_CAMPUS = (
    "Research Infrastructure: CC* Compute-Campus: Pioneering Research-Oriented "
    "Flexible Cyberinfrastructure (PROFLEX-CI)"
)
CC_STORAGE = (
    "CC* Data Storage: High Volume Data Storage Infrastructure for Scientific "
    "Research and Education at Kennesaw State University"
)
MRI_HPC = (
    "MRI: Acquisition of an HPC System for Data-Driven Discovery in Computational "
    "Astrophysics, Biology, Chemistry, and Materials Science"
)
MRI_COMPUTING = "MRI Acquisition: Advanced Computing Infrastructure Driving long-tail Sciences"
MRI_CLUSTER = "MRI: Acquisition of a Computer Cluster for Bioinformatics Research at UGA"

MRI_SPECTROMETER = "MRI: Acquisition of a High-Resolution Mass Spectrometer (HRMS)"
MRI_MICROSCOPE = "MRI: Acquisition of a Lumicks C-Trap microscope for the study of proteins"
MRI_DIFFRACTOMETER = "MRI: Acquisition of a Single-Crystal X-ray Diffractometer"
RESEARCH_AWARD = "Collaborative Research: CDS&E-MSS: Local Approximation for Large Scale problems"
ICORPS = "I-Corps: Translation Potential of Tools for Simulation and Design"


class TestHardwareFilter:
    """Which award titles count as evidence of campus computing hardware."""

    def test_cc_star_titles_match(self):
        # The regression this file exists for. An earlier pattern put a word
        # boundary after "CC\*"; "*" is not a word character, so it could never
        # match the space that follows, and every CC* award in Georgia was
        # silently dropped. CC* is the program most likely to indicate a facility.
        assert is_computing_hardware(CC_STAR)
        assert is_computing_hardware(CC_CAMPUS)
        assert is_computing_hardware(CC_STORAGE)

    def test_mri_computing_titles_match(self):
        assert is_computing_hardware(MRI_HPC)
        assert is_computing_hardware(MRI_COMPUTING)
        assert is_computing_hardware(MRI_CLUSTER)

    def test_mri_instrument_titles_are_excluded(self):
        # MRI funds instruments of every kind; only the computing ones belong.
        assert not is_computing_hardware(MRI_SPECTROMETER)
        assert not is_computing_hardware(MRI_MICROSCOPE)
        assert not is_computing_hardware(MRI_DIFFRACTOMETER)

    def test_research_awards_that_merely_use_computing_are_excluded(self):
        # A grant that runs simulations is not a grant that built a facility.
        assert not is_computing_hardware(RESEARCH_AWARD)
        assert not is_computing_hardware(ICORPS)

    def test_empty_title_is_not_hardware(self):
        assert not is_computing_hardware("")
        assert not is_computing_hardware(None)


class TestInstitutionNormalization:
    def test_strips_legal_entity_wrappers(self):
        assert normalize_institution("University of Georgia Research Foundation Inc") == (
            "University of Georgia"
        )
        assert normalize_institution(
            "Kennesaw State University Research and Service Foundation"
        ) == "Kennesaw State University"

    def test_all_caps_names_are_title_cased(self):
        assert "Augusta" in normalize_institution("AUGUSTA UNIVERSITY RESEARCH INSTITUTE, INC.")

    def test_aliases_resolve_to_the_registry_name(self):
        # "Georgia Tech Research Corporation" and the registry's "Georgia Institute
        # of Technology" must land on one string, or a known facility reads as new.
        assert normalize_institution("Georgia Tech Research Corporation") == (
            "Georgia Institute of Technology"
        )
        assert normalize_institution("Georgia Institute of Technology") == (
            "Georgia Institute of Technology"
        )


class TestCandidate:
    def _cand(self):
        return Candidate(
            institution="Test University",
            city="Atlanta",
            awards=[
                {"id": "1", "title": MRI_HPC, "date": "08/24/2018", "fundsObligatedAmt": "1000"},
                {"id": "2", "title": CC_CAMPUS, "date": "11/13/2024", "fundsObligatedAmt": "2500"},
            ],
        )

    def test_totals_and_latest_year(self):
        c = self._cand()
        assert c.total_obligated == 3500
        assert c.latest_year == "2024"

    def test_strongest_award_prefers_cc_star(self):
        # CC* exists to build campus cyberinfrastructure, so it speaks more
        # directly to a facility than a general instrumentation award.
        assert self._cand().strongest["id"] == "2"

    def test_unparsable_amount_does_not_crash_the_total(self):
        c = Candidate(
            institution="X", city="Y",
            awards=[{"id": "1", "title": CC_STAR, "date": "2020", "fundsObligatedAmt": None}],
        )
        assert c.total_obligated == 0


class TestReport:
    def test_report_marks_institutions_already_in_the_registry(self):
        c = Candidate(institution="University of Georgia", city="Athens", awards=[
            {"id": "1", "title": MRI_CLUSTER, "date": "08/17/2008", "fundsObligatedAmt": "796822"},
        ])
        text = format_report([c], known={"University of Georgia"})
        assert "[in registry]" in text

    def test_report_states_the_award_is_not_proof_of_a_facility(self):
        # The caveat is the point of the report; it must not be edited away.
        text = format_report([], known=set())
        assert "NOT evidence" in text
