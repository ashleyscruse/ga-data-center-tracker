# Methodology

How the Georgia Data Center Tracker dataset is built. This document is delivered alongside the dataset and is written so the work can be understood, trusted, and reproduced. It is a living document; sections marked _(planned)_ firm up as each source and indicator is built. For a code-level walkthrough, see [code-walkthrough.md](code-walkthrough.md).

## Scope

The dataset describes data center activity in each of Georgia's 159 counties across four strands: proposals, construction, operations, and community engagement. The unit of analysis is the county. One row per county.

Phase 5 is built entirely from free, public, redistributable sources (see [sources.md](sources.md)). Commercial catalogs named in the original SOW (Baxtel, Data Center Hawk, DataCenterMap) are deferred to a future phase because their terms restrict republishing in a public dataset.

## County as the unit of analysis

The Solutions Tracker joins on county name in the exact form `X County, Georgia`. The county reference table (`data/reference/ga_counties.csv`) is built from the U.S. Census Bureau's authoritative national county file (state FIPS 13) and is the single source of truth for county names and FIPS codes. The build refuses to proceed unless it finds exactly 159 Georgia counties. Every facility record is resolved to a county FIPS before it contributes to a county-level number. No county name is ever hand-typed.

## What counts as a data center

Every count in this dataset depends on this definition, so it is stated before the sources rather than left implicit in them.

**Included.** A purpose-built facility whose primary function is housing computing and storage infrastructure at scale. This covers commercial colocation and hyperscale facilities, enterprise-owned facilities, and **institutionally operated facilities**, meaning university and college data centers housing research computing.

**Excluded.** Server closets, wiring rooms, and departmental racks inside a building built for something else. Cloud-hosted computing with no Georgia physical footprint is also excluded, since the dataset measures facilities sited in Georgia counties, not computing consumed by Georgia institutions. A cluster that a Georgia university runs inside another institution's data center is counted once, at the county where the building actually sits.

**Why institutional facilities are included.** They are frequently large, and they are hard to see in the other sources. Georgia Tech's Coda data center is a 9.6 megawatt facility in Midtown Atlanta, one of the largest in the Southeast, and it appears on no commercial development map; it holds a state air permit only under an operating-company name that never mentions Georgia Tech. Counting a small commercial colocation building while omitting Coda would misstate the county's actual data center footprint, which is the thing this dataset exists to measure. The University of Georgia's Boyd facility is the cleaner case: Clarke County registers zero data centers in every other source in this project, and it houses the university's central research computing facility.

**Two open boundary cases** are recorded rather than silently resolved. Telephone central offices classified under SIC 4813 are a genuine mix of carrier switching and colocation, and are surfaced for manual review rather than counted. Cryptocurrency mining facilities meet the physical definition but serve a different end use; none is currently in the record, and the question is flagged for the final delivery.

## Source-by-source method

### Georgia EPD air permits: permitted facilities, with dates

Georgia EPD's Air Permit Search Engine publishes every air permit the state has issued. Data centers appear in it because their diesel backup generators require an air permit before the facility is built.

**Which SIC codes to search was determined empirically, not assumed.** The full state permit database (about 10,200 permits across 3,044 facilities) was pulled once and inspected to see which classifications actually carry data centers. Two are searched:

- **7374, Data Processing and Preparation.** The obvious one, and the only one originally searched. 26 facilities.
- **7376, Computer Facilities Management Services.** 8 facilities, every one a data center, including several large operators that 7374 misses entirely.

Searching 7374 alone understated the count by roughly a quarter, which is why the check was worth doing.

**Two further codes carry data centers mixed with unrelated industry, so they are filtered facility by facility rather than swept in.** Promoting a whole code would import the sterilization plant and the airport that share it; ignoring the code entirely loses real data centers. Neither is acceptable, so individual facilities are adjudicated by AIRS number, each with a recorded reason, in `ADJUDICATED_INCLUSIONS` and `ADJUDICATED_EXCLUSIONS`.

- **7389, Services Not Elsewhere Classified.** A catch-all holding 3 Georgia facilities. One is **Google's Douglas County data center**. The other two are manufacturing and medical sterilization, and are recorded as excluded.
- **4813, Telephone Communications.** 9 facilities, a genuine mix. Three are adjudicated in: **AT&T Data Center** (named as such in the state's own record), **Savvis AT1** (a colocation operator's Atlanta facility), and **375 Riverside Pkwy** (a 250,000 square foot, 27.5 MW colocation building in Lithia Springs). Hartsfield-Jackson airport is excluded as a misfiling.

**Missing Google was a miss, not a scope decision**, and it is the same class of error as the SIC 7374 gap: a data center that exists, holds a current state permit, and was invisible because of how the state filed it. It was found the same way, by inspecting the full permit database rather than trusting a classification.

**The four remaining 4813 facilities are carrier switching centers** (Bellsouth Midtown Two, AT&T Georgia, Sprint Atlanta Switch, and two AT&T Mobility sites). They sit on neither list. Whether a telecom switch counts as a data center is a scope question rather than a data question, and it is recorded here as open pending Georgia Tech's call.

Two encodings in the published record carry the fields the dataset needs, which is what makes this source unusually clean:

- The **AIRS number** `CCC-NNNNN` begins with the county's 3-digit FIPS code. `097-00098` is Douglas County, FIPS 13097. Prefixing `13` produces the tracker's join key directly. There is no geocoding step, so there is no geocoding error to account for.
- The **permit number** `SSSS-CCC-NNNN-T-VV-R` begins with the facility's SIC code, which confirms each record's classification independently of the search filter.

A facility accumulates several permit records over time (initial issuance, amendments, renewals). Permits are collapsed to one record per facility by AIRS number, keeping the earliest issuance date as the facility's first-permit date and the latest as its most recent activity. Counting permits rather than facilities would overstate counties whose facilities amend permits frequently.

**Current yield:** 107 permit records resolving to 38 facilities across 11 counties, with every record county-resolved and none sent to manual review. Fulton County (16) and Douglas County (10) lead.

**The first-permit dates carry the finding.** Georgia issued roughly one data center air permit a year through 2021, then 2 in 2023, 4 in 2024, 7 in 2025, and 7 in the first half of 2026 alone. Because the source is both dated and county-resolved, the dataset can show not only where data centers are but when each county entered the buildout.

**Coverage limit (stated plainly):** this source captures facilities that have reached air permitting. It misses proposals that have not yet applied, facilities whose generators fall below permitting thresholds, and any data center EPD classified under a different SIC code. Cross-checked against EPIcenter's mapped facilities (below), it is a floor rather than a census: EPIcenter maps 123 Georgia facilities against this source's 38. The gap is expected and is the reason the build does not stop at one source.

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

The Hub also publishes a **development map**: one row per facility, as a latitude and longitude with a development stage. This is the dataset's primary facility-coverage source, and it supplies `dc_mapped_n`, `dc_operational_n`, `dc_construction_n`, and `dc_planned_n`.

**One trap in this source is worth recording, because it is easy to fall into and it undercounts by a factor of four.** The Hub's regulations choropleth also carries columns named `Operational`, `Under construction`, and `Planned`. Those are 0/1 presence flags indicating whether a county has any facility at that stage, not counts. Reading them as counts yields 27 facilities statewide instead of 123, and reports Douglas County as having 1 facility when the development map places 16 there. The counts in this dataset come from the per-facility development map, and the county totals are verified against the reconciliation report on every build.

**Current yield:** 123 mapped facilities across 30 counties (73 operational, 16 under construction, 34 planned). Separately, 13 counties with a data center ordinance, and 11 moratoria across 10 counties. Every moratorium resolved to a county; none required manual review. As of this pull, none of the 11 moratoria is still in force, the most recent having expired in July 2026.

**Attribution and terms.** This is Georgia Tech's compiled research product, not a primary government record, and the two other sources in this dataset are. Every variable derived from it is attributed to EPIcenter by name in the Data Description sheet, and the derivation is documented above so a reader can see exactly what was taken and how it was transformed. Formal redistribution terms have been requested from Georgia Tech and are not yet confirmed; the draft delivery flags this explicitly for the Solutions Tracker team, who are the same institution that publishes the Hub. The pipeline carries a `--skip-epicenter` switch so the dataset can be rebuilt without these variables if terms are declined.

### Institutional data centers: university and college facilities

Campus data centers are largely invisible to the other sources here. Most do not appear in the EPD air permit record, because a campus facility's backup generation usually falls below the threshold that catches a commercial hyperscale campus. They do not appear on EPIcenter's development map, which tracks the commercial buildout. They are not in commercial catalogs, which track leasable colocation space rather than owner-occupied research infrastructure. Under the definition above they are data centers, so they are counted, and this is the source that counts them.

**One of the three is not invisible, and finding that out corrected a double count.** Georgia Tech's Coda facility does hold a state air permit, filed as "Data Center Atlanta, LLC" under AIRS 121-00941. Nothing in that name indicates Georgia Tech, which is why the two records were never connected: they were matched only once the facility's street address was read out of the permit PDF and matched 756 West Peachtree Street NW, the Coda building. Coda was therefore being counted twice in the statewide total, once as a permitted facility and once as an institutional one.

The registry now records the overlap on the facility itself (`epd_airs_number`), and the statewide union subtracts it. `dc_institutional_n` still counts Coda, because "how many institutional data centers does Fulton County have" is a real question with the answer 2. The union does not add it a second time.

The general lesson is worth stating: **a facility can be present in a source and still be undiscoverable in it**, because operators permit under holding-company names. Address matching finds those; name matching does not.

**This source is curated, not scraped, and that is a deliberate trade.** There is no statewide register of campus data centers to scrape; each facility is documented in institutional announcements and trade coverage instead. The registry is therefore assembled by hand under one rule enforced in code: **every record must carry a public source URL**, and the build raises an error on a record without one, so an unsourced facility cannot reach the published dataset even by accident. Those URLs ship on the `Original` sheet, one per facility, so any reader can check the entry themselves. Each record's county and development stage are validated against the same reference table and stage vocabulary the other sources use.

**Current yield:** 3 facilities across 2 counties, of which 2 are new to the dataset (Coda is also in the permit record).

| Facility | Institution | County | Stage |
|---|---|---|---|
| Coda Data Center | Georgia Institute of Technology | Fulton | Operational |
| Horizon supercomputer site | Morehouse College | Fulton | Planned |
| Boyd Data Center | University of Georgia | Clarke | Operational |

Clarke County is the clearest illustration of why this source exists: it registers zero data centers in every other source in this dataset, and it houses the University of Georgia's central research computing facility.

### The statewide total is a range, not a number

Reporting a single "how many data centers does Georgia have" figure requires knowing which facilities appear in more than one source, and that cannot be established: EPIcenter publishes bare coordinates with no names, so nothing can be matched across sources by identity.

The dataset therefore reports the **conservative** union, `max(dc_mapped_n, dc_permitted_n) + dc_institutional_n` per county, which assumes every permitted facility is also mapped. That assumption is chosen because it can only undercount, never double-count.

| Assumption | Statewide total |
|---|---|
| Every permitted facility is also on EPIcenter's map (the published rule) | **127** |
| No overlap between the two sources | 163 |

**So the defensible statement is "at least 127 facilities," not "127 facilities."** The 36-facility spread is the cost of not being able to match by identity, and closing it is what the coordinate-matching work scheduled before final delivery is for. Any headline figure drawn from this dataset should carry the "at least."

**Why the institutional count is not added to `dc_mapped_n`.** Whether EPIcenter's development map already includes any of these three facilities has not been verified facility by facility, and EPIcenter publishes bare coordinates with no names, so it cannot be verified by identity. Summing the two would risk double-counting Fulton County. `dc_institutional_n` is therefore published as its own variable, and **a county's full footprint is the union of `dc_mapped_n` and `dc_institutional_n`, not their sum.** Resolving the overlap by coordinate is scheduled before final delivery.

#### Finding candidates systematically, rather than from memory

A hand-maintained list contains what its author happened to know, which is not a defensible sampling frame. `scrapers/institutional_discovery.py` replaces recall with a search of a public federal record.

**The insight is that there is no register of campus data centers, but there is a register of the money that builds them.** Two NSF programs buy campus computing hardware, and both title their awards predictably: **MRI** (Major Research Instrumentation), which funds instruments of every kind and so needs its computing awards separated from its mass spectrometers, and **CC\*** (Campus Cyberinfrastructure), which exists specifically to build campus cyberinfrastructure and is therefore the higher-signal program. Every award carries an institution, a city, a date, an amount, and a stable public URL, which is exactly the evidence the citation rule demands.

The discovery pass currently surfaces **five Georgia institutions**, two of which are already in the registry. Its output is `docs/institutional-candidates.txt`.

**It emits candidates, and nothing is promoted automatically.** An award to buy a cluster is not evidence of a data center. The machine may sit in another institution's building, in a converted room that does not meet the inclusion rule, or in the cloud. Emory is the cautionary case: its HPC cluster ran inside Georgia Tech's Rich Computer Center and its current platform is cloud-hosted, so an institution can have substantial research computing and no Georgia facility at all. Collecting the evidence is automatable; deciding what it means is not.

**Review outcome for the three new candidates, all held out:**

| Institution | Evidence | Decision |
|---|---|---|
| Georgia State University | CC\* Compute-Campus (2024) and MRI computing infrastructure (2019), $1.5M | **Held.** Substantial research computing (ARCTIC), but no public source names a physical facility or its location. |
| Kennesaw State University | CC\* Data Storage (2022), $500K, ~70 servers and a 6.5 PB store | **Held.** Published pages describe hardware and capacity, never a building. |
| Augusta State University | Two MRI awards (2007, 2009), $177K, undergraduate research | **Held.** Small, decades old, and predates the institution's 2013 merger. Likely a departmental cluster rather than a facility. |

Holding all three is the correct outcome, not a failed run: each is now a named institution with a specific unanswered question, rather than an unknown unknown. Confirming them requires a source that names the building, which is a records question rather than a search question.

**Coverage limit (stated plainly):** this is a floor, and a low one. It contains the institutional facilities that are publicly documented well enough to cite, not every institutional facility in Georgia. Facilities known to exist but lacking a public, citable source are deliberately absent rather than entered on private knowledge. The discovery pass above bounds how much is missing at the state's research-active institutions; it says nothing about teaching institutions that never sought NSF instrumentation funding. Corporate enterprise data centers, invisible for the same structural reasons, are a further known gap and are not yet addressed.

### County building permits: construction _(planned, source not yet built)_

Per-county permit records identify facilities under construction. Coverage is uneven across the 159 counties: some publish searchable portals, others require open-records requests. The build prioritizes high-activity counties and documents which counties are covered by which method. The parsing approach and the open-records process are documented here as the recon pass completes.

### Remaining community engagement sources: citizen support and concerns _(planned, sources not yet built)_

Ordinances and moratoria (above) capture what local *government* did. Commission and zoning minutes, local news, and public comment records capture what residents said, and are still to be built. Where feasible these are counted and classified by direction (support versus concern). The coding scheme is documented here before it is applied, since a sentiment classification is a research judgment in a way that counting ordinances is not.

## Cross-source reconciliation

The three facility sources do not agree, and that disagreement is reported rather than smoothed over. The full county-by-county table is in [reconciliation-report.txt](reconciliation-report.txt), regenerated by `cleaning/reconcile.py`.

EPIcenter publishes its facilities as bare coordinates with a development stage, no name and no address, so its points cannot be matched to EPD records by identity. They are matched by *place*: each point is resolved to a county through the U.S. Census Bureau's geocoder, and the sources are then compared county by county. All 123 points resolved to a Georgia county with none sent to manual review.

**This is the honest limit of the method.** A county where EPD finds 1 and EPIcenter finds 4 tells you three more facilities exist there at some stage. It does not establish that EPD's one is among EPIcenter's four. Facility-level matching would require names, which EPIcenter does not publish.

**Statewide, as of this pull:** EPD air permits reach 34 facilities. EPIcenter maps 123, of which 73 are operational, 16 under construction, and 34 planned. Thirty-three counties show activity in at least one source, and the union across all sources is 127 facilities: EPIcenter's 123, the 2 institutional facilities not already in the permit record, and the 2 permitted facilities in Forsyth and Jackson that EPIcenter's map does not show.

The 34 planned facilities explain part of the gap, since a proposal would not hold a permit yet. The 73 operational ones do not: an operating data center with backup generators should hold an air permit. Three explanations remain open, and the reconciliation is what will distinguish them:

1. Georgia EPD classifies some data centers under a SIC code other than 7374, making the permit search too narrow.
2. EPIcenter counts individual buildings where EPD permits a whole campus, so the two count different units.
3. Some facilities fall below the generator thresholds that trigger permitting.

Resolving this is the next scheduled work, because it determines whether the two counts can be reconciled at all or are measuring different things.

**The comparison runs both directions.** Twenty-one counties have EPIcenter-mapped facilities that the permit record does not reach. Two counties, Forsyth and Jackson, have facilities holding current Georgia EPD air permits that do not appear on EPIcenter's map. The second direction is the more informative one: a permitted facility is a verified facility, so those are corrections flowing back to the Hub rather than gaps in this dataset.

## Deduplication

A single physical facility can appear in multiple sources. Records are matched and counted once. Within FRS, deduplication is by registry ID (implemented). Cross-source deduplication, for example an interconnection-queue proposal that later appears in FRS as operational, resolves to one facility record tagged by its furthest stage; this is documented here as multi-source integration is built _(planned)_.

## Indicators: selection, normalization, and composite weighting

Per-county counts are the base layer and the first deliverable. This section documents how they combine into comparable scores. It is written before any composite ships, so the reasoning can be reviewed rather than reverse-engineered from a number.

### Indicator selection

Two things are being measured, and they are not the same thing: **how much data center activity a county has**, and **how its local institutions have responded**. Collapsing both into one score would hide which of the two is driving it, so the design keeps two sub-indices.

| Sub-index | Inputs | Rationale |
|---|---|---|
| **Facility intensity** | `dc_operational_n`, `dc_construction_n`, `dc_planned_n`, `dc_institutional_n` | The physical footprint. Stage-weighted, because an operating facility and an announcement are not equivalent. |
| **Community response** | `dc_ordinance`, `dc_moratorium_n`, plus the resident-sentiment variables when built | Formal local action. Currently government response only; resident sentiment is the missing half. |

`dc_permitted_n` and `dc_permitted_recent_n` are deliberately **excluded from the composite** and retained as standalone variables. They measure the same facilities as `dc_operational_n` through a different instrument, so including both would double-weight permitted facilities. They stay in the dataset because they are the only dated measure, which makes them the right variable for a time-trend question and the wrong one for a cross-sectional index.

### Normalization

**The distribution is the problem to solve.** Facility counts across Georgia's 159 counties are extremely right-skewed: Fulton has 45, Douglas 16, and 128 counties have zero. Plain min-max rescaling on that distribution puts every non-Fulton county within a few points of zero, producing an index that says nothing except "Fulton."

Three options were considered:

| Method | Why not / why |
|---|---|
| Min-max on raw counts | Rejected. Fulton's 45 compresses everything else into the bottom of the range. |
| Z-score | Rejected. Assumes a roughly symmetric distribution; on this one it produces a standard deviation driven almost entirely by two counties. |
| **log1p, then min-max to 0-100** | **Adopted.** `log(1 + count)` compresses the long tail so the difference between 0, 1, and 3 facilities stays visible, which is the range most Georgia counties actually occupy, while Fulton still scores highest. |

Zero stays zero under `log1p`, so a county with no activity scores 0 rather than an arbitrary floor. Flag variables (`dc_ordinance`) are already 0/1 and are not transformed.

**Per-capita normalization is not applied**, and that is a deliberate scope choice. A per-capita figure answers "how exposed is the average resident," which is a burden question. This measure answers "how much data center development is sited here," which is a land-use and energy-demand question, and the Solutions Tracker joins it against other county measures that are themselves absolute. County population is a natural next variable for a user who wants the burden framing, and it is not this dataset's to impose.

### Composite weighting

**Within the facility sub-index, facilities are weighted by development stage:**

| Stage | Weight | Rationale |
|---|---|---|
| Operational | 1.00 | The facility exists and is drawing power. |
| Under construction | 0.66 | Committed and physically underway; will operate absent an unusual reversal. |
| Planned | 0.33 | Announced or proposed. A meaningful signal of where pressure is arriving, but the most likely to change. |

The weights are deliberately simple and evenly spaced rather than estimated. There is no Georgia dataset of announced-facility completion rates to estimate them from, so an estimated-looking weight would imply precision that does not exist. Even spacing is defensible, legible without a formula, and easy for a user to override.

**Institutional facilities enter at weight 1.00 when operational**, on the same stage scale, since a campus data center is a physical facility like any other.

**Across the two sub-indices, weights are equal**, and the two are reported separately as well as combined. Equal weighting is the honest default when there is no principled basis for preferring one dimension over the other, and reporting them separately means a user who disagrees can recombine them.

### What ships when

The base variables are the August 15 draft. The composites enter the final dataset once the resident-sentiment variables exist, because a community-response index built only on ordinances would measure local government and be named for residents. Publishing that composite early would be the single most misleading thing this dataset could do.

**Open decisions for Georgia Tech**, flagged rather than resolved unilaterally: whether the Tracker prefers absolute or per-capita normalization for cross-measure comparability, and whether the stage weights above should match any convention already used in other Tracker measures.

## Zero versus missing

A true zero (a county tracked, with no activity found) is recorded distinctly from missing (not yet collected). The county reference table guarantees all 159 counties are present in every output, so a tracked-but-empty county reads as zero, not as absent. The encoding is fixed before draft delivery so users do not mistake "not collected" for "none."

## Validation

The dataset is checked against known cases before delivery, and the count of facilities is sanity-checked against DataCenterMap's public Georgia map (browsed manually, with no extraction or republishing) to confirm the pipeline is not missing major facilities. The delivery step also refuses to write any county that is not in canonical `X County, Georgia` form, so a broken join key cannot ship silently.

## Reproducibility

The full dataset is regenerated by running the pipeline (`python -m ga_data_center_tracker.pipeline`). The county reference is rebuilt from the Census source on demand. See [update_guide.md](update_guide.md) for the step-by-step refresh and [code-walkthrough.md](code-walkthrough.md) for how each module works.
