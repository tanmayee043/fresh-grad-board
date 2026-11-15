"""Build data/h1b_sponsors.json and data/h1b_employers.json from the government
H-1B employer data export.

Run occasionally (the data is published once per fiscal year):
    python scripts/build_h1b.py              # downloads FY2023
    python scripts/build_h1b.py path/to.csv  # uses a local export instead
"""

import csv
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from common import normalize_company
from net import HEADERS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "h1b_sponsors.json"
# The biggest sponsors by name, for the site's past-sponsors list.
EMPLOYERS_OUT = ROOT / "data" / "h1b_employers.json"
MIN_FOR_LIST = 25
URL = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2023.csv"
MIN_APPROVALS = 3


def read_rows():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8-sig", errors="replace")
    else:
        req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig", errors="replace")
    return csv.DictReader(io.StringIO(text))


def main():
    approvals = defaultdict(int)
    new_hires = defaultdict(int)
    naics = defaultdict(lambda: defaultdict(int))
    spellings = defaultdict(lambda: defaultdict(int))
    places = defaultdict(lambda: defaultdict(int))
    year = None
    for row in read_rows():
        raw = " ".join((row.get("Employer") or "").split())
        name = normalize_company(raw)
        if not name:
            continue
        year = row.get("Fiscal Year") or year
        initial = int(row.get("Initial Approval") or 0)
        count = initial + int(row.get("Continuing Approval") or 0)
        approvals[name] += count
        new_hires[name] += initial
        spellings[name][raw] += count
        if row.get("City") and row.get("State"):
            places[name][f"{row['City'].title()}, {row['State']}"] += count
        if row.get("NAICS"):
            naics[name][row["NAICS"]] += count

    employers = {
        name: {
            "approvals": total,
            "naics": max(naics[name], key=naics[name].get) if naics[name] else None,
        }
        for name, total in approvals.items()
        if total >= MIN_APPROVALS
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps({"fiscal_year": year, "employers": employers}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {len(employers)} employers (FY{year}) to {OUT}")

    top = [
        {
            "key": name,
            "name": max(spellings[name], key=spellings[name].get),
            "approvals": approvals[name],
            "new_hires": new_hires[name],
            "naics": max(naics[name], key=naics[name].get) if naics[name] else None,
            "place": max(places[name], key=places[name].get) if places[name] else None,
        }
        for name in approvals
        if approvals[name] >= MIN_FOR_LIST
    ]
    top.sort(key=lambda e: -e["approvals"])
    EMPLOYERS_OUT.write_text(
        json.dumps({"fiscal_year": year, "employers": top}, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(top)} employers with {MIN_FOR_LIST}+ approvals to {EMPLOYERS_OUT}")


if __name__ == "__main__":
    main()
