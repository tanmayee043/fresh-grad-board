"""Job source for employers whose careers site runs on a shared hosted platform.

Each site in data/workday.json is searched through the same public job-search
address its own careers page uses, newest first, and robots.txt is checked for every
request. Only titles that pass the role filter get a second request for the full
description, which the new-grad and sponsorship checks need.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from common import classify_role, html_to_text, remember, us_locations
from net import RateLimited, get, job, log

SITES = Path(__file__).resolve().parent.parent / "data" / "workday.json"
PAGE = 20
MAX_PAGES = 25


def _days_ago(posted_on):
    """'Posted Today' -> 0, 'Posted Yesterday' -> 1, 'Posted 3 Days Ago' -> 3, '30+' -> 30."""
    text = (posted_on or "").lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    m = re.search(r"(\d+)", text)
    return int(m[1]) if m else 99


def _start_date(value):
    """'2026-11-13' -> that day at noon UTC, never in the future."""
    try:
        day = datetime.strptime(value, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return min(int(day.timestamp()), int(time.time()))


def from_site(company, site_url, since):
    m = re.match(r"https://(([^./]+)\.wd\d+\.myworkdayjobs\.com)/([^/]+)", site_url)
    host, tenant, site = m[1], m[2], m[3]
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    max_days = int((time.time() - since) // 86400) + 1
    found, out = [], []
    try:
        for page in range(MAX_PAGES):
            data = get(f"{api}/jobs", raise_on_429=True,
                       body={"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": ""}) or {}
            rows = data.get("jobPostings") or []
            fresh = [x for x in rows if _days_ago(x.get("postedOn")) <= max_days]
            found += [x for x in fresh if x.get("externalPath") and classify_role(x.get("title", ""))]
            # Lists run newest first, though some sites pin a few old jobs on top,
            # so stop at the first page with nothing recent on it.
            if not fresh or len(rows) < PAGE:
                break
            time.sleep(0.5)
        for x in found:
            time.sleep(0.5)
            info = (get(f"{api}{x['externalPath']}", raise_on_429=True) or {}).get("jobPostingInfo") or {}
            if not info:
                continue
            posted = _start_date(info.get("startDate"))
            remember(company, info.get("title") or x["title"], posted)
            if not posted or posted < since:
                continue
            locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
            country = (info.get("country") or {}).get("descriptor", "")
            if country.startswith("United States") and not us_locations(locs):
                locs = [f"{loc}, US" for loc in locs if loc]
            out.append(job(company, info.get("title") or x["title"],
                           info.get("externalUrl") or f"https://{host}/{site}{x['externalPath']}",
                           locs, posted, "Workday", html_to_text(info.get("jobDescription"))))
    except RateLimited:
        log(f"  - a careers site asked us to slow down; keeping {len(out)} postings from it")
    return out


def from_workday(since):
    sites = json.loads(SITES.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda kv: from_site(kv[0], kv[1], since), sites.items()))
    out = [j for batch in results for j in batch]
    log(f"Hosted careers sites: {len(out)} recent postings across {len(sites)} companies")
    return out
