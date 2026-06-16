# Data Dictionary

Definitions for every field in the county-level dataset. One row per Georgia county (159 total). For how each field is produced, see [methodology.md](methodology.md); for the workbook structure, see [output_format.md](output_format.md).

**Status: draft v1.** The `Status` column marks what is in the delivered workbook today versus what is planned. Today only `dc_operational_n` is populated (from EPA FRS); planned fields appear here so the target schema is visible, and activate as each source is built. The `Codebook` sheet in each delivered workbook is generated from this dictionary.

## Identity

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `county` | string | County name in `X County, Georgia` form. The integration join key. | County reference table | live |
| `county_fips` | string | 5-digit Census FIPS code (state 13 plus 3-digit county). | Census / county reference table | live |

## Facility indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `dc_operational_n` | integer | Count of operational and permitted data centers (NAICS 518210) in the county. | EPA FRS | live |
| `dc_proposed_n` | integer | Count of distinct data centers at proposal or planning stage. | OASIS interconnection queue, news | planned |
| `dc_construction_n` | integer | Count of distinct data centers in active construction. | County permits | planned |
| `dc_total_n` | integer | Distinct data centers across all stages (deduplicated). | Combined | planned |
| `proposed_load_mw` | float | Total proposed new electrical load (MW) from interconnection requests. | OASIS, if MW is exposed | planned |

## Community engagement indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `minutes_mentions_n` | integer | Count of commission or zoning minutes referencing data center siting or operations. | Meeting minutes | planned |
| `ordinance_flag` | integer | Whether the county has a data center ordinance or moratorium (1/0). | EPICenter ordinance hub, county records | planned |
| `public_comments_n` | integer | Count of public comments on data center permitting or review. | Public comment records | planned |
| `news_articles_n` | integer | Count of local news items on data centers in the county. | News coverage | planned |
| `petitions_n` | integer | Count of organized petitions or advocacy actions. | Petitions, advocacy publications | planned |
| `engagement_sentiment` | categorical / float | Direction of documented community response (support versus concern). Coding scheme defined in methodology. | Minutes, comments, news | planned |

## Composite indicators

| Field | Type | Definition | Source | Status |
|---|---|---|---|---|
| `facility_index` | float | Normalized composite of facility activity across stages. Construction defined in methodology. | Derived | planned |
| `engagement_index` | float | Normalized composite of community engagement signals. Construction defined in methodology. | Derived | planned |

## Provenance (carried in the Data Description sheet, not the row)

For every variable: source, vintage, date pulled, original variable name, transformations applied. See [output_format.md](output_format.md).

## Conventions

- **Zero versus missing:** a true zero (county tracked, no activity found) is distinct from missing (not yet collected). All 159 counties are present in every output, so a tracked-but-empty county reads as zero. The encoding is fixed in the methodology before draft delivery.
- **Deduplication:** a single physical facility appearing in multiple sources is counted once. Dedup logic is documented in [methodology.md](methodology.md).
- **Geocoding:** every facility record is resolved to a county FIPS before it enters a count. See methodology.
