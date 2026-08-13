"""Tests for reading facility addresses out of Georgia EPD permit PDFs.

The address block is hand-typed by whoever wrote each permit, so its format drifts
between documents. Every variant below was observed in the real 38-facility set;
they are pinned here because a parser that silently rejects a variant produces an
empty column rather than an error, and a parser that mis-splits one relocates a
facility. No network access.
"""

from __future__ import annotations

from ga_data_center_tracker.scrapers.epd_permit_docs import (
    FacilityAddress,
    county_disagreements,
    parse_address_block,
)


def block(street: str, city_line: str, trailing: str = "Mailing Address:") -> str:
    return f"""
   PERMIT NO. 7374-097-0093-B-01-0
Facility Name:         Example Data Center, LLC
Facility Address:       {street}
                   {city_line}
{trailing}        3344 Peachtree Road, NE, Suite 2550
                   Atlanta, GA 30326
Facility AIRS Number:   04-13-097-00093
"""


class TestAddressFormats:
    """Every layout EPD actually publishes."""

    def test_plain(self):
        t = block("South End of Trae Lane", "Lithia Springs, Georgia 30122 Douglas County")
        assert parse_address_block(t) == (
            "South End of Trae Lane", "Lithia Springs", "30122", "Douglas",
        )

    def test_county_in_parentheses(self):
        t = block("300 Riverside Parkway SW", "Lithia Springs, Georgia 30122 (Douglas County)")
        assert parse_address_block(t)[3] == "Douglas"

    def test_comma_after_state(self):
        t = block("1199 Enterprise Drive", "Dalton, Georgia, 30721, Whitfield County")
        assert parse_address_block(t) == (
            "1199 Enterprise Drive", "Dalton", "30721", "Whitfield",
        )

    def test_abbreviated_state_and_short_zip(self):
        # One permit really does print a four-digit zip. It is captured as printed,
        # not silently corrected; this module reports what the state published.
        t = block("2525 Westside Parkway", "Alpharetta, GA 3004, (Fulton County)")
        assert parse_address_block(t) == ("2525 Westside Parkway", "Alpharetta", "3004", "Fulton")

    def test_no_county_named(self):
        t = block("756 West Peachtree Street NW", "Atlanta, Georgia 30308")
        street, city, zip_code, county = parse_address_block(t)
        assert (city, zip_code, county) == ("Atlanta", "30308", "")

    def test_multi_line_street_is_joined(self):
        t = """
Facility Address:       300, 600, and 700
                   North Point Parkway
                   Alpharetta, Georgia 30005 Fulton County
Mailing Address:        elsewhere
"""
        street, city, _, _ = parse_address_block(t)
        assert street == "300, 600, and 700 North Point Parkway"
        assert city == "Alpharetta"


class TestRejection:
    """Failures must be silent-free: no block means no address, never a guess."""

    def test_missing_block_returns_none(self):
        assert parse_address_block("PERMIT NO. 1234\nSome other text entirely") is None

    def test_empty_text_returns_none(self):
        # A scanned permit has no text layer at all; one facility's PDF is exactly this.
        assert parse_address_block("") is None

    def test_unparsable_city_line_returns_none(self):
        t = block("123 Main Street", "somewhere unhelpful")
        assert parse_address_block(t) is None

    def test_mailing_address_is_never_used(self):
        # The mailing address is often a corporate HQ in another county. Taking it
        # would silently relocate the facility.
        t = block("South End of Trae Lane", "Lithia Springs, Georgia 30122 Douglas County")
        street, city, _, _ = parse_address_block(t)
        assert "Peachtree" not in street
        assert city == "Lithia Springs"


class TestCountyCrossCheck:
    """The printed county is an independent check on the AIRS-derived county."""

    class _Facility:
        def __init__(self, airs, county):
            self.airs_number = airs
            self.county = county

    def _addr(self, airs, county_printed):
        return FacilityAddress(
            airs_number=airs, street="1 Main St", city="Somewhere", zip_code="30000",
            county_printed=county_printed, permit_number="x", pdf_url="https://example",
        )

    def test_agreement_reports_nothing(self):
        f = [self._Facility("097-00093", "Douglas County, Georgia")]
        assert county_disagreements({"097-00093": self._addr("097-00093", "Douglas")}, f) == []

    def test_disagreement_is_flagged(self):
        f = [self._Facility("097-00093", "Douglas County, Georgia")]
        out = county_disagreements({"097-00093": self._addr("097-00093", "Fulton")}, f)
        assert out == [("097-00093", "Douglas", "Fulton")]

    def test_missing_printed_county_is_not_a_disagreement(self):
        f = [self._Facility("121-00941", "Fulton County, Georgia")]
        assert county_disagreements({"121-00941": self._addr("121-00941", "")}, f) == []
