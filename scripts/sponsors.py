"""Build site/data/sponsors.json: companies whose own job postings from this year say
they sponsor work visas, sorted into Big Tech, Small Tech, Universities and Other.

Evidence comes from posting text only: every posting from this calendar year on the
company boards read each day, plus each day's board jobs. The list carries over from
the previous run (the local file, or the published copy in CI) and grows daily; it
starts fresh each January.
"""

import json
import os
import re
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from common import _INTERN, _NON_CS, ROLES, industry_from_name, normalize_company, sponsorship_from_text, us_locations
from jobright import company_domains
from net import get, log

DATA = Path(__file__).resolve().parent.parent / "data"
YEAR = datetime.now(timezone.utc).year
YEAR_START = int(datetime(YEAR, 1, 1, tzinfo=timezone.utc).timestamp())
MAX_POSTINGS = 20  # kept per company, newest first

BIG_TECH_EXTRA = {
    "Cisco", "Intel", "Qualcomm", "Broadcom", "AMD", "Advanced Micro Devices", "Micron", "Texas Instruments",
    "Snowflake", "Databricks", "Airbnb", "DoorDash", "Lyft", "PayPal", "Atlassian", "Spotify", "Pinterest",
    "Snap", "Block", "Shopify", "Palo Alto Networks", "Cloudflare", "Samsung", "Stripe", "Bloomberg",
    "Coinbase", "Robinhood", "Reddit", "Instacart", "eBay", "Twilio", "Zoom", "Dropbox", "OpenAI", "Anthropic",
    "Tesla", "Walmart Global Tech", "Capital One", "Visa", "Mastercard", "Expedia", "Booking", "Yahoo",
}
TECH_INDUSTRIES = {
    "Big Tech", "AI & Machine Learning", "Software & SaaS", "Consumer Tech & Marketplaces",
    "Hardware & Semiconductors", "Telecom & Networking", "Automotive & Robotics", "Consulting & IT Services",
    "Finance & Fintech", "Gaming, Media & Entertainment",
}
_UNIVERSITY = re.compile(r"\b(universit(y|ies)|college|institute of technology|polytechnic)\b", re.I)
_FINTECH_NOT_BANK = re.compile(r"\b(bank|bancorp|credit union|insurance|mutual)\b", re.I)

_found = {}
_lock = threading.Lock()


def _cs_title(title):
    """A computer-science role at any level: sponsorship policy is company-wide."""
    return (not _INTERN.search(title) and not _NON_CS.search(title)
            and any(rx.search(title) for _, rx in ROLES))


def note_sponsor(company, title, url, posted, evidence):
    if not (company and url and posted) or posted < YEAR_START:
        return
    with _lock:
        _found.setdefault(url, {"company": company, "title": title, "url": url,
                                "posted": int(posted), "evidence": evidence})


def note_posting(company, title, url, posted, text, locations):
    """Called for every posting a source reads; keeps the US CS ones that say they sponsor."""
    if not posted or posted < YEAR_START or not text or not _cs_title(title or ""):
        return
    if locations and not us_locations(locations):
        return
    status, evidence = sponsorship_from_text(text)
    if status == "yes":
        note_sponsor(company, title, url, posted, evidence)


def careers_from_url(url):
    """The careers-site home behind one job link, or None for job aggregators."""
    parts = urllib.parse.urlsplit(url or "")
    host, segs = (parts.hostname or "").lower(), [s for s in parts.path.split("/") if s]
    if not host:
        return None
    if "myworkdayjobs.com" in host:
        segs = [s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
        return f"https://{host}/{segs[0]}" if segs else None
    for ats in ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "workable.com"):
        if host.endswith(ats):
            if host.startswith("boards-api.") or host.startswith("api."):
                return None
            token = segs[1] if segs and segs[0] == "embed" and len(segs) > 1 else (segs[0] if segs else None)
            return f"https://{host}/{token}" if token else None
    if "oraclecloud.com" in host:
        m = re.search(r"(/hcmUI/CandidateExperience/[a-z]{2}/sites/[^/]+)", parts.path)
        return f"https://{host}{m[1]}" if m else None
    if any(bad in host for bad in ("jobright", "simplify", "linkedin", "indeed", "glassdoor", "ziprecruiter")):
        return None
    return f"https://{host}"


def _known_careers(listings):
    """Normalized company name -> its most likely careers-site home."""
    sites = defaultdict(Counter)

    def add(name, url, weight=1):
        key = normalize_company(name or "")
        if key and url:
            sites[key][url] += weight

    for name, url in json.loads((DATA / "careers.json").read_text(encoding="utf-8")).items():
        add(name, url, 1000)
    boards = json.loads((DATA / "boards.json").read_text(encoding="utf-8"))
    hosts = {"greenhouse": "https://job-boards.greenhouse.io/", "lever": "https://jobs.lever.co/",
             "ashby": "https://jobs.ashbyhq.com/"}
    for ats, entries in boards.items():
        for token, name in entries.items():
            add(name, hosts[ats] + token, 100)
    for name, url in json.loads((DATA / "workday.json").read_text(encoding="utf-8")).items():
        add(name, url, 100)
    for x in listings:
        add(x.get("company_name"), careers_from_url(x.get("url")))
    return {key: counts.most_common(1)[0][0] for key, counts in sites.items()}


def _category(name, industry):
    if _UNIVERSITY.search(name):
        return "Universities"
    if industry == "Big Tech" or name in BIG_TECH_EXTRA:
        return "Big Tech"
    if industry in TECH_INDUSTRIES and not (industry == "Finance & Fintech" and _FINTECH_NOT_BANK.search(name)):
        return "Small Tech"
    return "Other"


def _previous(out_path):
    """Last run's list: the local file, else the published copy (CI starts empty)."""
    if out_path.exists():
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    base = os.environ.get("PAGES_URL", "")
    if base:
        return get(base.rstrip("/") + "/data/sponsors.json?t=" + str(int(time.time()))) or {}
    return {}


def build_sponsors(listings, lookups, out_path):
    postings = dict(_found)
    prev = _previous(out_path)
    if prev.get("year") == YEAR:
        for c in prev.get("companies", []):
            for p in c.get("postings", []):
                # Re-check with today's rules so a fixed false match doesn't linger.
                if sponsorship_from_text(p.get("evidence"))[0] != "yes":
                    continue
                postings.setdefault(p["url"], {**p, "company": p.get("company") or c["name"]})

    by_company = defaultdict(list)
    for p in postings.values():
        if p["posted"] >= YEAR_START:
            by_company[normalize_company(p["company"])].append(p)

    careers = _known_careers(listings)
    companies = []
    for key, items in by_company.items():
        items.sort(key=lambda p: -p["posted"])
        name = Counter(p["company"] for p in items).most_common(1)[0][0]
        site = careers.get(key) or next(filter(None, (careers_from_url(p["url"]) for p in items)), None)
        domain = (lookups.domains.get(key) or company_domains.get(name)
                  or (lookups.domain(name, site) if site else None))
        industry = lookups.known_industry(name) or industry_from_name(name) or "Other"
        companies.append({
            "id": re.sub(r"\W+", "-", name.lower()).strip("-")[:80],
            "name": name, "careers": site, "domain": domain, "industry": industry,
            "category": _category(name, industry), "count": len(items),
            "last_posted": items[0]["posted"],
            "postings": [{k: p[k] for k in ("title", "url", "posted", "evidence")} for p in items[:MAX_POSTINGS]],
        })
    companies.sort(key=lambda c: (-c["count"], c["name"].lower()))
    out_path.write_text(json.dumps({"year": YEAR, "generated_at": int(time.time()), "companies": companies},
                                   separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    counts = Counter(c["category"] for c in companies)
    log(f"Sponsor list: {len(companies)} companies whose {YEAR} postings say they sponsor "
        f"({', '.join(f'{n} {k}' for k, n in counts.most_common())}); {len(_found)} postings found today")
