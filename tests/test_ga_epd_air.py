"""Tests for the Georgia EPD air permit scraper.

These cover the parsing and aggregation layer, which is where the correctness risk
lives: the county encoding in the AIRS number, the SIC encoding in the permit
number, EPD's non-breaking-hyphen dates, and the collapse from permit records to
facilities. Network calls are not exercised here.
"""

from __future__ import annotations

from datetime import date

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.scrapers.ga_epd_air import (
    PermitRecord,
    _parse_date,
    _parse_rows,
    _parse_sic,
    facilities_to_county_counts,
    facilities_to_recent_county_counts,
    permits_to_facilities,
)


def _permit(airs, name, permit_number, issued, county, fips, permit_type="SIP"):
    return PermitRecord(
        airs_number=airs,
        facility_name=name,
        permit_number=permit_number,
        issuance_date=issued,
        permit_type=permit_type,
        sic_code="7374",
        county=county,
        county_fips=fips,
    )


def test_parse_date_handles_epd_non_breaking_hyphens():
    # EPD renders dates with U+2011 non-breaking hyphens, not ASCII hyphens.
    assert _parse_date("1‑Feb‑2021") == date(2021, 2, 1)
    assert _parse_date("19-Feb-2024") == date(2024, 2, 19)
    assert _parse_date("not a date") is None


def test_parse_sic_reads_the_permit_number_prefix():
    assert _parse_sic("7374-097-0093-B-01-0") == "7374"
    assert _parse_sic("4911-001-0001-V-01-0") == "4911"
    assert _parse_sic("") == ""


def test_parse_rows_keeps_only_airs_numbered_rows():
    page = """
    <table>
      <tr><th>AIRS Number</th><th>Facility Name</th><th>Permit</th>
          <th>Issuance Date</th><th>Other Documents</th><th>Permit Type</th></tr>
      <tr><td>097-00098</td><td>Aligned Data Centers ATL01</td>
          <td>7374-097-0098-S-01-0</td><td>19-Feb-2024</td>
          <td><a href="#">Narrative</a></td><td>SIP</td></tr>
      <tr><td colspan="6">12345... 46 items in 3 pages</td></tr>
    </table>
    """
    rows = _parse_rows(page)
    assert len(rows) == 1
    assert rows[0][0] == "097-00098"
    assert rows[0][1] == "Aligned Data Centers ATL01"
    assert rows[0][5] == "SIP"


def test_permits_to_facilities_collapses_permit_history():
    permits = [
        _permit("097-00100", "Flexential Corporation", "7374-097-0100-S-01-0",
                date(2025, 4, 25), "Douglas County, Georgia", "13097"),
        _permit("097-00100", "Flexential Corporation", "7374-097-0100-S-01-1",
                date(2026, 5, 5), "Douglas County, Georgia", "13097"),
        _permit("113-00073", "QTS Fayetteville I, LLC", "7374-113-0073-S-01-0",
                date(2023, 10, 11), "Fayette County, Georgia", "13113"),
    ]
    facilities = permits_to_facilities(permits)
    assert len(facilities) == 2
    flexential = next(f for f in facilities if f.airs_number == "097-00100")
    assert flexential.permit_count == 2
    assert flexential.first_permit_date == date(2025, 4, 25)
    assert flexential.latest_permit_date == date(2026, 5, 5)


def test_county_counts_are_dense_across_all_counties():
    permits = [
        _permit("097-00098", "Aligned Data Centers ATL01", "7374-097-0098-S-01-0",
                date(2024, 2, 19), "Douglas County, Georgia", "13097"),
    ]
    counts = facilities_to_county_counts(permits_to_facilities(permits))
    assert len(counts) == GEORGIA_COUNTY_COUNT
    assert counts["Douglas County, Georgia"] == 1
    # A tracked county with no activity is a true zero, not missing.
    assert counts["Appling County, Georgia"] == 0


def test_recent_counts_use_the_first_permit_date():
    permits = [
        # Older facility: has permit activity after the cutoff but was first
        # permitted before it, so it is not part of the recent buildout.
        _permit("121-00050", "ADP Data Center (DC1)", "7374-121-0050-S-01-0",
                date(2014, 8, 29), "Fulton County, Georgia", "13121"),
        _permit("121-00050", "ADP Data Center (DC1)", "7374-121-0050-S-01-1",
                date(2025, 1, 5), "Fulton County, Georgia", "13121"),
        _permit("097-00101", "Amazon Data Services, Inc.", "7374-097-0101-S-01-0",
                date(2025, 8, 18), "Douglas County, Georgia", "13097"),
    ]
    facilities = permits_to_facilities(permits)
    recent = facilities_to_recent_county_counts(facilities, since_year=2023)
    assert recent["Fulton County, Georgia"] == 0
    assert recent["Douglas County, Georgia"] == 1


# --- SIC adjudication ---------------------------------------------------------
#
# Georgia EPD files some data centers under catch-all codes shared with unrelated
# industry, so those codes cannot be swept in wholesale and individual facilities
# are named instead. These guard the named list, because a facility silently
# dropping off it would quietly lower the published count.

from ga_data_center_tracker.scrapers.ga_epd_air import (  # noqa: E402
    _AIRS_RE,
    ADJUDICATED_EXCLUSIONS,
    ADJUDICATED_INCLUSIONS,
    DATA_CENTER_SIC_CODES,
    REVIEW_SIC_CODES,
)


def test_google_douglas_county_is_adjudicated_in():
    # The facility this mechanism exists for: Google's Douglas County data center,
    # filed under 7389 alongside a sterilization plant.
    assert "097-00061" in ADJUDICATED_INCLUSIONS
    assert "Google" in ADJUDICATED_INCLUSIONS["097-00061"]


def test_every_adjudicated_entry_records_a_reason():
    for airs, reason in {**ADJUDICATED_INCLUSIONS, **ADJUDICATED_EXCLUSIONS}.items():
        assert len(reason) > 30, f"{airs} needs a real reason, not a label"


def test_adjudicated_airs_numbers_are_well_formed():
    for airs in {**ADJUDICATED_INCLUSIONS, **ADJUDICATED_EXCLUSIONS}:
        assert _AIRS_RE.match(airs), airs


def test_inclusions_and_exclusions_do_not_overlap():
    assert not set(ADJUDICATED_INCLUSIONS) & set(ADJUDICATED_EXCLUSIONS)


def test_review_codes_are_not_also_counted_wholesale():
    # If a review code ever moves into DATA_CENTER_SIC_CODES, the adjudication list
    # for it becomes dead weight and the unrelated facilities get swept in.
    assert not set(REVIEW_SIC_CODES) & set(DATA_CENTER_SIC_CODES)


def test_airport_stays_excluded():
    # Hartsfield-Jackson carries a 4813 permit. It is not a data center.
    assert "063-00030" in ADJUDICATED_EXCLUSIONS
