# How the Georgia Data Center Tracker Works

A plain-language walkthrough of the code and the data-collection method. Written so you (or a maintainer a year from now) can understand what each piece does, how the data is actually gathered, and how to reproduce it.

For the research reasoning behind these choices, see [methodology.md](methodology.md). For the refresh procedure, see [update_guide.md](update_guide.md).

---

## 1. What this system does

It builds a county-level dataset of data center activity across all 159 Georgia counties and writes it out in the exact Excel format the Drawdown Georgia Solutions Tracker requires. It draws from four sources, produces eleven per-county variables, and keeps the facility-level records behind those counts in the same workbook.

---

## 2. The big idea

No single public database lists "all data centers in Georgia." Every available source sees a different slice, so the method is:

1. Pull from several public sources that each reveal data centers indirectly.
2. Resolve every facility to a Georgia county.
3. Count per county, keeping each source as its own variable.
4. Write the counts into the Tracker's required spreadsheet format.

Every source follows the same shape: **pull, resolve, county-match, count, deliver.**

**The part that is easy to get wrong:** the counts are *not* merged into one number. Merging would require matching facilities across sources by identity, and EPIcenter publishes bare coordinates with no names, so it cannot be done reliably. A silently wrong merge in a published dataset is worse than two honestly separate counts, so the disagreement is reported instead. See the additivity rules in [data_dictionary.md](data_dictionary.md).

---

## 3. Repository layout

| Path | What it does |
|---|---|
| `src/ga_data_center_tracker/counties.py` | The county backbone. Builds and loads the 159-county reference table; normalizes messy county strings. |
| `src/ga_data_center_tracker/scrapers/ga_epd_air.py` | Georgia EPD air permits. The dated source, and the cleanest county resolution. |
| `src/ga_data_center_tracker/scrapers/epd_permit_docs.py` | Reads facility addresses out of the permit PDFs, which the search grid omits. |
| `src/ga_data_center_tracker/scrapers/epicenter.py` | Georgia Tech EPIcenter. Facility counts by stage, plus ordinances and moratoria. |
| `src/ga_data_center_tracker/scrapers/institutional.py` | Curated registry of campus data centers. Not scraped; hand-maintained with enforced citations. |
| `src/ga_data_center_tracker/scrapers/institutional_discovery.py` | Searches NSF award records for campus computing facilities and emits candidates for review. |
| `src/ga_data_center_tracker/scrapers/epa_frs.py` | EPA Facility Registry Service. An independent federal cross-check, currently returning nothing. |
| `src/ga_data_center_tracker/cleaning/reconcile.py` | Compares the sources county by county and renders the reconciliation report. |
| `src/ga_data_center_tracker/delivery.py` | The output format. Writes the GT-required `.xlsx` workbook. |
| `src/ga_data_center_tracker/pipeline.py` | The orchestrator. One command runs everything. |
| `src/ga_data_center_tracker/ordinances.py` | Builds the companion ordinance and moratorium workbook. |
| `data/reference/ga_counties.csv` | The committed county reference table (the join key for everything). |
| `data/processed/` | The delivered dataset. |
| `docs/` | Methodology, data dictionary, sources, output format, update guide, and this walkthrough. |

---

## 4. The county backbone (`counties.py`)

Everything joins on county, so this is the single source of truth for county names and codes.

- **Where it comes from:** the U.S. Census Bureau's authoritative national county file, filtered to Georgia (state FIPS `13`).
- **A built-in safety check:** if it does not find exactly **159** Georgia counties, it raises rather than proceeding. That guards against the upstream file changing or downloading incompletely.
- **The naming rule:** the Tracker wants `Fulton County, Georgia`. `County.tracker_name` produces exactly that, so nothing downstream hand-types a county name.
- **Cleaning messy inputs:** `normalize_county()` takes whatever a source calls a county ("Fulton", "FULTON COUNTY", "Fulton County, GA") and resolves it to canonical form, or returns nothing if it cannot match, so bad values get flagged rather than guessed.

---

## 5. Georgia EPD air permits (`scrapers/ga_epd_air.py`)

**The source.** Georgia EPD's Air Permit Search Engine publishes every air permit the state has issued. Data centers appear because their diesel backup generators need an air permit before the facility is built.

**Two encodings make this source unusually clean:**

- The **AIRS number** `CCC-NNNNN` starts with the county's 3-digit FIPS. `097-00098` is Douglas County, FIPS 13097. Prefix `13` and you have the tracker's join key directly. There is no geocoding step, so there is no geocoding error.
- The **permit number** starts with the facility's SIC code, confirming each record's classification independently of the search filter.

**Which codes to search was determined empirically.** The full state database (about 10,200 permits across 3,044 facilities) was pulled once and inspected. Two codes carry data centers wholesale: **7374** (Data Processing and Preparation, 26 facilities) and **7376** (Computer Facilities Management Services, 8 facilities). Searching 7374 alone understated the count by about a quarter.

**Two more codes carry data centers mixed with unrelated industry**, so they are filtered to named facilities rather than swept in. `ADJUDICATED_INCLUSIONS` holds four, each with a recorded reason: Google's Douglas County data center (filed under the 7389 catch-all, alongside a sterilization plant), AT&T Data Center, Savvis AT1, and 375 Riverside Pkwy. `ADJUDICATED_EXCLUSIONS` records the rejections, including Hartsfield-Jackson airport, so nobody re-litigates them. Carrier switching centers sit on neither list: that is the open scope question.

**Permits collapse to facilities.** A facility accumulates permit records over time (issuance, amendments, renewals). They collapse to one record per AIRS number, keeping the earliest issuance as the first-permit date and the latest as most recent activity. Counting permits instead would overstate counties whose facilities amend frequently.

**What you get:** 107 permit records resolving to 38 facilities across 11 counties, each dated. Those dates are what make the permitting curve possible.

---

## 6. Georgia Tech EPIcenter (`scrapers/epicenter.py`)

EPIcenter maintains the Georgia Data Center Ordinance Hub. It publishes as Datawrapper charts, and Datawrapper serves each chart's underlying table at `<chart-url>/dataset.csv`, so the data is reachable without parsing the rendered page. Chart IDs are discovered from the Hub page at run time, because Datawrapper URLs carry a version number that changes on every republish.

Three charts matter, and **they are not interchangeable**:

| Chart | What it gives | Used for |
|---|---|---|
| Development symbol map | One row per facility: lat, lon, stage | `dc_mapped_n`, `dc_operational_n`, `dc_construction_n`, `dc_planned_n` |
| Regulations choropleth | One row per county: a `Status` flag and stage columns | `dc_ordinance` only |
| Moratoria range plot | One row per jurisdiction, with dates | `dc_moratorium_n`, `dc_moratorium_active_n` |

**The trap, documented because it already caught this project once.** The regulations choropleth has columns named `Operational`, `Under construction`, and `Planned`. They look like counts. They are 0/1 presence flags saying whether the county has any facility at that stage. Reading them as counts gives **27 facilities statewide instead of 123**, and reports Douglas County as 1 when the map shows 16. Stage counts come from the development map, and `points_to_stage_counts()` is the only function that produces them. Four tests guard this.

**Facility points are matched by place, not identity.** Each point is a bare coordinate with a stage, no name and no address, so it is reverse-geocoded to a county through the Census geocoder. Results cache to disk, so re-runs are effectively free.

**Jurisdiction resolution for moratoria.** Counties match directly. Cities go through an explicit `CITY_TO_COUNTY` table, so an unrecognized city resolves to nothing and routes to manual review rather than being guessed into the wrong county. Expired moratoria stay in the cumulative count, because an expired moratorium is still evidence the community formally responded; a separate variable reports only those in force.

---

## 7. The institutional registry (`scrapers/institutional.py`)

The one source that is not scraped, because there is nothing to scrape: campus data centers appear in no statewide register.

They are also invisible to every other source here. A campus facility's backup generation usually falls below the EPD permitting threshold, EPIcenter's map tracks the commercial buildout, and commercial catalogs track leasable colocation space rather than owner-occupied research infrastructure. Under the dataset's definition they are data centers, so they are counted.

**The rule that makes a hand-maintained source publishable:** every record must carry a public `source_url`, and `load_registry()` raises on one that does not. County and stage are validated against the same reference table and vocabulary as every other source. A typo fails the build instead of shipping. The URLs travel on the `Original` sheet so any reader can check them.

---

## 8. EPA FRS (`scrapers/epa_frs.py`)

A federal cross-check rather than a primary count. EPA offers a one-shot joined query that hits a server-side bug, so the scraper joins three single-table lookups itself: NAICS 518210 records, then program-facility lookups to get registry ID and state (keeping only Georgia), then facility-site lookups for county and address. It deduplicates by registry ID and retries EPA's intermittent 500s with backoff.

**Current status: returning 0 records**, where it returned 22 in July 2026. The scraper runs without error, so the problem is the query rather than the code. Run with `--skip-frs` until it is fixed.

---

## 9. Reconciliation (`cleaning/reconcile.py`)

Compares the sources county by county and writes `docs/reconciliation-report.txt`. This is the quality check that found the SIC 7376 gap in the first place, and it is what you run after any refresh to confirm the sources still agree with each other.

**The honest limit, stated in the report itself:** a county where EPD finds 1 and EPIcenter finds 4 tells you three more facilities exist there at some stage. It does not establish that EPD's one is among EPIcenter's four. That would need names, which EPIcenter does not publish.

---

## 10. Shaping the deliverable (`delivery.py`)

`write_workbook()` builds the five sheets Georgia Tech requires, so delivery is mechanical rather than hand-assembled in Excel:

- **Original**: facility-level records as pulled, stacked across sources into a shared schema.
- **Transformed**: the wide county-by-variable table, 159 rows. Built by `build_transformed_rows()`.
- **Long**: exactly three columns, `county`, `varname`, `datavalue`. This is the integration target Power BI reads.
- **Data Description**: provenance per variable.
- **Codebook**: one row per variable: name, definition, units.

**Two guards.** `_validate_counties()` checks every county in the Long sheet against the reference table and refuses to write a non-canonical join key. And the Codebook and Data Description sheets are generated from the same `Variable` objects the pipeline registers, so the documentation cannot drift from the data it describes.

**Missing is not zero.** On the Transformed sheet, a variable never computed for a county is left blank; a variable computed to be zero is `0`. Those are different claims.

---

## 11. Orchestration (`pipeline.py`)

`run()` is the single command that ties it together:

1. Ensure the county reference table exists.
2. Run each source and merge its per-county counts into `county_values`.
3. Register a `Variable` per column, carrying its own provenance.
4. Build the Long and Transformed reshapes.
5. Write the GT-conformant workbook.

**How a new source slots in:** same `pull -> resolve -> county-match` shape, counts merge into `county_values`, a `Variable` documents it. No restructuring.

---

## 12. How to run it

```bash
# 1. (re)build the county reference table
python -m ga_data_center_tracker.counties

# 2. run the pipeline and write the dataset
python -m ga_data_center_tracker.pipeline --skip-frs --out data/processed/ga_data_centers.xlsx

# 3. confirm nothing broke
pytest
```

---

## 13. What is built vs. what is next

**Built and working:**
- County reference table, 159 counties, FIPS-keyed.
- Four sources wired in, producing 11 per-county variables.
- Cross-source reconciliation with a written report.
- Delivery format: all five required sheets, validated.
- 98 tests, no network required.

**Next:**
- Resident sentiment: county commission and zoning minutes, public comment records. The live engagement variables capture what local *government* did, not what residents said.
- Composite indicators, with normalization and weighting documented before anything composite ships.
- Resolve the institutional-versus-mapped overlap by coordinate, so the two facility counts can be safely combined.
- Repair EPA FRS.

---

## 14. Honest limitations

- **Every count here is a documented floor, not a census.** EPD captures facilities that reached air permitting. EPIcenter captures the commercial buildout. The institutional registry captures campus facilities that are publicly documented well enough to cite. None of them is complete, and the methodology says so for each.
- **The facility counts cannot be added together.** See the additivity rules in the data dictionary. Adding them would double-count.
- **Corporate enterprise data centers are a known gap**, invisible for the same structural reasons campus facilities were.
- **County permit coverage will be uneven** when that source is built. Georgia's counties publish inconsistently; the plan is to cover high-activity counties well and document the gaps rather than claim completeness.
