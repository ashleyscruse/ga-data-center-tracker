# Methodology

How the Georgia Data Center Tracker dataset is built. This document is delivered alongside the dataset and is written so the work can be understood, trusted, and reproduced. It is a living document; sections marked _(planned)_ firm up as each source and indicator is built. For a code-level walkthrough, see [code-walkthrough.md](code-walkthrough.md).

## Scope

The dataset describes data center activity in each of Georgia's 159 counties across four strands: proposals, construction, operations, and community engagement. The unit of analysis is the county. One row per county.

Phase 5 is built entirely from free, public, redistributable sources (see [sources.md](sources.md)). Commercial catalogs named in the original SOW (Baxtel, Data Center Hawk, DataCenterMap) are deferred to a future phase because their terms restrict republishing in a public dataset.

## County as the unit of analysis

The Solutions Tracker joins on county name in the exact form `X County, Georgia`. The county reference table (`data/reference/ga_counties.csv`) is built from the U.S. Census Bureau's authoritative national county file (state FIPS 13) and is the single source of truth for county names and FIPS codes. The build refuses to proceed unless it finds exactly 159 Georgia counties. Every facility record is resolved to a county FIPS before it contributes to a county-level number. No county name is ever hand-typed.

## Source-by-source method

### EPA Facility Registry Service (FRS): operational and permitted facilities

FRS is a free federal registry of facilities regulated under environmental programs. Data centers appear because their diesel backup generators require air permits, which registers them with EPA under NAICS 518210 (Data Processing, Hosting, and Related Services).

EPA's single joined query hits a server-side bug, so the scraper joins three single-table lookups in Python:

1. `FRS_NAICS`, code 518210: every data-center-classified facility nationwide (returns program-system IDs).
2. `FRS_PROGRAM_FACILITY`, by program-system ID: the registry ID and state. Keep only Georgia.
3. `FRS_FACILITY_SITE`, by registry ID: county FIPS, facility name, address.

Facilities are then deduplicated by registry ID and matched to a county by FIPS, falling back to a normalized county-name match. An optimization skips the per-ID lookup for records that came from a non-Georgia state-specific program, since those cannot be in Georgia. The fetch retries on EPA's intermittent server errors and logs-and-skips any persistent failure, so a run can be reconciled afterward by re-checking the skipped IDs.

**Current yield:** 22 deduplicated operational facilities across 10 counties (Fulton leads with 10), including Google, Amazon, Vantage, and QTS.

**Coverage limit (stated plainly):** FRS only contains facilities that triggered an environmental program, so it captures permitted and operational data centers, not proposals, and not facilities that never filed. FRS is therefore a floor on operational facilities, cross-checked against other sources, not a complete census. A planned broadening of the search by facility name will recover some facilities that EPA classified under a different industry code.

### Georgia Power interconnection queue (OASIS): proposals _(planned, source not yet built)_

The interconnection queue lists requests to connect large new electrical loads to the grid, often the earliest public signal of a planned data center. Queue entries are load requests by customer and location, not always labeled as data centers, so likely data centers are inferred from load size, customer name, and location. The parsing, classification, and county-match by point of interconnection are documented here as the scraper is built.

### County building permits: construction _(planned, source not yet built)_

Per-county permit records identify facilities under construction. Coverage is uneven across the 159 counties: some publish searchable portals, others require open-records requests. The build prioritizes high-activity counties and documents which counties are covered by which method. The parsing approach and the open-records process are documented here as the recon pass completes.

### Community engagement sources: citizen support and concerns _(planned, source not yet built)_

Commission and zoning minutes, local news, public comments, and data center ordinances and moratoria (including Georgia Tech's EPICenter ordinance hub) are counted and, where feasible, classified by direction (support versus concern). The coding scheme is documented here before it is applied.

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
