# Data Sources

Every source in the Phase 5 build is free, public, and redistributable. The dataset is published openly, so sources whose terms restrict republishing are excluded (see "Deferred sources" at the end).

Each source below lists its status, what it gives us, how it is accessed, the county join strategy, and the stage it captures. For the code behind the live source, see [code-walkthrough.md](code-walkthrough.md).

## Facility data

### EPA Facility Registry Service (FRS)
- **Status:** live.
- **What:** federal registry of facilities regulated under environmental programs. Data centers appear because their backup-generator air permits register them under NAICS 518210.
- **Access:** EPA Envirofacts `efservice` API, queried as three single-table lookups joined in Python (`FRS_NAICS` for NAICS 518210, then `FRS_PROGRAM_FACILITY` to get registry ID and state, then `FRS_FACILITY_SITE` for county and address). The single joined query is avoided because it hits a server-side bug.
- **Signal captured:** operational and permitted facilities.
- **County match:** by the FIPS code the site record carries, validated against the county reference table; falls back to a normalized county-name match.
- **Current yield:** 22 facilities across 10 counties (Fulton 10), including Google, Amazon, Vantage, QTS.
- **Cadence:** updated continuously upstream; re-pull at each refresh.

### Georgia Power Interconnection Queue (OASIS)
- **Status:** planned.
- **What:** requests to connect large new electrical loads to the grid. Often the earliest public signal that a data center is coming, before permits or construction.
- **Access:** Georgia Power / Southern Company OASIS portal. Public queue export.
- **Signal captured:** proposal and planning stage.
- **County match:** by stated point of interconnection or substation location, geocoded to county FIPS.
- **Note:** queue entries are load requests by customer and location, not always labeled as data centers; likely data centers are inferred from load size, customer, and location.
- **Cadence:** queue updated periodically; re-pull at each dataset refresh.

## Construction and permitting

### County building permit databases
- **Status:** planned.
- **What:** permits for data center construction (new commercial and industrial builds).
- **Access:** per-county. Many counties publish searchable permit portals; others require open-records (Georgia Open Records Act) requests with a templated letter.
- **Signal captured:** construction stage.
- **County match:** native (each source is a single county).
- **Cadence:** varies by county; the recon pass (below) determines which are online versus request-only.

## Community engagement and public sentiment

### County commission and zoning board meeting minutes
- **Status:** planned.
- **What:** where data center rezonings, special-use permits, and hearings are decided. Primary source for documented community support and concern.
- **Access:** county websites and agenda portals (Granicus, CivicClerk, PDF archives); scrape or download.
- **Signal captured:** community engagement; siting decisions.

### Data center ordinances and moratoria
- **Status:** planned.
- **What:** local ordinances and moratoria governing data center siting. A structured, countable signal of local government and community response.
- **Access:** Georgia Tech's EPICenter Data Center Ordinance Hub and county records.
- **Signal captured:** community and government response, by jurisdiction.

### Local newspaper coverage
- **Status:** planned.
- **What:** reporting on proposed and active data centers and community reaction.
- **Access:** free journalism indexes and news search; archive scraping where terms permit.
- **Signal captured:** community engagement; timeline of events.

### Public comment records (environmental review and permitting)
- **Status:** planned.
- **What:** citizen comments submitted during permitting and environmental review.
- **Access:** agency comment dockets; open-records where not posted.
- **Signal captured:** community concern, quantified.

### Online petitions and community advocacy publications
- **Status:** planned.
- **What:** organized community response (petitions, advocacy posts).
- **Access:** public web.
- **Signal captured:** community concern, organized.

## County recon (prerequisite, all 159 counties)

Before the permit and minutes scrapers are written, inventory each of Georgia's 159 counties:
- Does it publish building permits online (scrapable) or is it open-records only?
- Where does it post commission and zoning minutes, and in what format?

This recon determines build order and which counties need a templated open-records request.

## Deferred sources (named in SOW, not in Phase 5)

Commercial catalogs (Baxtel, Data Center Hawk, DataCenterMap) are industry deal-flow tools. Their terms likely restrict republishing in a public dataset, so they are excluded from the published build and held for a possible future phase pending research licensing. DataCenterMap's public map may be browsed manually as an informal coverage check only, with no extraction or republishing.
