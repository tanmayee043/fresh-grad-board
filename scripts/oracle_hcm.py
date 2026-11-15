"""Job source for employers whose careers site runs on a hosted recruiting cloud.

Each site in data/oracle_hcm.json is read through the public job-search service its
own careers page uses, newest first. Only titles that pass the role filter get a
second request for the full description, which the new-grad and sponsorship checks
need. These hosts publish no robots.txt rules; every request still checks.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import classify_role, html_to_text, remember
from net import RateLimited, get, iso_to_epoch, job, log

SITES = Path(__file__).resolve().parent.parent / "data" / "oracle_hcm.json"
PAGE = 25
MAX_PAGES = 20
API = "/hcmRestApi/resources/latest"


def _day(value):
    """'2026-11-14' -> that day at noon UTC, never in the future."""
    epoch = iso_to_epoch(f"{value}T12:00:00+00:00") if value else None
    return min(epoch, int(time.time())) if epoch else None


def from_site(company, host, site, since):
    base = f"https://{host}{API}"
    found, out = [], []
    try:
        for page in range(MAX_PAGES):
            url = (f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                   f"&finder=findReqs;siteNumber={site},limit={PAGE},offset={page * PAGE},sortBy=POSTING_DATES_DESC")
            items = (get(url, raise_on_429=True) or {}).get("items") or [{}]
            rows = items[0].get("requisitionList") or []
            fresh = [x for x in rows if (_day(x.get("PostedDate")) or 0) >= since - 86400]
            found += [x for x in fresh if classify_role(x.get("Title", ""))]
            if not fresh or len(rows) < PAGE:
                break
            time.sleep(0.5)
        for x in found:
            time.sleep(0.5)
            url = (f"{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                   f"&finder=ById;Id=%22{x['Id']}%22,siteNumber={site}")
            items = (get(url, raise_on_429=True) or {}).get("items") or []
            info = items[0] if items else {}
            posted = iso_to_epoch(info.get("ExternalPostedStartDate")) or _day(x.get("PostedDate"))
            remember(company, x["Title"], posted)
            if not posted or posted < since:
                continue
            locs = [x.get("PrimaryLocation", "")] + [s.get("Name", "") for s in x.get("secondaryLocations") or []]
            if x.get("PrimaryLocationCountry") == "US":
                locs = [loc if "United States" in loc or loc.endswith(", US") else f"{loc}, US" for loc in locs if loc]
            text = " ".join(html_to_text(info.get(k)) for k in (
                "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr") if info.get(k))
            out.append(job(company, x["Title"], f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{x['Id']}",
                           locs, posted, "Oracle", text or html_to_text(x.get("ShortDescriptionStr"))))
    except RateLimited:
        log(f"  - a careers site asked us to slow down; keeping {len(out)} postings from it")
    return out


def from_oracle_hcm(since):
    sites = json.loads(SITES.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda kv: from_site(kv[0], kv[1][0], kv[1][1], since), sites.items()))
    out = [j for batch in results for j in batch]
    log(f"Recruiting-cloud careers sites: {len(out)} recent postings across {len(sites)} companies")
    return out
