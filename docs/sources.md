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
- **Current yield:** 107 permit records resolving to 38 facilities across 11 counties, every one county-resolved. Fulton (16) and Douglas (10) lead.
- **Which SIC codes:** 7374 (Data Processing and Preparation) and 7376 (Computer Facilities Management Services) are searched wholesale. Two further codes, 7389 and 4813, mix data centers with unrelated industry, so they are searched and then filtered to four individually adjudicated facilities: Google's Douglas County data center, AT&T Data Center, Savvis AT1, and 375 Riverside Pkwy. The remaining 4813 facilities are carrier switching centers, the open scope question.
- **Cadence:** updated as EPD issues permits; re-pull at each refresh.
- **Addresses come from the permit PDFs, not the grid.** The search results carry no address. Every permit row links to its permit document, whose first page holds a `Facility Address:` block. `scrapers/epd_permit_docs.py` downloads one PDF per facility, parses that block, and caches both the PDFs and the parsed result. **34 of 38 facilities resolved.** The 4 that did not: one permit is a scanned image with no text layer, and three facilities publish no permit PDF at all.
- **The printed county is an independent check.** The permit spells the county out in words; the dataset derives it from the AIRS number's digits. Those come from different parts of the record, and all 34 agree.

### Georgia Tech EPIcenter development map
- **Status:** live. The **primary facility-coverage source**: it reaches 123 facilities across 30 counties, against the permit record's 38 across 11.
- **What:** one row per facility, published as a latitude and longitude with a development stage (operational, construction, planned), on the Ordinance Hub's symbol map.
- **Access:** Datawrapper chart dataset, discovered at run time from the Hub page. Same fetch as the ordinance and moratoria charts below.
- **Signal captured:** facilities at every stage, including proposals that have not applied for any permit.
- **County match:** each point reverse-geocoded to a county FIPS through the U.S. Census geocoder, cached on disk. All 123 resolved; none required manual review.
- **Do not read stage counts off the regulations choropleth.** Its `Operational` / `Under construction` / `Planned` columns are 0/1 presence flags, not counts. Using them reports 27 facilities statewide instead of 123.
- **Terms:** Georgia Tech's compiled research product. Attributed by name in every derived variable; formal redistribution terms requested and not yet confirmed. `--skip-epicenter` rebuilds without it.

### Institutional (campus) data center registry
- **Status:** live, and deliberately a floor. 3 facilities across 2 counties.
- **What:** university and college data centers, which no other source in this pipeline can see. Not in the EPD permit record (campus backup generation usually falls below the threshold), not on the commercial development map, not in commercial catalogs (which track leasable colocation space).
- **Access:** curated by hand from institutional announcements and trade coverage. There is no statewide register to scrape.
- **The one hard rule:** every record carries a public `source_url`, enforced in code. The build raises on a record without one, so an unsourced facility cannot ship. The URLs travel on the `Original` sheet.
- **County match:** validated against the county reference table; an entry whose county does not resolve to a Georgia county fails the build.
- **Not additive to the mapped count.** See the additivity rules in [data_dictionary.md](data_dictionary.md).
- **Cadence:** reviewed at each refresh; new facilities added as public documentation appears.
- **Candidate discovery:** `scrapers/institutional_discovery.py` searches the NSF Award Search API for MRI and CC* awards to Georgia institutions whose titles indicate computing hardware, and writes a reviewable worklist to `data/interim/institutional-candidates.txt`. Currently 5 institutions, 2 already in the registry. Nothing is promoted automatically: an award buys a cluster, it does not prove a building.

### EPA Facility Registry Service (FRS)
- **Status:** built, **currently returning 0 records**. The scraper runs without error but the NAICS 518210 query is not yielding Georgia facilities it previously returned. Under investigation; it is a cross-check rather than a primary count, so it does not block delivery, and `--skip-frs` bypasses it.
- **What:** federal registry of facilities regulated under environmental programs. Data centers appear because their backup-generator air permits register them under NAICS 518210.
- **Access:** EPA Envirofacts `efservice` API, queried as three single-table lookups joined in Python (`FRS_NAICS` for NAICS 518210, then `FRS_PROGRAM_FACILITY` to get registry ID and state, then `FRS_FACILITY_SITE` for county and address). The single joined query is avoided because it hits a server-side bug.
- **Signal captured:** operational and permitted facilities.
- **County match:** by the FIPS code the site record carries, validated against the county reference table; falls back to a normalized county-name match.
- **Previous yield:** 22 facilities across 10 counties (Fulton 10), including Google, Amazon, Vantage, QTS. Not reproduced in the current run.
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
- **Status:** planned. **Recon complete**; the scrape itself is not built.
- **What:** where data center rezonings, special-use permits, and hearings are decided, and where residents speak on the record. The primary source for documented citizen support and concern, which is the half of the community strand the ordinance data cannot supply.
- **Scope decision:** 37 counties, not 159. The target set is the union of counties with a data center and counties with a recorded ordinance or moratorium. A county with neither has nothing for this strand to find.
- **Recon:** `scrapers/minutes_recon.py` probes each target county's website and fingerprints its agenda vendor by the domains it serves assets from. Output: `data/interim/minutes-recon.txt`.
- **Why recon first:** Georgia counties do not each roll their own agenda system, they buy one of about a dozen. Mapping county to vendor turns 37 bespoke scrapers into a handful of adapters, and tells you in advance how many counties each adapter buys.
- **Current result:** 18 of 37 counties fingerprinted, 18 sites found without a recognized vendor, 1 site unresolved. **CivicPlus (11 counties) and CivicClerk (6) are the two adapters worth writing first**, covering 14 distinct counties between them. Granicus (3), Legistar (2), IQM2 (2), and NovusAGENDA (1) follow.
- **Known limit:** the 18 unfingerprinted counties are likely PDF-only or bespoke, which is the slow tail. They are named in the recon report rather than hidden in a percentage.

### Data center ordinances and moratoria (Georgia Tech EPIcenter Ordinance Hub)

**Also delivered as its own workbook**, `data/processed/ga_data_center_ordinances.xlsx`, built by `python -m ga_data_center_tracker.ordinances`. Same five-sheet Tracker format and the same county join key, so it loads exactly like the facility dataset. Its `Original` sheet carries one row per ordinance or moratorium (jurisdiction, type, dates, status) rather than one row per facility, and it adds two variables the facility workbook does not: `dc_moratorium_expired_n` and `dc_moratorium_city_n`. The four shared variables are identical in both files.
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
