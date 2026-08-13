# Data Dictionary

Definitions for every field in the county-level dataset. One row per Georgia county (159 total). For how each field is produced, see [methodology.md](methodology.md); for the workbook structure, see [output_format.md](output_format.md). For what does and does not count as a data center, see the "What counts as a data center" section of the methodology.

**Status: draft v2.** Eleven variables are live. The `Status` column marks what is in the delivered workbook today versus what is planned; planned fields appear here so the target schema is visible, and activate as each source is built. The `Codebook` and `Data Description` sheets in each delivered workbook are generated from the pipeline, not hand-maintained, so they cannot drift from the shipped data.

## Identity

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `county` | string | County name in `X County, Georgia` form. The integration join key. | County reference table | live |
| `county_fips` | string | 5-digit Census FIPS code (state 13 plus 3-digit county). Carried on the `Original` sheet. | Census / county reference table | live |

## Facility indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `dc_mapped_n` | integer | Data center facilities mapped in the county at any development stage. The broadest facility count. | GT EPIcenter development map | live |
| `dc_operational_n` | integer | Mapped facilities that are operating. | GT EPIcenter development map | live |
| `dc_construction_n` | integer | Mapped facilities under construction. | GT EPIcenter development map | live |
| `dc_planned_n` | integer | Mapped facilities announced or planned, not yet under construction. | GT EPIcenter development map | live |
| `dc_permitted_n` | integer | Facilities holding a Georgia EPD air permit, cumulative across all issuance years. The most conservative count, and the only dated one. | GA EPD air permits (SIC 7374, 7376) | live |
| `dc_permitted_recent_n` | integer | Facilities whose **first** EPD air permit was issued in 2023 or later. Separates the current buildout from pre-existing stock. | GA EPD air permits | live |
| `dc_institutional_n` | integer | Institutional (university and college) data centers in the county. Counted separately; see the note below. | Curated institutional registry | live |
| `dc_frs_n` | integer | Facilities listed in the EPA Facility Registry Service under NAICS 518210. An independent federal cross-check. | EPA FRS | built, currently returning 0 |
| `proposed_load_mw` | float | Proposed new electrical load (MW). | Not available at county level; see methodology | dropped |

**These counts are not additive.** They are four different instruments pointed at the same counties, and the methodology reports their disagreement rather than smoothing it. Two rules matter when using them:

- `dc_permitted_n` is a **subset relationship, not a separate population**: a permitted facility is also, in principle, a mapped facility. Do not add it to `dc_mapped_n`.
- `dc_institutional_n` is a **union, not a sum**: campus facilities are invisible to the other sources, but whether EPIcenter's map already includes any of them has not been verified facility by facility. A county's full footprint is the union of `dc_mapped_n` and `dc_institutional_n`. Do not add them.

## Community engagement indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `dc_ordinance` | flag (0/1) | County has adopted a land-use ordinance addressing data centers. | GT EPIcenter Ordinance Hub | live |
| `dc_moratorium_n` | integer | Data center moratoria adopted in the county, including those adopted by municipalities within it, and including expired ones. | GT EPIcenter Ordinance Hub | live |
| `dc_moratorium_active_n` | integer | Moratoria in force on the date the dataset was pulled. | GT EPIcenter Ordinance Hub | live |
| `dc_local_action` | flag (0/1) | County has either an ordinance or a recorded moratorium. Unweighted logical OR, readable without consulting a formula. | Derived | live |
| `minutes_mentions_n` | integer | Commission or zoning minutes referencing data center siting or operations. | Meeting minutes | planned |
| `public_comments_n` | integer | Public comments on data center permitting or review. | Public comment records | planned |
| `news_articles_n` | integer | Local news items on data centers in the county. | News coverage | planned |
| `petitions_n` | integer | Organized petitions or advocacy actions. | Petitions, advocacy publications | planned |
| `engagement_sentiment` | categorical / float | Direction of documented community response (support versus concern). Coding scheme defined in methodology before it is applied. | Minutes, comments, news | planned |

The live engagement variables capture what local **government** did, which is formal, dated, and countable. What **residents** said is the planned half of this strand.

## Composite indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `facility_index` | float | Normalized composite of facility activity across stages. | Derived | planned |
| `engagement_index` | float | Normalized composite of community engagement signals. | Derived | planned |

Composites are deliberately last. Normalization and weighting are research judgments, and they are documented in the methodology before any composite enters the delivered dataset.

## Fields on the `Original` sheet

The `Original` sheet carries one row per facility record as pulled, stacked across sources into a shared schema. Not every column applies to every source; unused columns are blank rather than zero.

| Field | Definition |
|---|---|
| `source` | Which source produced the record. |
| `source_id` | The source's own identifier (EPD AIRS number, FRS registry ID, or institution name). |
| `name` | Facility name as the source publishes it. |
| `address`, `city`, `zip_code` | Street address. For EPD facilities these are read out of the permit PDF, not the search grid, which publishes no address. Empty for the 4 facilities whose permit is a scanned image or absent. |
| `county`, `county_fips` | Resolved county, always in tracker form. |
| `stage` | Development stage in the shared vocabulary: `permitted`, `operational`, `construction`, `planned`. |
| `first_permit_date`, `latest_permit_date`, `permit_count`, `permit_types` | EPD permit history for the facility. |
| `operating_status`, `program` | FRS status and environmental program. |
| `source_url` | Public citation: the permit PDF for EPD facilities, the announcement for curated institutional ones. Required on every curated record and enforced in code. |
| `note` | Facility-level context (size, capacity, what the facility houses). |

## Provenance

Carried in the `Data Description` sheet, not the row: source, vintage, date pulled, original variable name, and transformations applied, for every variable. Generated by the pipeline. See [output_format.md](output_format.md).

## Conventions

- **Zero versus missing:** a true zero (county tracked, no activity found) is distinct from missing (not yet collected). All 159 counties are present in every output, so a tracked-but-empty county reads as zero. On the `Transformed` sheet, a variable never computed for a county is left blank rather than zero-filled.
- **Deduplication:** within a source, a single physical facility is counted once (EPD by AIRS number, FRS by registry ID). Cross-source deduplication is not claimed; see the additivity rules above and the reconciliation section of the methodology.
- **Geocoding:** every facility record is resolved to a county FIPS before it enters a count. EPD resolves exactly from the AIRS number with no geocoding step; EPIcenter points are reverse-geocoded through the Census geocoder.
