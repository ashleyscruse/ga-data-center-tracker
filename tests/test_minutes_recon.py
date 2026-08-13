"""Tests for the county minutes recon pass.

The value of this module is a short, correct list of which agenda platform each
county uses. Both ways it can be wrong are silent, so both are pinned here:
a fingerprint that fires on ordinary prose invents platforms, and one that never
fires reports "no platform" for a county that has one.
"""

from __future__ import annotations

from ga_data_center_tracker.scrapers.minutes_recon import (
    CountyRecon,
    detect_non_agenda,
    detect_platforms,
    format_report,
    minutes_links,
)


class TestPlatformFingerprints:
    def test_vendor_domains_are_detected(self):
        assert detect_platforms('<script src="https://x.civicplus.com/a.js">') == ["CivicPlus"]
        assert detect_platforms("https://county.civicclerk.com/") == ["CivicClerk"]
        assert detect_platforms("https://ga-dekalb.granicus.com/") == ["Granicus"]
        assert detect_platforms("https://x.legistar.com/Calendar.aspx") == ["Legistar"]
        assert detect_platforms("https://troup.iqm2.com/Citizens/") == ["IQM2"]

    def test_agendacenter_path_counts_as_civicplus(self):
        # CivicPlus sites are often identifiable only by this path.
        assert detect_platforms("https://www.bankscountyga.org/1228/AgendaCenter") == ["CivicPlus"]

    def test_ordinary_prose_does_not_invent_a_platform(self):
        # The regression this file exists for. "escribe" is a substring of
        # "describe", so bare-substring matching reported eSCRIBE on any page
        # containing an ordinary English word, on 9 of 37 counties.
        assert detect_platforms("The ordinance is described in section 4.") == []
        assert detect_platforms("Please describe your request.") == []
        assert detect_platforms("This page describes the zoning process.") == []

    def test_escribe_still_detected_by_its_real_domain(self):
        assert detect_platforms("https://pub-x.escribemeetings.com/") == ["eSCRIBE"]

    def test_multiple_vendors_on_one_page(self):
        html = "granicus.com/js granicus legistar.com/Calendar"
        assert detect_platforms(html) == ["Granicus", "Legistar"]

    def test_no_markers_returns_empty(self):
        assert detect_platforms("<html><body>Welcome to the county</body></html>") == []
        assert detect_platforms("") == []


class TestNonAgendaVendors:
    def test_municode_is_not_an_agenda_platform(self):
        # Municode hosts municipal codes and appears on most county sites. Counting
        # it as an agenda platform would claim coverage that buys no minutes.
        html = 'href="https://library.municode.com/ga/county/codes"'
        assert detect_platforms(html) == []
        assert detect_non_agenda(html) == ["Municode (code library, not agendas)"]


class TestMinutesLinks:
    SITE = "https://www.example-county.gov/"
    HTML = """
      <a href="/agendas">Agendas and Minutes</a>
      <a href="/parks">Parks and Recreation</a>
      <a href="/zoning-board">Zoning Board of Appeals</a>
      <a href="https://othersite.com/news">Board of Commissioners news</a>
      <a href="https://county.civicclerk.com/">Meeting Agendas</a>
    """

    def test_finds_agenda_and_zoning_links(self):
        found = minutes_links(self.SITE, self.HTML)
        assert "https://www.example-county.gov/agendas" in found
        assert "https://www.example-county.gov/zoning-board" in found

    def test_ignores_unrelated_links(self):
        assert not any("parks" in u for u in minutes_links(self.SITE, self.HTML))

    def test_keeps_offsite_vendor_links_but_drops_other_offsite(self):
        found = minutes_links(self.SITE, self.HTML)
        assert "https://county.civicclerk.com/" in found
        assert not any("othersite.com" in u for u in found)


class TestReport:
    def test_report_ranks_platforms_by_counties_covered(self):
        results = [
            CountyRecon(county="Fulton County, Georgia", site_url="https://f", platforms=["Legistar"]),
            CountyRecon(county="Cobb County, Georgia", site_url="https://c", platforms=["CivicPlus"]),
            CountyRecon(county="Henry County, Georgia", site_url="https://h", platforms=["CivicPlus"]),
        ]
        text = format_report(results)
        assert text.index("CivicPlus") < text.index("Legistar")

    def test_report_counts_the_three_outcomes(self):
        results = [
            CountyRecon(county="Fulton County, Georgia", site_url="https://f", platforms=["Legistar"]),
            CountyRecon(county="Cobb County, Georgia", site_url="https://c"),
            CountyRecon(county="Pike County, Georgia"),
        ]
        text = format_report(results)
        assert "1 with an identified agenda platform" in text
        assert "1 site found, platform not fingerprinted" in text
        assert "1 site not found" in text
