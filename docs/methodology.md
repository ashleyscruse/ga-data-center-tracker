# Methodology

How the Georgia Data Center Tracker dataset is built. This document is delivered alongside the dataset and is written so the work can be understood, trusted, and reproduced. It is a living document; sections marked _(planned)_ firm up as each source and indicator is built. For a code-level walkthrough, see [code-walkthrough.md](code-walkthrough.md).

## Scope

The dataset describes data center activity in each of Georgia's 159 counties across four strands: proposals, construction, operations, and community engagement. The unit of analysis is the county. One row per county.

Phase 5 is built entirely from free, public, redistributable sources (see [sources.md](sources.md)). Commercial catalogs named in the original SOW (Baxtel, Data Center Hawk, DataCenterMap) are deferred to a future phase because their terms restrict republishing in a public dataset.

## County as the unit of analysis

The Solutions Tracker joins on county name in the exact form `X County, Georgia`. The county reference table (`data/reference/ga_counties.csv`) is built from the U.S. Census Bureau's authoritative national county file (state FIPS 13) and is the single source of truth for county names and FIPS codes. The build refuses to proceed unless it finds exactly 159 Georgia counties. Every facility record is resolved to a county FIPS before it contributes to a county-level number. No county name is ever hand-typed.

## Source-by-source method

### Georgia EPD air permits: permitted facilities, with dates

Georgia EPD's Air Permit Search Engine publishes every air permit the state has issued. Data centers appear in it because their diesel backup generators require an air permit before the facility is built.

**Which SIC codes to search was determined empirically, not assumed.** The full state permit database (about 10,200 permits across 3,044 facilities) was pulled once and inspected to see which classifications actually carry data centers. Two are searched:

- **7374, Data Processing and Preparation.** The obvious one, and the only one originally searched. 26 facilities.
- **7376, Computer Facilities Management Services.** 8 facilities, every one a data center, including several large operators that 7374 misses entirely.

Searching 7374 alone understated the count by roughly a quarter, which is why the check was worth doing. Two further codes carry data centers mixed with unrelated industry and are surfaced for manual review rather than counted: **7389** (Services, Not Elsewhere Classified), where one of three Georgia facilities is a data center, and **4813** (Telephone Communications), which is a genuine mix of carrier central offices and colocation facilities. Whether a telecom switching center counts as a data center is a scope question rather than a data question, and it is recorded here as open.

Two encodings in the published record carry the fields the dataset needs, which is what makes this source unusually clean:

- The **AIRS number** `CCC-NNNNN` begins with the county's 3-digit FIPS code. `097-00098` is Douglas County, FIPS 13097. Prefixing `13` produces the tracker's join key directly. There is no geocoding step, so there is no geocoding error to account for.
- The **permit number** `SSSS-CCC-NNNN-T-VV-R` begins with the facility's SIC code, which confirms each record's classification independently of the search filter.

A facility accumulates several permit records over time (initial issuance, amendments, renewals). Permits are collapsed to one record per facility by AIRS number, keeping the earliest issuance date as the facility's first-permit date and the latest as its most recent activity. Counting permits rather than facilities would overstate counties whose facilities amend permits frequently.

**Current yield:** 88 permit records resolving to 34 facilities across 11 counties, with every record county-resolved and none sent to manual review. Fulton County (15) and Douglas County (7) lead.

**The first-permit dates carry the finding.** Georgia issued roughly one data center air permit a year through 2021, then 2 in 2023, 4 in 2024, 7 in 2025, and 7 in the first half of 2026 alone. Because the source is both dated and county-resolved, the dataset can show not only where data centers are but when each county entered the buildout.

**Coverage limit (stated plainly):** this source captures facilities that have reached air permitting. It misses proposals that have not yet applied, facilities whose generators fall below permitting thresholds, and any data center EPD classified under a different SIC code. Cross-checked against EPIcenter's mapped facilities (below), it is a floor rather than a census: EPIcenter maps 123 Georgia facilities against this source's 34. The gap is expected and is the reason the build does not stop at one source.

### EPA Facility Registry Service (FRS): operational and permitted facilities

FRS is a free federal registry of facilities regulated under environmental programs. Data centers appear because their diesel backup generators require air permits, which registers them with EPA under NAICS 518210 (Data Processing, Hosting, and Related Services).

EPA's single joined query hits a server-side bug, so the scraper joins three single-table lookups in Python:

1. `FRS_NAICS`, code 518210: every data-center-classified facility nationwide (returns program-system IDs).
2. `FRS_PROGRAM_FACILITY`, by program-system ID: the registry ID and state. Keep only Georgia.
3. `FRS_FACILITY_SITE`, by registry ID: county FIPS, facility name, address.

Facilities are then deduplicated by registry ID and matched to a county by FIPS, falling back to a normalized county-name match. An optimization skips the per-ID lookup for records that came from a non-Georgia state-specific program, since those cannot be in Georgia. The fetch retries on EPA's intermittent server errors and logs-and-skips any persistent failure, so a run can be reconciled afterward by re-checking the skipped IDs.

**Current yield:** 22 deduplicated operational facilities across 10 counties (Fulton leads with 10), including Google, Amazon, Vantage, and QTS.

**Coverage limit (stated plainly):** FRS only contains facilities that triggered an environmental program, so it captures permitted and operational data centers, not proposals, and not facilities that never filed. FRS is therefore a floor on operational facilities, cross-checked against other sources, not a complete census. A planned broadening of the search by facility name will recover some facilities that EPA classified under a different industry code.

### Georgia Power interconnection queue (OASIS): reassessed and not used

This source was planned as the proposal-stage signal and was dropped after examination. The public OASIS queue for Georgia Power is a *generation* interconnection queue: it lists generators seeking to connect to the grid, not large loads seeking service. Georgia's data center load pipeline runs through a separate, customer-confidential process and reaches the public record only as statewide aggregate megawatt figures in Georgia Power's IRP and Georgia PSC filings, with no facility or county detail.

A statewide megawatt total cannot be distributed across 159 counties without inventing an allocation rule, and inventing one would manufacture county-level precision the source does not contain. The Georgia EPD air permit record replaces it: EPD reaches nearly as early in the facility lifecycle, is facility-specific, and is exactly county-resolved. PSC and IRP filings are retained for statewide framing and cited as background, not joined into the dataset.

### Georgia Tech EPIcenter Ordinance Hub: local government response

EPIcenter, Georgia Tech's Energy Policy and Innovation Center, maintains the Georgia Data Center Ordinance Hub. It reviews municipal codes across more than 180 Georgia cities and counties and tracks which jurisdictions have adopted a data center ordinance or a moratorium. This is the community engagement strand's first source, and it is deliberately first: an ordinance or a moratorium is a formal, dated, countable act of community response, which news coverage and meeting minutes are not.

The Hub publishes its figures as Datawrapper charts, and Datawrapper serves each chart's underlying table at `<chart-url>/dataset.csv`, so the data is reachable without parsing the rendered page. The chart IDs are discovered from the Hub page at run time rather than hard-coded, because Datawrapper URLs carry a version number that changes each time EPIcenter republishes.

County assignment differs by jurisdiction type. County jurisdictions match directly. Municipal jurisdictions are assigned to their containing county through an explicit lookup table, so an unrecognized municipality resolves to no county and routes to manual review instead of being guessed into the wrong one. Expired moratoria are retained in the cumulative count, because an expired moratorium is still evidence that the community formally responded; a separate variable reports only those in force on the pull date.

**Current yield:** 13 counties with a data center ordinance, and 11 moratoria across 10 counties. Every moratorium resolved to a county; none required manual review. As of this pull, none of the 11 moratoria is still in force, the most recent having expired in July 2026.

**Attribution and terms.** This is Georgia Tech's compiled research product, not a primary government record, and the two other sources in this dataset are. Variables derived from it are attributed to EPIcenter, and its redistribution terms must be confirmed with Georgia Tech before they ship in a public dataset. The pipeline therefore carries a `--skip-epicenter` switch so the dataset can be built without them if terms are not granted.

### County building permits: construction _(planned, source not yet built)_

Per-county permit records identify facilities under construction. Coverage is uneven across the 159 counties: some publish searchable portals, others require open-records requests. The build prioritizes high-activity counties and documents which counties are covered by which method. The parsing approach and the open-records process are documented here as the recon pass completes.

### Remaining community engagement sources: citizen support and concerns _(planned, sources not yet built)_

Ordinances and moratoria (above) capture what local *government* did. Commission and zoning minutes, local news, and public comment records capture what residents said, and are still to be built. Where feasible these are counted and classified by direction (support versus concern). The coding scheme is documented here before it is applied, since a sentiment classification is a research judgment in a way that counting ordinances is not.

## Cross-source reconciliation

The three facility sources do not agree, and that disagreement is reported rather than smoothed over. The full county-by-county table is in [reconciliation-report.txt](reconciliation-report.txt), regenerated by `cleaning/reconcile.py`.

EPIcenter publishes its facilities as bare coordinates with a development stage, no name and no address, so its points cannot be matched to EPD records by identity. They are matched by *place*: each point is resolved to a county through the U.S. Census Bureau's geocoder, and the sources are then compared county by county. All 123 points resolved to a Georgia county with none sent to manual review.

**This is the honest limit of the method.** A county where EPD finds 1 and EPIcenter finds 4 tells you three more facilities exist there at some stage. It does not establish that EPD's one is among EPIcenter's four. Facility-level matching would require names, which EPIcenter does not publish.

**Statewide, as of this pull:** EPD air permits reach 34 facilities. EPIcenter maps 123, of which 73 are operational, 16 under construction, and 34 planned. Thirty-two counties show activity in at least one source.

The 34 planned facilities explain part of the gap, since a proposal would not hold a permit yet. The 73 operational ones do not: an operating data center with backup generators should hold an air permit. Three explanations remain open, and the reconciliation is what will distinguish them:

1. Georgia EPD classifies some data centers under a SIC code other than 7374, making the permit search too narrow.
2. EPIcenter counts individual buildings where EPD permits a whole campus, so the two count different units.
3. Some facilities fall below the generator thresholds that trigger permitting.

Resolving this is the next scheduled work, because it determines whether the two counts can be reconciled at all or are measuring different things.

**The comparison runs both directions.** Twenty-one counties have EPIcenter-mapped facilities that the permit record does not reach. Two counties, Forsyth and Jackson, have facilities holding current Georgia EPD air permits that do not appear on EPIcenter's map. The second direction is the more informative one: a permitted facility is a verified facility, so those are corrections flowing back to the Hub rather than gaps in this dataset.

## Deduplication

A single physical facility can appear in multiple sources. Records are matched and counted once. Within FRS, deduplication is by registry ID (implemented). Cross-source deduplication, for example an interconnection-queue proposal that later appears in FRS as operational, resolves to one facility record tagged by its furthest stage; this is documented here as multi-source integration is built _(planned)_.

## Indicators

Per-county counts (facilities by stage, engagement signals) are the base layer and the first deliverable. Composite indicators that normalize and combine these into comparable scores are _(planned)_: the normalization method, the weighting, and the rationale for which signals are included are documented here before any composite enters the delivered dataset.

## Zero versus missing

A true zero (a county tracked, with no activity found) is recorded distinctly from missing (not yet collected). The county reference table guarantees all 159 counties are present in every output, so a tracked-but-empty county reads as zero, not as absent. The encoding is fixed before draft delivery so users do not mistake "not collected" for "none."

## Validation

The dataset is checked against known cases before delivery, and the count of facilities is sanity-checked against DataCenterMap's public Georgia map (browsed manually, with no extraction or republishing) to confirm the pipeline is not missing major facilities. The delivery step also refuses to write any county that is not in canonical `X County, Georgia` form, so a broken join key cannot ship silently.

## Reproducibility

The full dataset is regenerated by running the pipeline (`python -m ga_data_center_tracker.pipeline`). The county reference is rebuilt from the Census source on demand. See [update_guide.md](update_guide.md) for the step-by-step refresh and [code-walkthrough.md](code-walkthrough.md) for how each module works.
