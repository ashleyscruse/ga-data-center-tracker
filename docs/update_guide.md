# Update Guide

How to regenerate the dataset, so it can be refreshed in future years without starting over. Written for a maintainer who did not build the pipeline.

## Setup (once)

```bash
# From the repository root, in a virtual environment:
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs the package and its dependencies
pip install -e ".[dev]"     # adds pytest
```

## The short version

```bash
python -m ga_data_center_tracker.pipeline --skip-frs --out data/processed/ga_data_centers.xlsx
pytest
```

That rebuilds the delivered workbook from scratch and confirms nothing broke. Everything below explains the pieces.

## Rebuild the county reference table

The reference table (`data/reference/ga_counties.csv`) rarely changes, but to rebuild it from the authoritative Census source:

```bash
python -m ga_data_center_tracker.counties
# or, after install:
gdct-build-counties
```

This refuses to write unless it finds exactly 159 Georgia counties, guarding against a changed upstream file.

## Run the full pipeline

```bash
python -m ga_data_center_tracker.pipeline --out data/processed/ga_data_centers.xlsx
```

The output is a Solutions Tracker `.xlsx` workbook (see [output_format.md](output_format.md)).

### Flags you will actually use

| Flag | When |
|---|---|
| `--skip-frs` | **Currently the normal way to run.** EPA FRS is returning 0 records (see below), and the pass is slow because it makes thousands of per-ID lookups. |
| `--skip-epicenter` | Rebuild without any Georgia Tech EPIcenter data, if redistribution terms are ever declined. Expect the dataset to drop to the EPD permit record plus the institutional registry. |
| `--max-lookups 50` | Cap the FRS lookups for a quick smoke test. |

### How long it takes

The EPD scrape is a few minutes (it pages through the state permit search). EPIcenter is seconds, because the 123 facility points are reverse-geocoded once and then cached in `data/interim/point_county_cache.json`. **Delete that cache file to force fresh geocoding**, which takes about a minute and should only be needed if EPIcenter adds facilities.

## Refresh the reconciliation report

The cross-source comparison in `docs/reconciliation-report.txt` is what tells you whether the sources still agree with each other. It is not rebuilt by the pipeline, so regenerate it after a refresh:

```python
from ga_data_center_tracker.scrapers import epicenter, ga_epd_air
from ga_data_center_tracker.cleaning import reconcile

permits = ga_epd_air.scrape_data_center_permits()
facilities = ga_epd_air.permits_to_facilities(permits)
hub = epicenter.fetch_hub_data()
report = reconcile.reconcile(epd_facilities=facilities, epicenter_points=hub.facility_points)
open("docs/reconciliation-report.txt", "w").write(reconcile.format_report(report))
```

**Check the statewide EPIcenter total in that report against `dc_mapped_n` summed across the workbook's `Transformed` sheet. They must match.** They come from the same points by different paths, so a mismatch means something moved.

## Facility addresses (permit PDFs)

Addresses are not in the EPD search grid; they are on the first page of each permit PDF. The pipeline pulls them automatically and caches them, so a normal rebuild costs nothing.

```bash
python -m ga_data_center_tracker.scrapers.epd_permit_docs            # report
python -m ga_data_center_tracker.scrapers.epd_permit_docs --refresh  # ignore the cache
```

PDFs cache to `data/raw/epd_permits/`, parsed addresses to `data/interim/epd_facility_addresses.json`. Delete the JSON to re-parse without re-downloading.

The report also cross-checks the county printed on the permit against the county derived from the AIRS number. **Those should always agree; investigate any that do not**, because it means one of the two is wrong for that facility.

## Maintaining the institutional registry

The one source that is not scraped. Campus data centers appear in no statewide register, so `scrapers/institutional.py` holds them as a hand-maintained list.

To add a facility, append an `InstitutionalFacility` to `REGISTRY` with a public `source_url`. **The build raises an error on a record without one**, so an unsourced facility cannot ship by accident. County and stage are validated against the same reference table and vocabulary as every other source, so a typo fails loudly.

To find facilities you do not already know about, run the discovery pass:

```bash
python -m ga_data_center_tracker.scrapers.institutional_discovery
```

It searches NSF Award Search for MRI and CC* awards to Georgia institutions indicating computing hardware, and writes `data/interim/institutional-candidates.txt`. Institutions already in the registry are marked. **Review each candidate before adding it**: an award proves an institution bought a cluster, not that it houses one. Confirm a physical facility, its county, and a public source URL.

Before adding, check the inclusion rule in [methodology.md](methodology.md): a purpose-built facility housing institutional computing at data center scale. A departmental server closet does not qualify.

## Recon: where counties publish minutes

```bash
python -m ga_data_center_tracker.scrapers.minutes_recon
```

Probes each target county's website and fingerprints its agenda vendor, writing `data/interim/minutes-recon.txt`. Re-run it when the target county set changes, since counties change vendors and the set grows as facilities appear.

Two tables in the module need hand-maintenance when a probe fails: `SITE_OVERRIDES` for counties whose hostname does not follow the usual patterns (consolidated city-county governments, mostly), and `PLATFORM_MARKERS` when a new vendor shows up. **Fingerprints must match vendor domains, never bare words**: an earlier version matched the substring "escribe", which is contained in "describe", and reported a platform on any county whose site used that ordinary word.

Both discovery passes write to `data/interim/`, which is gitignored. They are working
notes for whoever maintains this, not deliverables, and they name institutions and
counties that have not been confirmed yet.

## What lives where

| Path | Tracked in git? | Contents |
|---|---|---|
| `data/reference/` | Yes | County reference table (committed). |
| `data/processed/` | Yes | Final deliverable dataset (committed). |
| `data/raw/`, `data/interim/` | No (gitignored) | Scraped and intermediate data, regenerated by the pipeline. The geocode cache lives here. |
| `_admin/`, `_planning/` | No (gitignored) | Contracts, budget, planning notes. |

## Known issues to check on a refresh

| Issue | What to do |
|---|---|
| **EPA FRS returns 0 records.** The scraper runs without error, but the NAICS 518210 query no longer yields the 22 Georgia facilities it returned in July 2026. | Re-run without `--skip-frs` and see whether EPA's Envirofacts service has recovered. If not, the three-lookup join in `scrapers/epa_frs.py` needs re-checking against EPA's current schema. |
| **EPIcenter republishes its charts under new Datawrapper version numbers.** | Handled automatically: chart URLs are discovered from the Hub page at run time, not hard-coded. If discovery returns fewer than 3 charts, EPIcenter changed their iframe titles and `_CHART_ROLES` needs updating. |
| **A moratorium is filed by a city not in the lookup table.** | It routes to manual review rather than being guessed into a county. Add the city to `CITY_TO_COUNTY` in `scrapers/epicenter.py`. |
| **Georgia EPD reclassifies data centers under a new SIC code.** | The searched codes are 7374 and 7376. See the methodology for how those were determined empirically; repeat that check by pulling the full permit database if counts look wrong. |

## Refreshing a single source

Each source is a module under `src/ga_data_center_tracker/scrapers/`. To refresh one in isolation, call its scraper directly:

```python
from ga_data_center_tracker.scrapers import ga_epd_air
permits = ga_epd_air.scrape_data_center_permits()
facilities = ga_epd_air.permits_to_facilities(permits)
counts = ga_epd_air.facilities_to_county_counts(facilities)
```

## Adding a new source

1. Write a scraper module in `scrapers/` that returns typed records and exposes a `..._to_county_counts()` aggregator. Follow `ga_epd_air.py` as the template; it is the cleanest of the three and currently the healthiest.
2. Document the source in [sources.md](sources.md) and its variables in [data_dictionary.md](data_dictionary.md), including its coverage limit.
3. Wire it into `pipeline.py`: merge its per-county counts into `county_values` and add its `Variable` entries. The `Codebook` and `Data Description` sheets generate from those, so they cannot drift from the data.
4. Add tests under `tests/`.
5. State in the methodology whether the new count is additive to the existing ones. So far none of them are.

## Running tests

```bash
pytest
```

98 tests, no network access required. They cover county normalization, the delivery format's guardrails, EPD permit parsing, EPIcenter parsing and stage counting, the reconciliation, the institutional registry's validation rules, and the NSF discovery filters.
