"""Discovery pass for institutional (campus) data centers.

The institutional registry in ``institutional.py`` is hand-maintained, and the
honest limit of a hand-maintained list is that it contains what its author
happened to know. This module is how that list stops being a memory test: it
searches a public federal record for evidence of campus computing facilities in
Georgia and emits **candidates for review**, each with a citable URL.

**Why NSF award records.** There is no register of campus data centers, but there
is a register of the money that builds them. Two NSF programs buy campus computing
hardware, and both title their awards predictably:

  * **MRI** (Major Research Instrumentation), e.g. "MRI: Acquisition of an HPC
    System for Data-Driven Discovery". MRI funds instruments of every kind, so the
    computing ones have to be separated from the mass spectrometers.
  * **CC\\*** (Campus Cyberinfrastructure), e.g. "CC* Compute-Campus", "CC* Data
    Storage". This program exists specifically to build campus cyberinfrastructure,
    so nearly every hit is relevant.

Each award carries an institution, a city, a date, an amount, and a stable public
URL, which is exactly the evidence the registry's citation rule requires.

**What this module deliberately does not do: promote anything automatically.**
An award to buy a cluster is not proof of a data center. The machine may live in
another institution's building (Emory ran its cluster inside Georgia Tech's), or
in a converted room that does not meet the inclusion rule, or in the cloud. That
judgment is the reviewer's, and it is why ``discover()`` returns candidates and
``institutional.REGISTRY`` stays a hand-edited list. Collecting the evidence is
automatable; deciding what it means is not.

Run:  ``python -m ga_data_center_tracker.scrapers.institutional_discovery``
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

NSF_API = "https://api.nsf.gov/services/v1/awards.json"
NSF_AWARD_URL = "https://www.nsf.gov/awardsearch/showAward?AWD_ID={}"

PRINT_FIELDS = "id,title,awardeeName,awardeeCity,date,fundsObligatedAmt,piFirstName,piLastName"

# Search terms, chosen to reach the two hardware programs from several angles.
# NSF's keyword search is OR-ish and noisy, so recall matters more than precision
# here; precision comes from the title filters below.
KEYWORDS = [
    '"MRI: Acquisition"',
    '"MRI Acquisition"',
    '"CC* Compute"',
    '"CC* Data Storage"',
    '"Campus Cyberinfrastructure"',
    '"high performance computing"',
    "supercomputer",
    '"research computing"',
]

# A title must look like one of the hardware-buying programs.
#
# Note the absence of a trailing \b: "CC*" ends in a non-word character, so a
# word boundary after it can never match against the space that follows, and an
# earlier version of this pattern silently discarded every CC* award in Georgia.
PROGRAM_RE = re.compile(
    r"\b(MRI\s*:?\s*Acquisition|CC\*|Campus Cyberinfrastructure|Research Infrastructure)",
    re.I,
)

# ...and mention computing, so MRI's microscopes and spectrometers drop out.
COMPUTING_RE = re.compile(
    r"\b(HPC|high[- ]performance computing|computing infrastructure|compute|cluster|"
    r"cyberinfrastructure|supercomput\w*|data storage|GPU|computational (?:infrastructure|resource))\b",
    re.I,
)

# Instruments that share MRI's title pattern but are not computing facilities.
# Explicit, so a false positive is a fixable list entry rather than a silent rule.
EXCLUDE_RE = re.compile(
    r"\b(spectrometer|microscop\w*|diffractometer|telescope|mass spec|NMR|"
    r"cytometer|chromatograph|sequencer|magnetometer|C-Trap|reactor)\b",
    re.I,
)

# Awardee names in NSF's record are legal entities, not campuses. Stripped down so
# "University of Georgia Research Foundation Inc" and "University of Georgia" are
# recognized as one institution.
_ENTITY_NOISE = re.compile(
    r"\b(research (and service )?(foundation|corporation|institute|service foundation)|"
    r"foundation|corporation|inc\.?|incorporated|llc|,)\b",
    re.I,
)


@dataclass
class Candidate:
    """One institution, with the award evidence that suggests it runs a facility."""

    institution: str
    city: str
    awards: list[dict] = field(default_factory=list)

    @property
    def total_obligated(self) -> int:
        total = 0
        for a in self.awards:
            try:
                total += int(float(a.get("fundsObligatedAmt") or 0))
            except (TypeError, ValueError):
                continue
        return total

    @property
    def latest_year(self) -> str:
        years = [str(a.get("date") or "")[-4:] for a in self.awards]
        return max((y for y in years if y.isdigit()), default="")

    @property
    def strongest(self) -> dict:
        """The award a reviewer should read first.

        CC* awards outrank MRI: that program exists to build campus
        cyberinfrastructure, so its awards speak more directly to a facility than a
        general instrumentation award does. Within a tier, most recent wins.
        """
        def rank(a):
            cc = 1 if re.search(r"CC\*|Campus Cyberinfrastructure", a.get("title", ""), re.I) else 0
            return (cc, str(a.get("date") or "")[-4:])
        return max(self.awards, key=rank)


# NSF's legal-entity names and the registry's institution names do not always
# reduce to the same string ("Georgia Tech Research Corporation" against "Georgia
# Institute of Technology"). Without this, an institution already in the registry
# reads as a new candidate, which is the one error that would make the report
# actively misleading.
INSTITUTION_ALIASES = {
    "georgia tech": "Georgia Institute of Technology",
    "georgia institute of technology": "Georgia Institute of Technology",
    "university of georgia": "University of Georgia",
    "emory university": "Emory University",
    "georgia state university": "Georgia State University",
    "kennesaw state university": "Kennesaw State University",
    "morehouse college": "Morehouse College",
    "clark atlanta university": "Clark Atlanta University",
}


def normalize_institution(raw: str) -> str:
    """Reduce an NSF awardee legal name to the campus it stands for."""
    name = _ENTITY_NOISE.sub(" ", raw or "")
    name = re.sub(r"\s+", " ", name).strip(" ,.")
    if name.isupper():
        name = name.title()
    return INSTITUTION_ALIASES.get(name.lower(), name)


def _fetch(keyword: str, *, max_records: int = 200, timeout: int = 45) -> list[dict]:
    """Page through NSF's award search for one keyword, Georgia awardees only."""
    records: list[dict] = []
    offset = 1
    while len(records) < max_records:
        response = requests.get(
            NSF_API,
            params={
                "keyword": keyword,
                "awardeeStateCode": "GA",
                "printFields": PRINT_FIELDS,
                "rpp": 25,
                "offset": offset,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json().get("response", {}).get("award", [])
        records += page
        if len(page) < 25:
            break
        offset += 25
        time.sleep(0.3)
    return records


def is_computing_hardware(title: str) -> bool:
    """Whether an award title looks like it bought campus computing hardware."""
    if not title or EXCLUDE_RE.search(title):
        return False
    return bool(PROGRAM_RE.search(title) and COMPUTING_RE.search(title))


def discover(*, verbose: bool = True) -> list[Candidate]:
    """Search NSF and group matching awards by institution."""
    seen_awards: dict[str, dict] = {}
    for keyword in KEYWORDS:
        try:
            found = _fetch(keyword)
        except requests.RequestException as exc:
            if verbose:
                print(f"  {keyword}: request failed ({type(exc).__name__}), skipping")
            continue
        kept = 0
        for award in found:
            if is_computing_hardware(award.get("title", "")):
                seen_awards[award["id"]] = award
                kept += 1
        if verbose:
            print(f"  {keyword:<34} {len(found):>3} awards, {kept:>2} computing hardware")

    by_institution: dict[str, Candidate] = {}
    for award in seen_awards.values():
        name = normalize_institution(award.get("awardeeName", ""))
        if not name:
            continue
        candidate = by_institution.setdefault(
            name, Candidate(institution=name, city=award.get("awardeeCity", "") or "")
        )
        candidate.awards.append(award)

    return sorted(
        by_institution.values(), key=lambda c: (-len(c.awards), -c.total_obligated)
    )


def format_report(candidates: list[Candidate], known: set[str] | None = None) -> str:
    """Render the candidate list as a reviewable report.

    Institutions already in the registry are marked, so the report reads as a
    worklist rather than a dump.
    """
    known = known or set()
    lines = [
        "Institutional data center candidates, Georgia",
        "=" * 74,
        "",
        "Source: NSF Award Search, MRI and CC* awards to Georgia institutions whose",
        "titles indicate computing hardware. An award is evidence that an institution",
        "bought a cluster. It is NOT evidence that the institution houses it: the",
        "machine may sit in another institution's building, or in the cloud.",
        "",
        "REVIEW EACH before adding to institutional.REGISTRY. Confirm (a) a physical",
        "facility on that campus, (b) the county it sits in, (c) a public source URL.",
        "",
        f"{len(candidates)} institutions with at least one matching award.",
        "",
    ]
    for c in candidates:
        mark = "  [in registry]" if c.institution in known else ""
        lines += [
            "-" * 74,
            f"{c.institution}{mark}",
            f"  {c.city or 'city unknown'}  ·  {len(c.awards)} award(s)  ·  "
            f"${c.total_obligated:,} obligated  ·  latest {c.latest_year}",
            "",
        ]
        for a in sorted(c.awards, key=lambda x: str(x.get("date") or "")[-4:], reverse=True):
            pi = f"{a.get('piFirstName','')} {a.get('piLastName','')}".strip()
            lines.append(f"    {a.get('date','')}  {a.get('title','')}")
            lines.append(f"      {NSF_AWARD_URL.format(a['id'])}" + (f"   PI: {pi}" if pi else ""))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find candidate institutional data centers from NSF award records."
    )
    parser.add_argument(
        "--out", type=Path, default=Path("data/interim/institutional-candidates.txt")
    )
    args = parser.parse_args()

    print("Searching NSF Award Search for Georgia computing-hardware awards...")
    candidates = discover()

    from .institutional import REGISTRY
    known = {normalize_institution(f.institution) for f in REGISTRY}

    report = format_report(candidates, known=known)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"\n{len(candidates)} institutions -> {args.out}")


if __name__ == "__main__":
    main()
