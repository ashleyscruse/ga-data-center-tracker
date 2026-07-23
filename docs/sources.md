# Data Sources

Every source in the Phase 5 build is free, public, and redistributable. The dataset is published openly, so sources whose terms restrict republishing are excluded (see "Deferred sources" at the end).

Each source below lists its status, what it gives us, how it is accessed, the county join strategy, and the stage it captures. For the code behind the live source, see [code-walkthrough.md](code-walkthrough.md).

## Facility data

### Georgia EPD Air Protection Branch, Air Permit Search Engine
- **Status:** live. Primary facility source.
- **What:** every air permit issued in Georgia, published by the state. Data centers appear because their diesel backup generators require an air permit before the facility is built, and Georgia EPD classifies them under SIC 7374 (Data Processing and Preparation).
- **Access:** `https://permitsearch.gaepd.org/`, searched by SIC code. The site is an ASP.NET WebForms application, so the scraper holds a session and pages through the results grid via form postbacks.
- **Signal captured:** permitted facilities, reaching back to the construction-permitting stage. Each record carries an issuance date, which makes this the only current source that supports a timeline.
- **County match:** native and exact. The AIRS number `CCC-NNNNN` encodes the county's 3-digit FIPS code, so prefixing `13` yields the full county FIPS with no geocoding step and no name matching.
- **Current yield:** 88 permit records resolving to 34 facilities across 11 counties, every one county-resolved. Fulton (15) and Douglas (7) lead.
- **Which SIC codes:** 7374 (Data Processing and Preparation) and 7376 (Computer Facilities Management Services). Both are searched, because Georgia EPD files data centers under either. Two further codes, 7389 and 4813, contain some data centers mixed with unrelated industry and are surfaced for manual review rather than counted.
- **Cadence:** updated as EPD issues permits; re-pull at each refresh.

### EPA Facility Registry Service (FRS)
- **Status:** live. Retained as an independent cross-check on the EPD permit record, not as the primary count.
- **What:** federal registry of facilities regulated under environmental programs. Data centers appear because their backup-generator air permits register them under NAICS 518210.
- **Access:** EPA Envirofacts `efservice` API, queried as three single-table lookups joined in Python (`FRS_NAICS` for NAICS 518210, then `FRS_PROGRAM_FACILITY` to get registry ID and state, then `FRS_FACILITY_SITE` for county and address). The single joined query is avoided because it hits a server-side bug.
- **Signal captured:** operational and permitted facilities.
- **County match:** by the FIPS code the site record carries, validated against the county reference table; falls back to a normalized county-name match.
- **Current yield:** 22 facilities across 10 counties (Fulton 10), including Google, Amazon, Vantage, QTS.
- **Cadence:** updated continuously upstream; re-pull at each refresh.

### Georgia Power Interconnection Queue (OASIS)
- **Status:** reassessed; not a viable county-level source for this dataset. See the note below.
- **What was expected:** requests to connect large new electrical loads to the grid, as the earliest public signal that a data center is coming.
- **What the source actually is:** the public OASIS queue for Georgia Power is a *generation* interconnection queue. It lists generators seeking to connect to the grid, not large loads seeking service. Georgia's data center load pipeline is a separate, customer-confidential process; it reaches the public record only as statewide aggregate megawatt figures in Georgia Power's IRP and Georgia PSC filings, with no facility or county detail.
- **Why it is not used:** a statewide megawatt total cannot be allocated to counties without inventing an allocation rule, and inventing one would fabricate county-level precision the source does not contain.
- **What replaces it:** the Georgia EPD air permit record above, which reaches nearly as early in the facility lifecycle, is facility-specific, and is exactly county-resolved.
- **Retained as context, not as data:** Georgia PSC filings and the Georgia Power IRP remain useful for statewide framing (total contracted large load, growth trajectory) and are cited in the methodology as background rather than joined into the dataset.

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

### Data center ordinances and moratoria (Georgia Tech EPIcenter Ordinance Hub)
- **Status:** live. First source in the community engagement strand.
- **What:** which Georgia jurisdictions have adopted a data center ordinance, and which have adopted a moratorium, with start and expiration dates. EPIcenter reviews municipal codes across 180+ Georgia cities and counties.
- **Access:** `https://epicenter.energy.gatech.edu/data-center/`. The Hub's figures are Datawrapper charts, and Datawrapper serves each chart's underlying table at `<chart-url>/dataset.csv`. Chart IDs are discovered from the Hub page at run time, because the URLs carry a version number that changes on each republish.
- **Signal captured:** formal local government response to data center siting.
- **County match:** counties match directly; municipalities are assigned to their containing county through an explicit lookup table, so an unrecognized municipality routes to manual review rather than being guessed.
- **Current yield:** 13 counties with an ordinance; 11 moratoria across 10 counties, all county-resolved, none currently in force.
- **Attribution and terms:** this is Georgia Tech's compiled research product, not a primary government record. Derived variables are attributed to EPIcenter, and redistribution terms must be confirmed with Georgia Tech before they ship in the public dataset. The pipeline carries `--skip-epicenter` so the dataset can be built without them.
- **Cadence:** EPIcenter updates the Hub periodically; re-pull at each refresh.

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
