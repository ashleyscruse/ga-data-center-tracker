"""Georgia Tech EPIcenter Data Center Ordinance Hub scraper.

EPIcenter (Georgia Tech's Energy Policy and Innovation Center) maintains the
Georgia Data Center Ordinance Hub, which reviews municipal codes across 180+
Georgia cities and counties and tracks which jurisdictions have adopted a data
center ordinance or a moratorium. It is the only structured, statewide, public
record of *local government response* to data center siting, which makes it the
entry point for this dataset's community engagement strand: an ordinance or a
moratorium is a formal, dated, countable act of community response, in a way that
news coverage and meeting minutes are not.

The Hub publishes its figures as Datawrapper charts. Datawrapper serves each
chart's underlying table at ``<chart-url>/dataset.csv``, so the data is reachable
without parsing the rendered page. Three charts matter:

  * **Regulations choropleth** -> one row per county FIPS, with counts of
    operational / under-construction / planned facilities and a ``Status`` flag
    marking counties that have a data center ordinance.
  * **Moratoria range plot** -> one row per jurisdiction with moratorium start and
    expiration dates. Jurisdictions are a mix of counties and cities.
  * **Development symbol map** -> one row per facility with latitude and longitude
    and a development stage. Used as a coverage cross-check, not ingested; see
    the attribution note below.

The chart IDs are discovered from the Hub page rather than hard-coded, because
Datawrapper URLs carry a version number that changes each time EPIcenter republishes.

**Attribution.** This is Georgia Tech's compiled research product, not a primary
government record. Anything derived from it is attributed to EPIcenter, and its
redistribution terms must be confirmed with Georgia Tech before these variables
ship in a public dataset. Until then, treat the output as a validated cross-check.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from ..counties import load_reference, normalize_county

HUB_URL = "https://epicenter.energy.gatech.edu/data-center/"
DATAWRAPPER_HOST = "https://datawrapper.dwcdn.net"

ATTRIBUTION = (
    "Georgia Tech Energy Policy and Innovation Center (EPIcenter), "
    "Georgia Data Center Ordinance Hub"
)

# Chart titles as rendered in the Hub's iframes, mapped to the role each plays here.
# Matched case-insensitively on a substring so a wording tweak upstream does not
# silently drop a chart.
_CHART_ROLES = {
    "regulations": "regulations",   # "Data Center Regulations in Georgia"
    "moratoria": "moratoria",       # "Data Center Moratoria in Georgia"
    "development": "development",   # "Data Center Development in Georgia"
}

_IFRAME_RE = re.compile(
    r'<iframe[^>]*title="([^"]+)"[^>]*src=["\']?(https://datawrapper\.dwcdn\.net/[^"\'\s>]+)',
    re.I,
)

# Georgia municipalities that appear in the moratoria table, mapped to the county
# that contains their seat of government. The tracker's unit of analysis is the
# county, so a city moratorium is recorded against its county. Kept as an explicit
# table rather than inferred, so an unrecognized city fails loudly instead of being
# guessed into the wrong county.
CITY_TO_COUNTY = {
    "griffin": "Spalding County, Georgia",
    "hampton": "Henry County, Georgia",
    "lagrange": "Troup County, Georgia",
    "roswell": "Fulton County, Georgia",
}


@dataclass
class Moratorium:
    """One data center moratorium adopted by a Georgia jurisdiction."""

    jurisdiction: str           # as published, e.g. "Griffin, GA"
    jurisdiction_type: str      # "county" or "city"
    county: str | None          # tracker form, or None if unresolved
    start_date: date | None
    expiration_date: date | None
    note: str = ""
    source: str = ATTRIBUTION

    def is_active(self, on: date) -> bool:
        """Whether the moratorium is in force on ``on``.

        An unknown start date is treated as not-yet-established rather than
        assumed, so an unparsed row cannot inflate the active count.
        """
        if self.start_date is None or self.start_date > on:
            return False
        return self.expiration_date is None or self.expiration_date >= on


@dataclass
class CountyRegulation:
    """EPIcenter's per-county regulation and facility-stage record."""

    county_fips: str
    county: str | None
    has_ordinance: bool
    operational_n: int = 0
    construction_n: int = 0
    planned_n: int = 0
    source: str = ATTRIBUTION


@dataclass
class HubData:
    """Everything pulled from the Hub in one fetch."""

    moratoria: list[Moratorium] = field(default_factory=list)
    regulations: list[CountyRegulation] = field(default_factory=list)
    facility_points: list[dict[str, str]] = field(default_factory=list)


def _get(url: str, *, timeout: int = 60) -> str:
    response = requests.get(
        url, timeout=timeout, headers={"User-Agent": "ga-data-center-tracker (research)"}
    )
    response.raise_for_status()
    return response.text


def discover_chart_urls(page_html: str | None = None) -> dict[str, str]:
    """Map each role ("regulations", "moratoria", "development") to its chart URL.

    Reads the Hub page's iframes so the version-numbered Datawrapper URLs stay
    current across EPIcenter republishes.
    """
    html = page_html if page_html is not None else _get(HUB_URL)
    found: dict[str, str] = {}
    for title, url in _IFRAME_RE.findall(html):
        lowered = title.lower()
        for keyword, role in _CHART_ROLES.items():
            if keyword in lowered and role not in found:
                found[role] = url.rstrip("/")
    return found


def _fetch_dataset(chart_url: str) -> list[dict[str, str]]:
    """Fetch a Datawrapper chart's underlying table.

    Datawrapper serves comma- or tab-delimited data depending on the chart, so the
    delimiter is sniffed from the header line rather than assumed.
    """
    text = _get(f"{chart_url}/dataset.csv")
    header = text.splitlines()[0] if text else ""
    delimiter = "\t" if header.count("\t") > header.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def _parse_date(raw: str) -> date | None:
    """Parse EPIcenter's long-form dates, e.g. ``February 17, 2026``."""
    cleaned = (raw or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_jurisdiction(raw: str) -> tuple[str, str | None]:
    """Resolve a published jurisdiction label to (type, tracker county name).

    Handles both ``Troup County, GA`` and ``Griffin, GA``. Returns ``None`` for the
    county when a city is not in ``CITY_TO_COUNTY``, so it routes to manual review
    rather than being dropped or guessed.
    """
    label = (raw or "").strip().removesuffix(", GA").strip()
    if label.lower().endswith("county"):
        return "county", normalize_county(label)
    return "city", CITY_TO_COUNTY.get(label.lower())


def _parse_int(raw: str) -> int:
    value = (raw or "").strip()
    return int(value) if value.isdigit() else 0


def parse_moratoria(rows: list[dict[str, str]]) -> list[Moratorium]:
    """Parse the moratoria table. Its jurisdiction column is published unnamed."""
    moratoria: list[Moratorium] = []
    for row in rows:
        # The jurisdiction column is published with an empty header, so it is found
        # by looking for the blank key. That key is itself falsy, hence the explicit
        # ``is not None`` test.
        name_key = next((k for k in row if k is not None and not k.strip()), None)
        jurisdiction = (row.get(name_key) or "").strip() if name_key is not None else ""
        if not jurisdiction:
            continue
        kind, county = _resolve_jurisdiction(jurisdiction)
        moratoria.append(
            Moratorium(
                jurisdiction=jurisdiction,
                jurisdiction_type=kind,
                county=county,
                start_date=_parse_date(row.get("Moratorium Start Date", "")),
                expiration_date=_parse_date(row.get("Moratorium Expiration Date", "")),
                note=(row.get("Note") or "").strip(),
            )
        )
    return moratoria


def parse_regulations(rows: list[dict[str, str]]) -> list[CountyRegulation]:
    """Parse the per-county regulation table, keyed by 5-digit county FIPS."""
    fips_map = {c.fips: c.tracker_name for c in load_reference()}
    regulations: list[CountyRegulation] = []
    for row in rows:
        fips = (row.get("Five-Digit Code") or "").strip()
        if not fips:
            continue
        regulations.append(
            CountyRegulation(
                county_fips=fips,
                county=fips_map.get(fips),
                # The Status column carries "A" for counties with an ordinance and
                # is blank otherwise.
                has_ordinance=bool((row.get("Status") or "").strip()),
                operational_n=_parse_int(row.get("Operational", "")),
                construction_n=_parse_int(row.get("Under construction", "")),
                planned_n=_parse_int(row.get("Planned", "")),
            )
        )
    return regulations


def fetch_hub_data(*, verbose: bool = False) -> HubData:
    """Fetch and parse every dataset behind the Ordinance Hub."""
    charts = discover_chart_urls()
    if verbose:
        print(f"Discovered {len(charts)} EPIcenter charts: {sorted(charts)}")

    data = HubData()
    if "moratoria" in charts:
        data.moratoria = parse_moratoria(_fetch_dataset(charts["moratoria"]))
    if "regulations" in charts:
        data.regulations = parse_regulations(_fetch_dataset(charts["regulations"]))
    if "development" in charts:
        data.facility_points = _fetch_dataset(charts["development"])

    if verbose:
        print(
            f"EPIcenter: {len(data.moratoria)} moratoria, "
            f"{len(data.regulations)} county regulation rows, "
            f"{len(data.facility_points)} mapped facilities"
        )
    return data


def moratoria_to_county_counts(
    moratoria: list[Moratorium], *, active_on: date | None = None
) -> dict[str, int]:
    """Per-county count of data center moratoria.

    With ``active_on`` set, counts only moratoria in force on that date; otherwise
    counts every moratorium ever recorded for the county. Both are meaningful: an
    expired moratorium still evidences that the community formally pushed back.
    """
    counts = {c.tracker_name: 0 for c in load_reference()}
    for moratorium in moratoria:
        if not moratorium.county or moratorium.county not in counts:
            continue
        if active_on is not None and not moratorium.is_active(active_on):
            continue
        counts[moratorium.county] += 1
    return counts


# The development map's Status values, mapped to the variable each one feeds.
STAGE_VARS = {
    "operational": "dc_operational_n",
    "construction": "dc_construction_n",
    "planned": "dc_planned_n",
}
STAGE_TOTAL_VAR = "dc_mapped_n"


def points_to_stage_counts(
    points: list[dict[str, str]], *, verbose: bool = False
) -> dict[str, dict[str, int]]:
    """Per-county facility counts by development stage, plus an all-stage total.

    Counts come from the **development symbol map**, which publishes one row per
    facility, not from the regulations choropleth. That distinction matters and is
    easy to get wrong: the regulations table's ``Operational`` / ``Under
    construction`` / ``Planned`` columns are 0/1 presence flags telling you whether
    a county has any facility at that stage, so summing them undercounts badly
    (Douglas County reads 1 there and has 16 facilities on the map).

    Each point is a bare coordinate with a stage and no name or address, so it is
    resolved to a county through the Census geocoder. Results are cached on disk,
    so repeat runs cost nothing. Points that do not land in a Georgia county are
    dropped rather than assigned.
    """
    # Imported here rather than at module scope: the geocoding helper lives in the
    # cleaning layer, and only this function needs it.
    from ..cleaning.reconcile import resolve_points

    counts = {
        c.tracker_name: {v: 0 for v in (*STAGE_VARS.values(), STAGE_TOTAL_VAR)}
        for c in load_reference()
    }
    by_fips = {c.fips: c.tracker_name for c in load_reference()}
    resolved, unresolved = resolve_points(points, verbose=verbose)
    if unresolved and verbose:
        print(f"  {unresolved} EPIcenter points did not resolve to a Georgia county")

    for point in points:
        key = (
            f"{(point.get('latitude') or '').strip()},"
            f"{(point.get('longitude') or '').strip()}"
        )
        tracker_name = by_fips.get(resolved.get(key, ""))
        if tracker_name is None:
            continue
        row = counts[tracker_name]
        row[STAGE_TOTAL_VAR] += 1
        varname = STAGE_VARS.get((point.get("Status") or "").strip().lower())
        if varname:
            row[varname] += 1
    return counts


def regulations_to_ordinance_flags(regulations: list[CountyRegulation]) -> dict[str, int]:
    """Per-county 1/0 flag for whether the county has a data center ordinance."""
    flags = {c.tracker_name: 0 for c in load_reference()}
    for regulation in regulations:
        if regulation.county and regulation.county in flags and regulation.has_ordinance:
            flags[regulation.county] = 1
    return flags


def unresolved_moratoria(moratoria: list[Moratorium]) -> list[Moratorium]:
    """Moratoria whose jurisdiction did not resolve to a county, for manual review."""
    return [m for m in moratoria if m.county is None]
