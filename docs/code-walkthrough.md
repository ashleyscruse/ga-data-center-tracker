# How the Georgia Data Center Tracker Works

A plain-language walkthrough of the code and the data-collection method. Written so you (or a maintainer a year from now) can understand what each piece does, how the data is actually gathered, and how to reproduce it.

---

## 1. What this system does

It builds a county-level dataset of data center activity in Georgia and writes it out in the exact Excel format the Drawdown Georgia Solutions Tracker requires. Today it draws from one source (EPA's facility registry); it is built so more sources slot in without rework. The output is a per-county count of data centers, backed by the facility-level records behind those counts.

---

## 2. The big idea

No single public database lists "all data centers in Georgia." So the method is:

1. Pull from a public source that reveals data centers indirectly (a federal environmental registry, a utility queue, county permits).
2. Resolve each facility to a Georgia county using its FIPS code.
3. Deduplicate, then count facilities per county.
4. Write the counts into the Tracker's required spreadsheet format.

Every source follows that same shape: **pull, resolve, county-match, count, deliver.** The first source (EPA FRS) is the template the others copy.

---

## 3. Repository layout

| Path | What it does |
|---|---|
| `src/ga_data_center_tracker/counties.py` | The county backbone. Builds and loads the 159-county reference table; normalizes messy county strings. |
| `src/ga_data_center_tracker/scrapers/epa_frs.py` | The first data source. Pulls data center facilities from EPA FRS and resolves them to counties. |
| `src/ga_data_center_tracker/delivery.py` | The output format. Writes the GT-required `.xlsx` workbook (Original, Long, Data Description, Codebook). |
| `src/ga_data_center_tracker/pipeline.py` | The orchestrator. Runs the county setup, the scraper, the aggregation, and the delivery in one command. |
| `data/reference/ga_counties.csv` | The committed county reference table (the join key for everything). |
| `data/processed/` | The output datasets. |
| `docs/` | Methodology, data dictionary, sources, output format, and this walkthrough. |

---

## 4. The county backbone (`counties.py`)

Everything joins on county, so this is the single source of truth for county names and codes.

- **Where it comes from:** the U.S. Census Bureau's authoritative national county file, filtered to Georgia (state FIPS `13`). `fetch_georgia_counties()` downloads and parses it.
- **A built-in safety check:** if it does not find exactly **159** Georgia counties, it raises an error instead of proceeding. That guards against the upstream file changing or downloading incompletely.
- **The naming rule:** the Tracker wants county names as `Fulton County, Georgia`. The `County.tracker_name` property produces exactly that, so nothing downstream hand-types a county name.
- **Cleaning messy inputs:** `normalize_county()` takes whatever a source calls a county ("Fulton", "FULTON COUNTY", "Fulton County, GA") and resolves it to the canonical `Fulton County, Georgia`, or returns nothing if it cannot match, so bad values get flagged rather than guessed.

Regenerate the table with: `python -m ga_data_center_tracker.counties`

---

## 5. Getting the facility data (`scrapers/epa_frs.py`)

This is the heart of "what I did to get the data."

**The source.** EPA's Facility Registry Service (FRS) is a free, public federal database of facilities regulated under environmental programs. Data centers appear in it because their diesel **backup generators** require **air permits**, which registers the facility with EPA. FRS classifies them under the federal data center industry code, **NAICS 518210**.

**The method (a three-step join, done in Python).** EPA offers a one-shot joined query, but it hits a server-side bug, so the scraper joins three single-table lookups itself:

1. `fetch_data_center_naics_records()`: get every facility nationwide classified as a data center (NAICS 518210). This returns program-system IDs.
2. `fetch_program_facility(id)`: for each, look up its record to get the registry ID and state, and **keep only Georgia**.
3. `fetch_facility_site(registry_id)`: for each Georgia facility, get its county FIPS, name, and address.

**Then two cleanup steps:**
- **Deduplicate by registry ID**, so a facility holding several permits is counted once.
- **County-match** via `_resolve_county()`, which prefers the FIPS code the record carries and falls back to matching the county name through `normalize_county()`.

**An efficiency shortcut.** Some program IDs are state-specific. If a non-Georgia state program produced the record, the facility cannot be in Georgia, so the scraper skips that lookup. That removes roughly a quarter of the network calls.

**Built to survive a flaky API.** EPA's service intermittently returns 500 errors. `_get_json()` retries with backoff, and if an ID still fails the run logs and skips it rather than crashing. That is why a full run can be re-checked afterward: the skipped IDs are known, and we confirmed none of them were Georgia.

**What you get out:** a list of `FacilityRecord`s, each with a registry ID, name, county (in tracker form), FIPS, city, address, and the program it came from. `records_to_county_counts()` then aggregates these to a per-county count, with all 159 counties present (zeros included) so the result is dense and ready for the Tracker.

---

## 6. Shaping the deliverable (`delivery.py`)

Georgia Tech requires each dataset as an `.xlsx` workbook with specific sheets. `write_workbook()` builds exactly that, so delivery is mechanical rather than hand-assembled in Excel.

Sheets produced:
- **Original**: the facility-level records as pulled.
- **Transformed**: only if transformed rows are supplied (omitted otherwise, per GT's rule).
- **Long**: exactly three columns: `county`, `varname`, `datavalue`.
- **Data Description**: provenance per variable (source, vintage, date pulled, original name, transformations).
- **Codebook**: one row per variable: name, definition, units.

**A guard against bad joins:** before writing, `_validate_counties()` checks every county in the Long sheet against the reference table and refuses to write if any county is not in canonical `X County, Georgia` form. It will not silently ship a broken join key.

---

## 7. Orchestration (`pipeline.py`)

`run()` is the single command that ties it together:

1. Ensure the county reference table exists.
2. Run the EPA FRS scraper and aggregate to per-county counts.
3. Assemble the dataset: the Long sheet (counts), the Original sheet (facility records), and the variable documentation.
4. Write the GT-conformant workbook.

**How new sources slot in:** when the Georgia Power queue or county permits come online, their scraper follows the same `pull -> resolve -> county-match` shape, their per-county counts merge into the `county_values` map, and a new `Variable` documents them. No restructuring needed.

---

## 8. How to run it / reproduce

```bash
# from the repo root, with the virtual environment active
# 1. (re)build the county reference table
python -m ga_data_center_tracker.counties

# 2. run the full pipeline and write the dataset
python -m ga_data_center_tracker.pipeline --out data/processed/ga_data_centers.xlsx

# quick test run (cap the lookups so it finishes fast)
python -m ga_data_center_tracker.pipeline --out data/processed/test.xlsx --max-lookups 100
```

The output `.xlsx` is the deliverable, ready to hand to Georgia Tech.

---

## 9. What is built vs. what is next

**Built and working:**
- County reference table (159 counties, FIPS-keyed).
- EPA FRS scraper (operations layer): 22 verified facilities across 10 counties.
- Delivery format: writes GT's required sheets, validated.
- Pipeline: runs end to end on the FRS source.

**Next (each is a new scraper on the same template):**
- Georgia Power interconnection queue (proposals).
- County building permits (construction).
- Public records of community engagement (citizen support and concerns).

---

## 10. Honest limitations

- **EPA FRS is a floor, not a census.** It only captures facilities that filed an environmental permit, so it undercounts. It catches operational sites, not proposals. The other sources exist precisely to fill those gaps.
- **Classification depends on EPA.** A data center filed under a parent company's industry code, rather than NAICS 518210, will be missed. A planned broadening of the FRS search (by facility name) would catch some of these.
- **County coverage for permits will be uneven.** Georgia's 159 counties publish permit data inconsistently; the plan is to cover the high-activity counties well and document where gaps remain, rather than claim total completeness.
