"""Cross-source reconciliation.

Three sources count Georgia data centers and they do not agree. That disagreement is
information, not noise, and this module makes it explicit rather than hiding it behind a
single merged number:

  * **Georgia EPD air permits** finds facilities that have been through state air
    permitting. Exactly county-resolved, dated, and the most conservative count.
  * **EPA FRS** finds facilities registered federally under NAICS 518210.
  * **Georgia Tech EPIcenter** maps facilities by latitude and longitude, including
    proposals that have not applied for anything yet.

EPIcenter publishes its facilities as bare coordinates with a development stage and no
name or address, so its points cannot be matched to EPD records by identity. They can be
matched by *place*: each point is resolved to a county through the Census Bureau's
geocoder, and the sources are then compared county by county.

That is the honest limit of this reconciliation, and it is stated in the output. A county
where EPD finds 1 and EPIcenter finds 4 tells you three more facilities exist there at some
stage; it does not tell you that EPD's one is among EPIcenter's four. Establishing that
would require facility names, which EPIcenter does not publish.

What the comparison is actually for: bounding the coverage gap, and pointing the next round
of collection at the counties where the sources disagree most.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from ..counties import load_reference

CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# Reverse geocoding 100+ points is slow and the answers never change, so results are
# cached to disk. Delete the file to force a fresh pass.
_REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_PATH = _REPO_ROOT / "data" / "interim" / "point_county_cache.json"

GEORGIA_STATE_FIPS = "13"


@dataclass
class CountyComparison:
    """One county's counts, as each source sees it."""

    county: str
    county_fips: str
    epd_permitted: int = 0          # GA EPD air permits
    frs_registered: int = 0         # EPA FRS
    epicenter_total: int = 0        # EPIcenter, all stages
    epicenter_operational: int = 0
    epicenter_construction: int = 0
    epicenter_planned: int = 0

    @property
    def gap(self) -> int:
        """How many more facilities EPIcenter sees than EPD does.

        Negative means EPD found facilities EPIcenter's map does not show, which is the
        more surprising direction and worth investigating by hand.
        """
        return self.epicenter_total - self.epd_permitted

    @property
    def has_any(self) -> bool:
        return bool(self.epd_permitted or self.frs_registered or self.epicenter_total)


@dataclass
class Reconciliation:
    """The full comparison, plus the statewide totals and the flagged counties."""

    counties: list[CountyComparison] = field(default_factory=list)
    unresolved_points: int = 0      # points that did not land in a Georgia county

    @property
    def active_counties(self) -> list[CountyComparison]:
        """Counties where at least one source found something."""
        return [c for c in self.counties if c.has_any]

    def totals(self) -> dict[str, int]:
        return {
            "epd_permitted": sum(c.epd_permitted for c in self.counties),
            "frs_registered": sum(c.frs_registered for c in self.counties),
            "epicenter_total": sum(c.epicenter_total for c in self.counties),
            "epicenter_operational": sum(c.epicenter_operational for c in self.counties),
            "epicenter_construction": sum(c.epicenter_construction for c in self.counties),
            "epicenter_planned": sum(c.epicenter_planned for c in self.counties),
            "counties_with_any_activity": len(self.active_counties),
        }

    def epd_blind_spots(self) -> list[CountyComparison]:
        """Counties where EPIcenter maps facilities and EPD permits show none.

        These are the counties to look at first: either the facilities are pre-permit
        proposals (expected), or EPD classified them under a different SIC code (a real
        gap in our search).
        """
        return sorted(
            [c for c in self.active_counties if c.epicenter_total and not c.epd_permitted],
            key=lambda c: -c.epicenter_total,
        )

    def epicenter_blind_spots(self) -> list[CountyComparison]:
        """Counties where EPD permitted facilities that EPIcenter's map does not show.

        The more surprising direction. A permitted facility is a real facility, so these
        are candidates to send back to EPIcenter as additions.
        """
        return sorted(
            [c for c in self.active_counties if c.epd_permitted and not c.epicenter_total],
            key=lambda c: -c.epd_permitted,
        )


def _load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))


def point_to_county_fips(lat: float, lon: float, *, timeout: int = 30) -> str | None:
    """Resolve one coordinate to a 5-digit county FIPS via the Census geocoder.

    Returns ``None`` if the point does not fall in a county the geocoder recognizes,
    which happens for coordinates just offshore or malformed rows.
    """
    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Counties",
        "format": "json",
    }
    response = requests.get(CENSUS_GEOCODER, params=params, timeout=timeout)
    response.raise_for_status()
    counties = response.json().get("result", {}).get("geographies", {}).get("Counties", [])
    return counties[0].get("GEOID") if counties else None


def resolve_points(
    points: list[dict[str, str]], *, sleep: float = 0.2, verbose: bool = False
) -> tuple[dict[str, str], int]:
    """Resolve EPIcenter facility points to county FIPS codes.

    Returns ``(point_key -> county_fips, unresolved_count)``. Results are cached on disk
    by coordinate, so re-runs are nearly free.
    """
    cache = _load_cache()
    resolved: dict[str, str] = {}
    unresolved = 0
    fetched = 0

    for point in points:
        lat_raw = (point.get("latitude") or "").strip()
        lon_raw = (point.get("longitude") or "").strip()
        if not lat_raw or not lon_raw:
            unresolved += 1
            continue
        key = f"{lat_raw},{lon_raw}"

        if key in cache:
            fips = cache[key]
        else:
            try:
                fips = point_to_county_fips(float(lat_raw), float(lon_raw)) or ""
            except (ValueError, requests.RequestException) as exc:
                if verbose:
                    print(f"  could not resolve {key}: {exc}")
                fips = ""
            cache[key] = fips
            fetched += 1
            time.sleep(sleep)
            if verbose and fetched % 20 == 0:
                print(f"  geocoded {fetched} new points...")

        if fips.startswith(GEORGIA_STATE_FIPS):
            resolved[key] = fips
        else:
            unresolved += 1

    if fetched:
        _save_cache(cache)
    if verbose:
        print(f"  resolved {len(resolved)} points, {unresolved} unresolved "
              f"({fetched} newly geocoded, rest from cache)")
    return resolved, unresolved


def reconcile(
    *,
    epd_facilities,
    epicenter_points: list[dict[str, str]],
    frs_records=None,
    verbose: bool = False,
) -> Reconciliation:
    """Build the county-by-county comparison across every source.

    Args:
        epd_facilities: ``ga_epd_air.FacilityRecord`` list.
        epicenter_points: raw point rows from the EPIcenter development map.
        frs_records: optional ``epa_frs.FacilityRecord`` list.
        verbose: print geocoding progress.
    """
    counties = load_reference()
    by_fips = {
        c.fips: CountyComparison(county=c.tracker_name, county_fips=c.fips) for c in counties
    }

    for facility in epd_facilities:
        if facility.county_fips in by_fips:
            by_fips[facility.county_fips].epd_permitted += 1

    for record in frs_records or []:
        if record.county_fips in by_fips:
            by_fips[record.county_fips].frs_registered += 1

    if verbose:
        print(f"Reverse geocoding {len(epicenter_points)} EPIcenter facility points...")
    resolved, unresolved = resolve_points(epicenter_points, verbose=verbose)

    for point in epicenter_points:
        key = f"{(point.get('latitude') or '').strip()},{(point.get('longitude') or '').strip()}"
        fips = resolved.get(key)
        if not fips or fips not in by_fips:
            continue
        comparison = by_fips[fips]
        comparison.epicenter_total += 1
        stage = (point.get("Status") or "").strip().lower()
        if stage == "operational":
            comparison.epicenter_operational += 1
        elif stage == "construction":
            comparison.epicenter_construction += 1
        elif stage == "planned":
            comparison.epicenter_planned += 1

    return Reconciliation(
        counties=[by_fips[c.fips] for c in counties],
        unresolved_points=unresolved,
    )


def format_report(reconciliation: Reconciliation) -> str:
    """Render the reconciliation as a plain-text report for the methodology appendix."""
    totals = reconciliation.totals()
    lines = [
        "Cross-source reconciliation, Georgia data centers",
        "=" * 64,
        "",
        "Statewide totals",
        f"  GA EPD air permits (permitted)     {totals['epd_permitted']:>4}",
        f"  EPA FRS (federally registered)     {totals['frs_registered']:>4}",
        f"  EPIcenter mapped, all stages       {totals['epicenter_total']:>4}",
        f"    of which operational             {totals['epicenter_operational']:>4}",
        f"    of which under construction      {totals['epicenter_construction']:>4}",
        f"    of which planned                 {totals['epicenter_planned']:>4}",
        f"  Counties with any activity         {totals['counties_with_any_activity']:>4}",
        "",
        f"  EPIcenter points not resolved to a Georgia county: "
        f"{reconciliation.unresolved_points}",
        "",
        "County detail (sources disagree by design; see methodology)",
        f"  {'county':<26}{'EPD':>5}{'FRS':>5}{'EPIc':>6}{'oper':>6}{'const':>6}{'plan':>6}",
    ]
    for c in sorted(
        reconciliation.active_counties,
        key=lambda x: (-x.epicenter_total, -x.epd_permitted, x.county),
    ):
        short = c.county.replace(" County, Georgia", "")
        lines.append(
            f"  {short:<26}{c.epd_permitted:>5}{c.frs_registered:>5}"
            f"{c.epicenter_total:>6}{c.epicenter_operational:>6}"
            f"{c.epicenter_construction:>6}{c.epicenter_planned:>6}"
        )

    blind = reconciliation.epd_blind_spots()
    lines += ["", f"Counties EPIcenter maps but EPD permits do not reach ({len(blind)}):"]
    for c in blind[:15]:
        lines.append(
            f"  {c.county.replace(' County, Georgia', ''):<26}"
            f"{c.epicenter_total:>3} mapped  "
            f"({c.epicenter_planned} planned, {c.epicenter_construction} building, "
            f"{c.epicenter_operational} operating)"
        )

    reverse = reconciliation.epicenter_blind_spots()
    lines += ["", f"Counties EPD permits but EPIcenter's map does not show ({len(reverse)}):"]
    for c in reverse:
        lines.append(
            f"  {c.county.replace(' County, Georgia', ''):<26}{c.epd_permitted:>3} permitted"
        )

    return "\n".join(lines)
