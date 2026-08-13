"""Georgia EPD Air Protection Branch permit scraper.

Georgia EPD's Air Permit Search Engine (https://permitsearch.gaepd.org/) publishes
every issued air construction permit in the state. Data centers appear here because
their backup diesel generators require an air permit before the facility is built,
which makes this the earliest *facility-specific, county-resolved* public signal in
Georgia. It reaches earlier in the lifecycle than EPA FRS: FRS records a facility
once it is regulated and reported federally, while an EPD permit is issued during
the construction-permitting stage.

Two encodings in the search results carry the fields that matter:

  * **AIRS number** ``CCC-NNNNN`` -> ``CCC`` is the county's 3-digit FIPS code.
    ``001-00001`` is Appling County (FIPS 13001), ``097-00093`` is Douglas County
    (FIPS 13097). Prefixing ``13`` yields the full county FIPS, which is the
    tracker's join key. No geocoding step is needed for this source.
  * **Permit number** ``SSSS-CCC-NNNN-T-VV-R`` -> ``SSSS`` is the facility's SIC
    code. ``7374`` is Data Processing and Preparation, the classification Georgia
    EPD assigns to data centers.

Permits are versioned: one facility accumulates several permit records over time
(initial issuance, amendments, renewals). ``scrape_permits`` returns every permit
record; ``permits_to_facilities`` collapses them to one record per facility (per
AIRS number), keeping the earliest issuance date as the facility's first-permit
date and the latest as its most recent activity.

The site is an ASP.NET WebForms application with a Telerik RadGrid, so paging runs
through ``__doPostBack`` on a persistent session with the hidden state fields
carried forward from each response.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import requests

from ..counties import load_reference

SEARCH_URL = "https://permitsearch.gaepd.org/"

# Georgia EPD does not file every data center under one SIC code. These two were
# established by pulling the entire permit database (about 10,200 permits across 3,044
# facilities) and inspecting which codes carry data center facilities:
#
#   7374  Data Processing and Preparation. The main one, 26 facilities.
#   7376  Computer Facilities Management Services. 8 facilities, all data centers,
#         including several large operators that 7374 alone misses entirely.
#
# Searching 7374 alone understates the count by roughly a quarter.
DATA_CENTER_SIC_CODES = ("7374", "7376")

# Codes that contain *some* data centers alongside unrelated industry, so they cannot be
# swept in wholesale. Facilities here are surfaced for manual review instead of counted:
#
#   7389  Services, Not Elsewhere Classified. A catch-all. Of 3 Georgia facilities, one
#         is a data center and the others are unrelated manufacturing and sterilization.
#   4813  Telephone Communications. 7 facilities, a genuine mix of telecom central
#         offices and colocation data centers. Whether a carrier switch counts as a data
#         center is a scope question, not a data question, so it is not decided here.
#
# ``review_candidates`` pulls these for a human to adjudicate. See docs/methodology.md.
REVIEW_SIC_CODES = ("7389", "4813")

# Facilities under the review codes that have been adjudicated **in**, by AIRS number.
#
# Adjudicating one facility at a time, rather than promoting a whole SIC code, is what
# lets a data center filed under a catch-all code be counted without also sweeping in
# the sterilization plant and the airport that share it. Each entry records why, so the
# decision is auditable and reversible rather than folklore.
ADJUDICATED_INCLUSIONS = {
    "097-00061": (
        "Google, Inc. (Douglas County). Google's Douglas County data center, filed "
        "under the 7389 catch-all. A data center under any definition; its exclusion "
        "was a filing artifact, not a scope judgment."
    ),
    "121-00798": (
        "AT&T Data Center (Fulton County). Named as a data center in the state's own "
        "facility record."
    ),
    "097-00071": (
        "Savvis Communications Corporation - AT1 (Douglas County). Savvis is a "
        "colocation operator and AT1 is its Atlanta facility, not a carrier switch."
    ),
    "097-00063": (
        "375 Riverside Pkwy LLC (Douglas County). A 250,000 sq ft, 27.5 MW colocation "
        "facility in Lithia Springs, operated most recently as Evoque Atlanta."
    ),
}

# Facilities under the review codes adjudicated **out**, recorded so the next person to
# look does not re-litigate them. The remaining 4813 facilities are carrier switching
# centers, which are the open scope question and are deliberately absent from both lists.
ADJUDICATED_EXCLUSIONS = {
    "063-00030": "Hartsfield-Jackson Atlanta International Airport. Misfiled SIC; an airport.",
    "057-00066": "CyCan Industries, Inc. Manufacturing, not a data center.",
    "067-00093": "Sterigenics U.S. LLC. Medical sterilization, not a data center.",
}

GEORGIA_STATE_FIPS = "13"

_AIRS_RE = re.compile(r"^\d{3}-\d{5}$")
_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)

# Telerik renders the pager buttons with a title attribute; that is the stable
# handle for "Next Page" across pages, unlike the generated ctl.. control ids.
_NEXT_BUTTON_RE = re.compile(
    r'<button[^>]*name="([^"]+)"[^>]*title="Next Page"[^>]*class="([^"]*)"', re.S
)

_FORM_FIELDS = (
    "ctl00$ContentPlaceHolder2$txtAirsNo",
    "ctl00$ContentPlaceHolder2$txtFacility",
    "ctl00$ContentPlaceHolder2$txtSIC",
)


@dataclass
class PermitRecord:
    """One issued air permit record as published by Georgia EPD."""

    airs_number: str            # "097-00093"
    facility_name: str
    permit_number: str          # "7374-097-0093-B-01-0"
    issuance_date: date | None
    permit_type: str            # "SIP", "Title V", ...
    sic_code: str               # parsed from the permit number
    county: str | None          # "Douglas County, Georgia"
    county_fips: str | None     # "13097"
    source: str = "GA EPD Air Permit Search"


@dataclass
class FacilityRecord:
    """One data center facility, collapsed from its permit history."""

    airs_number: str
    name: str
    county: str | None
    county_fips: str | None
    first_permit_date: date | None
    latest_permit_date: date | None
    permit_count: int
    permit_types: str           # comma-separated, e.g. "SIP, Title V"
    sic_code: str
    source: str = "GA EPD Air Permit Search"
    stage: str = "permitted"    # air permit issued: construction or operating


def _fips_to_tracker() -> dict[str, str]:
    """County FIPS -> tracker name, built from the committed county reference."""
    return {c.fips: c.tracker_name for c in load_reference()}


def _clean(cell: str) -> str:
    """Strip tags and normalize whitespace out of one grid cell."""
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub("", cell))).strip()


def _hidden(page: str, name: str) -> str:
    """Pull an ASP.NET hidden state field (``__VIEWSTATE`` and friends) out of a page."""
    match = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
    return html_lib.unescape(match.group(1)) if match else ""


def _parse_date(raw: str) -> date | None:
    """Parse EPD's ``4-Feb-1999`` dates, which use non-breaking hyphens."""
    cleaned = raw.replace("‑", "-").replace("–", "-").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_sic(permit_number: str) -> str:
    """The leading segment of a permit number is the facility's SIC code."""
    head = permit_number.split("-", 1)[0].strip()
    return head if head.isdigit() else ""


def _post(session: requests.Session, page: str, extra: dict[str, str]) -> str:
    """Submit a WebForms postback, carrying this page's hidden state forward."""
    payload = {
        "__VIEWSTATE": _hidden(page, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hidden(page, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hidden(page, "__EVENTVALIDATION"),
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
    }
    payload.update({field: "" for field in _FORM_FIELDS})
    payload.update(extra)
    response = session.post(SEARCH_URL, data=payload, timeout=120)
    response.raise_for_status()
    return response.text


def _parse_rows(page: str) -> list[list[str]]:
    """Extract the permit rows from a results page.

    A permit row is identified by its first cell matching the AIRS number pattern,
    which skips the header, pager, and layout rows without depending on their markup.
    """
    rows: list[list[str]] = []
    for row_html in _ROW_RE.findall(page):
        cells = [_clean(c) for c in _CELL_RE.findall(row_html)]
        if len(cells) >= 6 and _AIRS_RE.match(cells[0]):
            rows.append(cells[:6])
    return rows


def _next_page_control(page: str) -> str | None:
    """Name of the enabled "Next Page" pager button, or ``None`` on the last page."""
    for name, css in _NEXT_BUTTON_RE.findall(page):
        if "rgPagerDisabled" in css or "aspNetDisabled" in css:
            continue
        return name
    return None


def _search(session: requests.Session, page: str, sic_code: str) -> str:
    """Run the SIC-code search and return the first results page."""
    # The SIC box is a Telerik RadTextBox; it only registers the typed value when
    # its ClientState field is submitted alongside the plain input.
    client_state = json.dumps(
        {
            "enabled": True,
            "emptyMessage": "",
            "validationText": sic_code,
            "valueAsString": sic_code,
            "lastSetTextBoxValue": sic_code,
        }
    )
    return _post(
        session,
        page,
        {
            "ctl00$ContentPlaceHolder2$txtSIC": sic_code,
            "ctl00_ContentPlaceHolder2_txtSIC_ClientState": client_state,
            "ctl00$ContentPlaceHolder2$btnSearch": "Search",
        },
    )


def scrape_permits(
    *,
    sic_codes: tuple[str, ...] = DATA_CENTER_SIC_CODES,
    max_pages: int | None = None,
    sleep: float = 0.5,
    verbose: bool = False,
) -> list[PermitRecord]:
    """Scrape every issued data center air permit from Georgia EPD.

    Args:
        sic_codes: SIC codes to search. Defaults to 7374 (data centers).
        max_pages: cap pages per SIC code, for quick test runs.
        sleep: seconds between requests, to stay polite to a state server.
        verbose: print per-page progress.

    Returns one ``PermitRecord`` per issued permit, deduplicated by permit number.
    """
    fips_map = _fips_to_tracker()
    by_permit: dict[str, PermitRecord] = {}

    for sic_code in sic_codes:
        session = requests.Session()
        session.headers.update({"User-Agent": "ga-data-center-tracker (research)"})
        page = session.get(SEARCH_URL, timeout=120).text
        page = _search(session, page, sic_code)

        page_number = 1
        while True:
            rows = _parse_rows(page)
            for airs, name, permit_number, issued, _docs, permit_type in rows:
                if permit_number in by_permit:
                    continue
                county_fips = GEORGIA_STATE_FIPS + airs.split("-")[0]
                by_permit[permit_number] = PermitRecord(
                    airs_number=airs,
                    facility_name=name,
                    permit_number=permit_number,
                    issuance_date=_parse_date(issued),
                    permit_type=permit_type,
                    sic_code=_parse_sic(permit_number) or sic_code,
                    county=fips_map.get(county_fips),
                    county_fips=county_fips if county_fips in fips_map else None,
                )
            if verbose:
                print(f"SIC {sic_code} page {page_number}: {len(rows)} rows "
                      f"({len(by_permit)} permits total)")

            if max_pages is not None and page_number >= max_pages:
                break
            control = _next_page_control(page)
            if not control:
                break
            time.sleep(sleep)
            next_page = _post(session, page, {"__EVENTTARGET": control, control: " "})
            if _parse_rows(next_page) == rows:
                break  # pager wrapped or stalled; stop rather than loop forever
            page = next_page
            page_number += 1

    return list(by_permit.values())


def permits_to_facilities(permits: list[PermitRecord]) -> list[FacilityRecord]:
    """Collapse permit records to one record per facility (AIRS number).

    A facility's name can vary slightly across its permit history (operators rename
    campuses), so the name from its most recent permit is kept.
    """
    grouped: dict[str, list[PermitRecord]] = {}
    for permit in permits:
        grouped.setdefault(permit.airs_number, []).append(permit)

    facilities: list[FacilityRecord] = []
    for airs, records in grouped.items():
        dated = [r for r in records if r.issuance_date]
        dated.sort(key=lambda r: r.issuance_date)  # type: ignore[arg-type,return-value]
        newest = dated[-1] if dated else records[-1]
        facilities.append(
            FacilityRecord(
                airs_number=airs,
                name=newest.facility_name,
                county=newest.county,
                county_fips=newest.county_fips,
                first_permit_date=dated[0].issuance_date if dated else None,
                latest_permit_date=dated[-1].issuance_date if dated else None,
                permit_count=len(records),
                permit_types=", ".join(sorted({r.permit_type for r in records if r.permit_type})),
                sic_code=newest.sic_code,
            )
        )
    facilities.sort(key=lambda f: f.airs_number)
    return facilities


def facilities_to_county_counts(facilities: list[FacilityRecord]) -> dict[str, int]:
    """Per-county count of air-permitted data center facilities.

    Every Georgia county is present, defaulting to 0, so the result is dense and
    ready for the Long sheet.
    """
    counts = {c.tracker_name: 0 for c in load_reference()}
    for facility in facilities:
        if facility.county and facility.county in counts:
            counts[facility.county] += 1
    return counts


def scrape_data_center_permits(
    *, sleep: float = 0.5, verbose: bool = False
) -> list[PermitRecord]:
    """Every permit record this dataset counts as a data center.

    Two passes, because Georgia EPD's filing is not clean enough for one:

    1. The codes that carry data centers wholesale (``DATA_CENTER_SIC_CODES``).
    2. The ambiguous codes (``REVIEW_SIC_CODES``), filtered to the specific facilities
       in ``ADJUDICATED_INCLUSIONS``.

    The second pass is the reason Google's Douglas County data center is in the count.
    It sits under 7389, a catch-all shared with a sterilization plant, so the code
    cannot be swept in and the facility has to be named.
    """
    permits = scrape_permits(sic_codes=DATA_CENTER_SIC_CODES, sleep=sleep, verbose=verbose)

    if verbose:
        print(f"Checking review SIC codes {REVIEW_SIC_CODES} for adjudicated facilities...")
    review = scrape_permits(sic_codes=REVIEW_SIC_CODES, sleep=sleep, verbose=False)
    adjudicated = [p for p in review if p.airs_number in ADJUDICATED_INCLUSIONS]
    permits += adjudicated

    if verbose:
        found = sorted({p.airs_number for p in adjudicated})
        print(f"  {len(found)} of {len(ADJUDICATED_INCLUSIONS)} adjudicated facilities found: {found}")
        missing = set(ADJUDICATED_INCLUSIONS) - set(found)
        if missing:
            # Loud, because a silently vanished facility would quietly drop the count.
            print(f"  WARNING: adjudicated facilities not found in the permit record: {sorted(missing)}")
    return permits


def review_candidates(*, sleep: float = 0.5, verbose: bool = False) -> list[FacilityRecord]:
    """Facilities under the ambiguous SIC codes, for manual adjudication.

    These are deliberately kept out of the counted dataset. Run this when revisiting
    scope, hand the list to a human, and promote anything confirmed by adding its code to
    ``DATA_CENTER_SIC_CODES`` or by recording the decision in the methodology.
    """
    permits = scrape_permits(sic_codes=REVIEW_SIC_CODES, sleep=sleep, verbose=verbose)
    return permits_to_facilities(permits)


def facilities_to_recent_county_counts(
    facilities: list[FacilityRecord], *, since_year: int
) -> dict[str, int]:
    """Per-county count of facilities first permitted in ``since_year`` or later.

    This separates the current buildout from the long tail of older facilities, so
    the tracker can show where activity is happening now rather than cumulatively.
    """
    counts = {c.tracker_name: 0 for c in load_reference()}
    for facility in facilities:
        if not facility.county or facility.county not in counts:
            continue
        if facility.first_permit_date and facility.first_permit_date.year >= since_year:
            counts[facility.county] += 1
    return counts
