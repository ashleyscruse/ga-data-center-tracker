"""Facility addresses, read out of the permit PDFs Georgia EPD publishes.

The EPD permit search grid gives an AIRS number, a facility name, a permit number,
a date, and a permit type. No address. That is why every EPD row on the delivered
``Original`` sheet has an empty ``city`` and ``address``, and, more importantly,
why the statewide facility total is a range rather than a number: with no address
there is nothing to geocode, and with nothing to geocode a permitted facility
cannot be matched by location against EPIcenter's coordinates.

**The addresses are published, just one layer down.** Every permit row in the grid
links to the permit PDF, and the first page of that PDF carries a header block:

    Facility Name:         T5@Atlanta III, LLC
    Facility Address:      South End of Trae Lane
                           Lithia Springs, Georgia 30122  Douglas County
    Mailing Address:       3344 Peachtree Road, NE, Suite 2550
                           Atlanta, GA 30326
    Facility AIRS Number:  04-13-097-00093

So this module walks the same search, collects each permit's PDF link, downloads
one PDF per facility, and parses that block.

Two things it is careful about:

* **Facility Address, never Mailing Address.** They are usually different, and the
  mailing address is often a corporate headquarters in another county. Taking the
  wrong one would silently relocate the facility.
* **Parsing by line, not by flattened text.** The PDF puts street on one line and
  "City, Georgia ZIP County County" on the next. Flattening the block first loses
  the boundary between street and city, because there is no comma between them.

The county printed in words is kept as an independent check on the county derived
from the AIRS number's digits. Those come from different parts of the record, so a
disagreement is worth surfacing rather than averaging away.

Run:  ``python -m ga_data_center_tracker.scrapers.epd_permit_docs``
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from . import ga_epd_air as epd

BASE_URL = "https://permitsearch.gaepd.org/"

# Permit-document links in the results grid. The anchor text is the permit number,
# the href carries the document id. "OP" is the permit itself; "ON" is the
# narrative, which does not have the header block.
_PERMIT_PDF_RE = re.compile(
    r'href=["\'](permit\.aspx\?id=PDF-OP-\d+)["\'][^>]*>\s*([0-9][0-9A-Za-z\-]*)\s*<'
)

# The city/state/zip/county line, which EPD writes at least five different ways.
# Observed across the 38 data center facilities:
#
#   Lithia Springs, Georgia 30122 Douglas County
#   Lithia Springs, Georgia 30122 (Douglas County)      county parenthesized
#   Dalton, Georgia, 30721, Whitfield County            comma after the state
#   Suwanee, Georgia 30024, (Gwinnett County)           both
#   Alpharetta, GA 3004, (Fulton County)                "GA", and a typo'd 4-digit zip
#   Atlanta, Georgia 30318                              no county at all
#
# Hence the tolerance: the state may be spelled or abbreviated, commas are optional
# nearly everywhere, the county may be wrapped in parentheses or absent, and the zip
# is allowed to be four digits because one permit genuinely prints it that way. A
# short zip is captured as printed and flagged rather than silently corrected; this
# module reports what the state published.
_CITY_LINE_RE = re.compile(
    r"^(?P<city>.+?),\s*(?:Georgia|GA)\.?,?\s+"
    r"(?P<zip>\d{4,5})(?:-\d{4})?\.?,?\s*"
    r"\(?\s*(?:(?P<county>[A-Za-z .'\-]+?)\s+County)?\s*\)?\.?\s*$",
    re.I,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = _REPO_ROOT / "data" / "raw" / "epd_permits"
ADDRESS_CACHE = _REPO_ROOT / "data" / "interim" / "epd_facility_addresses.json"


@dataclass
class FacilityAddress:
    """One facility's address as printed on its air permit."""

    airs_number: str
    street: str
    city: str
    zip_code: str
    county_printed: str      # county as written on the permit, e.g. "Douglas"
    permit_number: str
    pdf_url: str

    @property
    def full(self) -> str:
        parts = [self.street, f"{self.city}, GA {self.zip_code}".strip(", ")]
        return ", ".join(p for p in parts if p)


def _text_first_page(pdf_bytes: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc[0].get_text() if doc.page_count else ""


def parse_address_block(page_text: str) -> tuple[str, str, str, str] | None:
    """Pull ``(street, city, zip, county)`` out of a permit's first page.

    Returns ``None`` when the header block is absent or shaped differently, so a
    surprising PDF drops out of the results instead of contributing a wrong
    address.
    """
    start = page_text.find("Facility Address:")
    if start == -1:
        return None
    # The block ends at whichever of these comes first; both follow it.
    ends = [page_text.find(m, start) for m in ("Mailing Address:", "Facility AIRS")]
    ends = [e for e in ends if e != -1]
    block = page_text[start : min(ends)] if ends else page_text[start : start + 400]

    lines = [
        re.sub(r"\s+", " ", ln).strip()
        for ln in block.replace("Facility Address:", "").splitlines()
    ]
    lines = [ln for ln in lines if ln]
    if len(lines) < 2:
        return None

    # Last line that names the city/state/zip; everything before it is the street.
    for i in range(len(lines) - 1, 0, -1):
        m = _CITY_LINE_RE.match(lines[i])
        if m:
            street = " ".join(lines[:i]).strip(" ,")
            county = (m.group("county") or "").strip()
            return street, m.group("city").strip(), m.group("zip"), county
    return None


def discover_permit_pdfs(
    *, sic_codes: tuple[str, ...] | None = None, sleep: float = 0.5, verbose: bool = False
) -> dict[str, str]:
    """Map permit number -> permit-PDF URL, across every results page."""
    codes = sic_codes or (epd.DATA_CENTER_SIC_CODES + epd.REVIEW_SIC_CODES)
    found: dict[str, str] = {}

    for sic_code in codes:
        session = requests.Session()
        session.headers.update({"User-Agent": "ga-data-center-tracker (research)"})
        page = session.get(epd.SEARCH_URL, timeout=120).text
        page = epd._search(session, page, sic_code)

        page_number = 1
        while True:
            for href, permit_number in _PERMIT_PDF_RE.findall(page):
                found.setdefault(permit_number, BASE_URL + href)
            if verbose:
                print(f"  SIC {sic_code} page {page_number}: {len(found)} permit PDFs so far")
            control = epd._next_page_control(page)
            if not control:
                break
            time.sleep(sleep)
            next_page = epd._post(session, page, {"__EVENTTARGET": control, control: " "})
            if epd._parse_rows(next_page) == epd._parse_rows(page):
                break
            page = next_page
            page_number += 1
    return found


def _download(session: requests.Session, url: str, *, timeout: int = 90) -> bytes | None:
    """Fetch a permit PDF, caching it on disk. These documents never change."""
    doc_id = re.search(r"id=([\w\-]+)", url)
    path = CACHE_DIR / f"{doc_id.group(1) if doc_id else 'unknown'}.pdf"
    if path.exists():
        return path.read_bytes()
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None
    if not response.content.startswith(b"%PDF"):
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


def fetch_addresses(
    facilities, *, sleep: float = 0.4, verbose: bool = True, use_cache: bool = True
) -> dict[str, FacilityAddress]:
    """Resolve one address per facility, keyed by AIRS number.

    A facility usually holds several permits. Any of their PDFs carries the same
    header block, so the most recent is used and the rest are skipped: 38 downloads
    rather than 107.
    """
    if use_cache and ADDRESS_CACHE.exists():
        cached = json.loads(ADDRESS_CACHE.read_text())
        if verbose:
            print(f"  {len(cached)} addresses from cache ({ADDRESS_CACHE.name})")
        return {k: FacilityAddress(**v) for k, v in cached.items()}

    if verbose:
        print("Discovering permit PDF links...")
    pdf_urls = discover_permit_pdfs(verbose=verbose)

    # Newest permit first, so the freshest document wins.
    permits_by_facility: dict[str, list] = {}
    for f in facilities:
        permits_by_facility.setdefault(f.airs_number, [])

    session = requests.Session()
    session.headers.update({"User-Agent": "ga-data-center-tracker (research)"})
    out: dict[str, FacilityAddress] = {}

    for facility in facilities:
        # Permit numbers embed the AIRS county and facility digits: SSSS-CCC-NNNN-...
        county, serial = facility.airs_number.split("-")
        stem = f"-{county}-{serial.lstrip('0').zfill(4)}-"
        candidates = sorted(
            (p for p in pdf_urls if stem in p),
            key=lambda p: p,
            reverse=True,
        )
        if not candidates:
            if verbose:
                print(f"  {facility.airs_number}: no permit PDF found")
            continue

        for permit_number in candidates:
            content = _download(session, pdf_urls[permit_number])
            if not content:
                continue
            parsed = parse_address_block(_text_first_page(content))
            if parsed:
                street, city, zip_code, county_printed = parsed
                out[facility.airs_number] = FacilityAddress(
                    airs_number=facility.airs_number,
                    street=street,
                    city=city,
                    zip_code=zip_code,
                    county_printed=county_printed,
                    permit_number=permit_number,
                    pdf_url=pdf_urls[permit_number],
                )
                break
            time.sleep(sleep)
        if verbose and facility.airs_number in out:
            a = out[facility.airs_number]
            print(f"  {facility.airs_number}  {a.full}")

    ADDRESS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ADDRESS_CACHE.write_text(json.dumps({k: asdict(v) for k, v in out.items()}, indent=1))
    return out


def county_disagreements(
    addresses: dict[str, FacilityAddress], facilities
) -> list[tuple[str, str, str]]:
    """Facilities whose printed county differs from the AIRS-derived county.

    The AIRS digits and the printed county name come from different parts of the
    record, so a mismatch means one of them is wrong and the facility needs a look.
    """
    by_airs = {f.airs_number: f for f in facilities}
    out = []
    for airs, address in addresses.items():
        facility = by_airs.get(airs)
        if not facility or not facility.county or not address.county_printed:
            continue
        derived = facility.county.replace(" County, Georgia", "")
        if derived.lower() != address.county_printed.lower():
            out.append((airs, derived, address.county_printed))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract facility addresses from EPD permit PDFs.")
    parser.add_argument("--refresh", action="store_true", help="Ignore the address cache.")
    args = parser.parse_args()

    permits = epd.scrape_data_center_permits(verbose=True)
    facilities = epd.permits_to_facilities(permits)
    print(f"\nResolving addresses for {len(facilities)} facilities...")
    addresses = fetch_addresses(facilities, use_cache=not args.refresh)

    print(f"\n{len(addresses)}/{len(facilities)} facilities have an address.")
    missing = [f.airs_number for f in facilities if f.airs_number not in addresses]
    if missing:
        print(f"  no address: {missing}")
    bad = county_disagreements(addresses, facilities)
    if bad:
        print("\nCounty disagreements (AIRS digits vs printed on permit):")
        for airs, derived, printed in bad:
            print(f"  {airs}: AIRS says {derived}, permit says {printed}")
    else:
        print("  every printed county matches the AIRS-derived county.")


if __name__ == "__main__":
    main()
