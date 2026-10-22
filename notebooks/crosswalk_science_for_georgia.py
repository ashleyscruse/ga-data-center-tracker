"""Crosswalk the tracker against Science for Georgia's data center map.

Science for Georgia's map is the facility list cited in Drawdown Georgia's
"Data Centers in Georgia" guide. It publishes two ArcGIS layers (completed and
planned), each with a name, owner, address, county, and coordinates, which is
what EPIcenter's development map lacks.

Three matches are made, one-to-one and nearest-first:
  * EPD permitted facilities -> S4GA by street address (house number + street).
  * EPIcenter development-map points -> S4GA by distance (<= 0.5 km match,
    0.5-2 km possible).
  * Institutional registry -> S4GA by street address where one exists.

Rerun:  python notebooks/crosswalk_science_for_georgia.py [OUT_DIR]
Writes crosswalk-science-for-georgia.xlsx to OUT_DIR (default: ../docs).
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "science_for_georgia"
BASE = "https://services2.arcgis.com/vHeD2bHG1G3sW5YZ/arcgis/rest/services"
LAYERS = {
    "completed": "Completed_Data_Centers_in_GA_GIS_Input",
    "planned": "Planned_Data_Centers_in_GA_GIS_as_of_04_Aug_2025",
}
MATCH_KM, POSSIBLE_KM = 0.5, 2.0
# S4GA county entries that are misspelled, a city, or two counties. Each is
# resolved from the facility's address; two-county sites take the first named.
COUNTY_ALIASES = {
    "marrietta": "cobb",          # 1751 Bells Ferry Rd, Marietta
    "athens-clark": "clarke",
    "spalding?": "spalding",
    "brantely": "brantley",
    "clayton & henry": "clayton",  # straddles the line; flagged in s4ga_status
    "troupe": "troup",
    "": "bulloch",                 # 4AM Development, Statesboro (only blank entry)
}
GENERIC = {"data", "center", "centers", "campus", "llc", "inc", "corporation", "corp", "facility", "services",
           "atlanta", "georgia", "college", "technology", "park", "the", "and", "phase", "project", "development", "communications"}


def tokens(*texts: str | None) -> set[str]:
    words = re.findall(r"[a-z]{4,}", " ".join(t or "" for t in texts).lower())
    return {w for w in words if w not in GENERIC}


def fetch_layer(name: str) -> list[dict]:
    url = f"{BASE}/{name}/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json&resultRecordCount=2000"
    RAW.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r:
        payload = json.load(r)
    if payload.get("exceededTransferLimit"):
        raise RuntimeError(f"{name}: more features than one page; add paging")
    (RAW / f"{name}.json").write_text(json.dumps(payload))
    return payload["features"]


def s4ga_stage(layer: str, status: str | None) -> str:
    if layer == "completed":
        return "operational"
    s = (status or "").lower()
    if "withdrawn" in s:
        return "withdrawn"
    if any(k in s for k in ("construction", "land disturbance", "roads", "power station")):
        return "construction"
    return "planned"


def addr_key(address: str | None) -> tuple[str, str] | None:
    """(house number, first street-name word), e.g. ('300', 'riverside')."""
    if not address:
        return None
    m = re.match(r"\s*(\d+)[a-z-]*\s+(?:(?:north|south|east|west|n|s|e|w)\.?\s+)?([a-z0-9]+)", address.lower())
    return (m.group(1), m.group(2)) if m else None


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def main(out_dir: Path) -> None:
    counties = {r["county_name"].replace(" County", "").lower(): r["county"]
                for r in csv.DictReader(open(ROOT / "data/reference/ga_counties.csv"))}

    def county(name: str | None) -> str:
        key = (name or "").strip().lower().replace(" county", "")
        key = COUNTY_ALIASES.get(key, key)
        return counties.get(key, f"UNRESOLVED: {name}")

    # --- Science for Georgia ---------------------------------------------------
    s4ga = []
    for layer, name in LAYERS.items():
        for f in fetch_layer(name):
            a = f["attributes"]
            g = f.get("geometry") or {}
            s4ga.append({
                "s4ga_id": f"{layer[0].upper()}{a['FID']}",
                "layer": layer,
                "name": (a.get("Name") or "").strip(),
                "owner": (a.get("Owner") or "").strip(),
                "address": (a.get("Address") or "").strip(),
                "county": county(a.get("County") or a.get("County_")),
                "s4ga_status": (a.get("Status") or "").strip(),
                "stage": s4ga_stage(layer, a.get("Status")),
                "mw": a.get("Total_Power__MegaWatts_"),
                "sqft": a.get("Total_SqFt"),
                "lat": g.get("y"), "lon": g.get("x"),
                "link": a.get("Link"),
                "date_added": a.get("Date_Added") or a.get("DateEntered"),
            })

    # --- The tracker's facility-level records -----------------------------------
    wb = openpyxl.load_workbook(ROOT / "data/processed/ga_data_centers.xlsx", read_only=True)
    rows = list(wb["Original"].iter_rows(values_only=True))
    hdr = rows[0]
    original = [dict(zip(hdr, r)) for r in rows[1:]]
    epd = [r for r in original if str(r["source"]).startswith("GA EPD")]
    inst = [r for r in original if str(r["source"]).startswith("Institutional")]

    epic = []
    cache = json.load(open(ROOT / "data/interim/point_county_cache.json"))
    fips_to_county = {r["county_fips"]: r["county"] for r in csv.DictReader(open(ROOT / "data/reference/ga_counties.csv"))}
    for i, r in enumerate(csv.DictReader(open(ROOT / "data/raw/ga_data_center_points_status.tsv"), delimiter="\t"), 1):
        fips = cache.get(f"{r['latitude']},{r['longitude']}")
        epic.append({"epic_id": f"EP{i}", "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                     "stage": r["Status"], "county": fips_to_county.get(fips, "UNRESOLVED")})

    # --- Address match: EPD + institutional -> S4GA -----------------------------
    by_addr = defaultdict(list)
    for s in s4ga:
        k = addr_key(s["address"])
        if k:
            by_addr[(k, s["county"])].append(s)
    for r in epd + inst:
        k = addr_key(r.get("address"))
        hits = by_addr.get((k, r["county"]), []) if k else []
        kind = "address"
        if not hits and k:  # same street, nearby house number (e.g. 4762 vs 4764 Bakers Ferry)
            hits = [s for s in s4ga if s["county"] == r["county"] and (sk := addr_key(s["address"]))
                    and sk[1] == k[1] and abs(int(sk[0]) - int(k[0])) <= 50]
            kind = "possible: nearby address"
        if not hits:  # same operator name in the same county
            mine = tokens(r["name"], r.get("source_id") if r in inst else None)
            hits = [s for s in s4ga if s["county"] == r["county"] and mine & tokens(s["name"], s["owner"])][:4]
            kind = "possible: operator name"
        r["match_kind"] = kind if hits else ""
        r["s4ga_match"] = "; ".join(f"{h['s4ga_id']} {h['name']} ({h['address']})" for h in hits)
        for h in hits:
            tag = "" if kind == "address" else " [possible]"
            h.setdefault("matched_epd", []).append(f"{r['source_id']} {r['name']}{tag}")

    # --- Distance match: EPIcenter points -> S4GA, nearest first, one-to-one ----
    pairs = sorted(
        (km((e["lat"], e["lon"]), (s["lat"], s["lon"])), e["epic_id"], s["s4ga_id"])
        for e in epic for s in s4ga if s["lat"] is not None and s["stage"] != "withdrawn"
    )
    e_idx = {e["epic_id"]: e for e in epic}
    s_idx = {s["s4ga_id"]: s for s in s4ga}
    for d, eid, sid in pairs:
        if d > POSSIBLE_KM:
            break
        e, s = e_idx[eid], s_idx[sid]
        if "s4ga_id" in e or "epic_id" in s:
            continue
        kind = "match" if d <= MATCH_KM else "possible"
        e.update(s4ga_id=sid, s4ga_name=s["name"], km=round(d, 2), kind=kind, s4ga_stage=s["stage"])
        s.update(epic_id=eid, epic_km=round(d, 2), epic_kind=kind, epic_stage=e["stage"])

    # --- County table ------------------------------------------------------------
    tab = defaultdict(Counter)
    for s in s4ga:
        tab[s["county"]][f"s4ga_{s['stage']}"] += 1
    for e in epic:
        tab[e["county"]][f"epic_{e['stage']}"] += 1
    for r in epd:
        tab[r["county"]]["epd_permitted"] += 1
    for r in inst:
        tab[r["county"]]["institutional"] += 1
    cols = ["s4ga_operational", "s4ga_construction", "s4ga_planned", "s4ga_withdrawn",
            "epic_operational", "epic_construction", "epic_planned", "epd_permitted", "institutional"]

    # --- Write ---------------------------------------------------------------------
    out = openpyxl.Workbook()
    bold = Font(bold=True)

    def sheet(title, header, data):
        ws = out.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font = bold
        for row in data:
            ws.append(row)
        ws.freeze_panes = "A2"

    s4_total = sum(1 for s in s4ga if s["stage"] != "withdrawn")
    epd_kind = Counter(r["match_kind"] for r in epd)
    epic_m = Counter(e.get("kind", "none") for e in epic)
    s4_only = [s for s in s4ga if s["stage"] != "withdrawn" and "epic_id" not in s and not s.get("matched_epd")]
    stage_n = Counter(s["stage"] for s in s4ga)
    summary = [
        ["Pulled", date.today().isoformat()],
        ["Science for Georgia source", "ArcGIS layers behind the map cited in Drawdown Georgia's 'Data Centers in Georgia' guide"],
        ["S4GA facilities (excl. withdrawn)", s4_total],
        ["  operational / construction / planned / withdrawn",
         f"{stage_n['operational']} / {stage_n['construction']} / {stage_n['planned']} / {stage_n['withdrawn']}"],
        ["S4GA counties (excl. withdrawn)", len({s['county'] for s in s4ga if s['stage'] != 'withdrawn'})],
        ["EPD permitted facilities (total)", len(epd)],
        ["  matched to S4GA by exact address", epd_kind["address"]],
        ["  possible match, nearby address", epd_kind["possible: nearby address"]],
        ["  possible match, operator name in same county", epd_kind["possible: operator name"]],
        ["  no S4GA candidate", epd_kind[""]],
        ["EPIcenter points matched to S4GA within 0.5 km", epic_m["match"]],
        ["EPIcenter points possibly matched (0.5-2 km)", epic_m["possible"]],
        ["EPIcenter points with no S4GA facility within 2 km", epic_m["none"]],
        ["S4GA facilities in neither EPIcenter nor EPD", len(s4_only)],
        ["Unresolved S4GA counties", sum(1 for s in s4ga if s["county"].startswith("UNRESOLVED"))],
    ]
    sheet("Summary", ["Measure", "Value"], summary)
    sheet("County crosswalk", ["county", *cols],
          [[c, *[tab[c][k] for k in cols]] for c in sorted(tab, key=lambda c: -sum(tab[c].values()))])
    sheet("S4GA facilities",
          ["s4ga_id", "layer", "stage", "s4ga_status", "name", "owner", "address", "county", "mw", "sqft",
           "lat", "lon", "epic_id", "epic_km", "epic_kind", "epic_stage", "matched_epd", "link", "date_added"],
          [[s.get(k) if k != "matched_epd" else "; ".join(s.get(k, [])) for k in
            ("s4ga_id", "layer", "stage", "s4ga_status", "name", "owner", "address", "county", "mw", "sqft",
             "lat", "lon", "epic_id", "epic_km", "epic_kind", "epic_stage", "matched_epd", "link", "date_added")]
           for s in s4ga])
    sheet("EPD + institutional", ["source", "source_id", "name", "county", "address", "stage", "match_kind", "s4ga_match"],
          [[r["source"].split(" (")[0], r["source_id"], r["name"], r["county"], r.get("address"), r["stage"],
            r["match_kind"], r["s4ga_match"]]
           for r in epd + inst])
    sheet("EPIcenter points", ["epic_id", "county", "stage", "lat", "lon", "s4ga_id", "s4ga_name", "s4ga_stage", "km", "kind"],
          [[e.get(k) for k in ("epic_id", "county", "stage", "lat", "lon", "s4ga_id", "s4ga_name", "s4ga_stage", "km", "kind")]
           for e in epic])
    del out["Sheet"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "crosswalk-science-for-georgia.xlsx"
    out.save(path)
    for k, v in summary:
        print(f"{k}: {v}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "docs")
