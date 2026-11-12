"""Job sources for big tech companies that run their own careers sites instead of
Greenhouse, Lever or Ashby: Amazon, Microsoft and Netflix. Each one's robots.txt
allows the job-search address used here.

Left out on purpose: Google (its robots.txt disallows the careers results pages),
Apple (its site terms forbid automated access) and Meta (it rejects automated
requests). Their new-grad roles still arrive through the SimplifyJobs list.

Each source only fetches a full description for titles that pass the role filter,
because the new-grad and sponsorship checks need it and these sites are large.
"""

import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from common import classify_role, html_to_text
from net import RateLimited, get, job, log

MAX_PAGES = 15


def _text(*parts):
    return " ".join(html_to_text(p) for p in parts if p)


# ---------------------------------------------------------------- Amazon

AMAZON_QUERIES = [
    "software development engineer", "software engineer", "data engineer", "machine learning engineer",
    "network engineer", "forward deployed engineer", "new grad", "university graduate", "early career",
]


def _amazon_date(value):
    """'November  9, 2026' -> that day at noon UTC (the site only gives the date)."""
    try:
        day = datetime.strptime(" ".join(value.split()), "%B %d, %Y")
    except (ValueError, AttributeError):
        return None
    return min(int(day.replace(hour=12, tzinfo=timezone.utc).timestamp()), int(time.time()))


def from_amazon(since):
    seen, out = set(), []
    for q in AMAZON_QUERIES:
        for page in range(3):
            url = ("https://www.amazon.jobs/en/search.json?result_limit=100&sort=recent"
                   f"&normalized_country_code%5B%5D=USA&offset={page * 100}&base_query={urllib.parse.quote(q)}")
            jobs = (get(url) or {}).get("jobs") or []
            for x in jobs:
                posted = _amazon_date(x.get("posted_date"))
                if not posted or posted < since or x["id"] in seen:
                    continue
                seen.add(x["id"])
                out.append(job("Amazon", x["title"], "https://www.amazon.jobs" + x["job_path"],
                               [x.get("normalized_location") or x.get("location", "")], posted, "Amazon",
                               _text(x.get("description"), x.get("basic_qualifications"),
                                     x.get("preferred_qualifications")),
                               requirements=_text(x.get("basic_qualifications"))))
            oldest = _amazon_date(jobs[-1].get("posted_date")) if jobs else None
            if len(jobs) < 100 or not oldest or oldest < since:
                break
    return out


# ---------------------------------------------------------------- Microsoft

MICROSOFT_QUERIES = ["software engineer", "data engineer", "network engineer", "new grad"]
MICROSOFT = "https://apply.careers.microsoft.com"


def from_microsoft(since):
    """Microsoft throttles quick requests, so this paces itself and stops for the day
    at the first rate-limit answer, keeping whatever it already has."""
    found, out = {}, []
    try:
        for q in MICROSOFT_QUERIES:
            for page in range(5):
                time.sleep(2)
                url = (f"{MICROSOFT}/api/pcsx/search?domain=microsoft.com&location=United%20States"
                       f"&sort_by=timestamp&start={page * 10}&query={urllib.parse.quote(q)}")
                rows = ((get(url, raise_on_429=True) or {}).get("data") or {}).get("positions") or []
                fresh = [x for x in rows if x.get("postedTs", 0) >= since]
                for x in fresh:
                    if classify_role(x.get("name", "")):
                        found.setdefault(x["id"], x)
                if len(fresh) < len(rows) or not rows:
                    break
        for x in found.values():
            time.sleep(2)
            d = (get(f"{MICROSOFT}/api/pcsx/position_details?position_id={x['id']}&domain=microsoft.com&hl=en",
                     raise_on_429=True) or {}).get("data") or {}
            out.append(job("Microsoft", x["name"], f"{MICROSOFT}/careers/job/{x['id']}",
                           x.get("standardizedLocations") or x.get("locations") or [], x["postedTs"],
                           "Microsoft", _text(d.get("jobDescription"))))
    except RateLimited:
        log("  - Microsoft asked us to slow down; stopping Microsoft for today")
    return out


# ---------------------------------------------------------------- Netflix

NETFLIX = "https://explore.jobs.netflix.net/api/apply/v2/jobs"


def from_netflix(since):
    found = []
    for page in range(MAX_PAGES * 2):
        rows = (get(f"{NETFLIX}?domain=netflix.com&sort_by=new&start={page * 10}") or {}).get("positions") or []
        fresh = [x for x in rows if x.get("t_create", 0) >= since]
        found += [x for x in fresh if classify_role(x.get("name", ""))]
        if len(fresh) < len(rows) or not rows:
            break

    def detail(x):
        d = get(f"{NETFLIX}/{x['id']}?domain=netflix.com") or {}
        return job("Netflix", x["name"], x.get("canonicalPositionUrl", ""), x.get("locations") or [],
                   x["t_create"], "Netflix", _text(d.get("job_description")))

    with ThreadPoolExecutor(6) as pool:
        return list(pool.map(detail, found))


# ---------------------------------------------------------------- all

SOURCES = {"Amazon": from_amazon, "Microsoft": from_microsoft, "Netflix": from_netflix}


def from_big_tech(since):
    with ThreadPoolExecutor(len(SOURCES)) as pool:
        results = dict(zip(SOURCES, pool.map(lambda fetch: fetch(since), SOURCES.values())))
    log("Big tech: " + ", ".join(f"{name} {len(jobs)}" for name, jobs in results.items()))
    return [j for jobs in results.values() for j in jobs]
