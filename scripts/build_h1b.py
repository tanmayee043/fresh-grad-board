"""Build data/h1b_sponsors.json from the USCIS H-1B Employer Data Hub export.

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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "h1b_sponsors.json"
URL = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-2023.csv"
MIN_APPROVALS = 3


def read_rows():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8-sig", errors="replace")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig", errors="replace")
    return csv.DictReader(io.StringIO(text))


def main():
    approvals = defaultdict(int)
    naics = defaultdict(lambda: defaultdict(int))
    year = None
    for row in read_rows():
        name = normalize_company(row.get("Employer") or "")
        if not name:
            continue
        year = row.get("Fiscal Year") or year
        count = int(row.get("Initial Approval") or 0) + int(row.get("Continuing Approval") or 0)
        approvals[name] += count
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


if __name__ == "__main__":
    main()
