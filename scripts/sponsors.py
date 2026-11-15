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

from common import (
    _INTERN, _NON_CS, NAICS_INDUSTRY, ROLES, industry_from_name, normalize_company, sponsorship_from_text, us_locations,
)
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
    "Tesla", "Walmart Global Tech", "Visa", "Mastercard", "Expedia", "Booking", "Yahoo", "Meta Platforms",
    "Amazon Web Services", "Google", "Microsoft", "Apple", "Amazon", "Oracle", "IBM", "Salesforce", "Adobe",
    "NVIDIA", "VMware", "Uber", "LinkedIn", "Intuit", "ServiceNow", "Workday", "Dell Technologies",
}
TECH_INDUSTRIES = {
    "AI & Machine Learning", "Software & SaaS", "Consumer Tech & Marketplaces",
    "Hardware & Semiconductors", "Telecom & Networking",
}
_UNIVERSITY = re.compile(r"\b(universit(y|ies)|univ|college|institute of technology|polytechnic)\b", re.I)
# Banks and big financial houses are not tech companies; trading firms and fintechs are.
_BANK = re.compile(
    r"\b(bank\w*|bancorp|credit union|insurance|mutual|investments?|chase|citi\w*|morgan stanley|goldman|"
    r"barclays|schwab|american express|wells fargo|capital one|financial|securities|asset management)\b", re.I)
_IT_SERVICES = re.compile(
    r"\b(consult\w*|infosys|tata consultancy|cognizant|wipro|hcl|tech mahindra|ltimindtree|mindtree|capgemini|"
    r"accenture|deloitte|ernst|kpmg|pwc|pricewaterhouse\w*|mphasis|hexaware|virtusa|ust global|zensar|"
    r"persistent systems|birlasoft|ntt data|syntel|larsen|staffing|compunnel|infotech|it services|"
    r"synechron|coforge|cgi|l t technology)\b", re.I)
_TECHY = re.compile(r"\b(software|tech\w*|systems|data|digital|cloud|analytics|computer|computing|"
                    r"semiconductors?|networks?|ai|labs?|robotics|cyber\w*)\b", re.I)

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
    for name, (host, site) in json.loads((DATA / "oracle_hcm.json").read_text(encoding="utf-8")).items():
        add(name, f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}", 100)
    for x in listings:
        add(x.get("company_name"), careers_from_url(x.get("url")))
    return {key: counts.most_common(1)[0][0] for key, counts in sites.items()}


_BIG = {normalize_company(n) for n in BIG_TECH_EXTRA}


def _category(name, industry, naics=None):
    """Big Tech, Small Tech, IT Services, Universities or Other."""
    if _UNIVERSITY.search(name):
        return "Universities"
    if industry == "Big Tech" or normalize_company(name) in _BIG:
        return "Big Tech"
    if industry == "Consulting & IT Services" or _IT_SERVICES.search(name):
        return "IT Services"
    if _BANK.search(name):
        return "Other"
    if (industry in TECH_INDUSTRIES or industry == "Finance & Fintech" or naics == "51"
            or (industry in ("Other", "Automotive & Robotics") and _TECHY.search(name))):
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


# ---------------------------------------------------------------- past sponsors

PAST_MIN_APPROVALS = 50  # "heavy" sponsors: 50+ approved H-1B petitions in the year

# Words that can follow a company's name in its legal entity name without making it
# a different company: 'AMAZON COM SERVICES' is Amazon, 'APPLE HOSPITALITY' is not Apple.
ENTITY_WORDS = {
    "COM", "SERVICES", "SERVICE", "SVCS", "TECHNOLOGIES", "TECHNOLOGY", "TECH", "PLATFORMS", "USA", "US", "U", "S",
    "AMERICA", "AMERICAS", "NORTH", "INTERNATIONAL", "SYSTEMS", "SOLUTIONS", "SOFTWARE", "LABS", "LAB",
    "DEVELOPMENT", "CENTER", "DATA", "WEB", "HOLDINGS", "GROUP", "CORPORATION", "GLOBAL", "DIGITAL",
    "CONSULTING", "RESEARCH", "SEMICONDUCTOR", "SEMICONDUCTORS", "NETWORKS", "OPERATIONS", "OF", "AND",
    "ENTERPRISE", "ENTERPRISES", "COMPANY", "ASSOCIATES", "WORLDWIDE", "PAYMENTS", "FINANCIAL",
}
_SMALL = {"OF", "AND", "THE", "FOR", "IN", "AT", "ON", "DE"}
_ACRONYMS = {"US", "USA", "IBM", "CGI", "UST", "HCL", "PWC", "LLC", "NA", "IT", "AI", "MIT", "UC", "CVS", "FCA",
             "DFS", "EY", "NYU", "UCLA", "USC", "HHS", "NIH", "SAP", "AMD", "LG", "GE", "HP", "BMW", "KPMG"}
_LEGAL = re.compile(r"[\s,]+(INC|LLC|L\.L\.C|LLP|LP|L\.P|CORP|CORPORATION|CO|LTD|LIMITED|PC|PLLC|PLC)\.?$", re.I)


def _pretty(name):
    """'THE LELAND STANFORD JR UNIVERSITY' -> 'Leland Stanford Jr University'."""
    while _LEGAL.search(name):
        name = _LEGAL.sub("", name)
    name = re.sub(r"^THE\s+", "", name, flags=re.I)
    words = []
    for i, w in enumerate(name.split()):
        bare = w.strip(",.").upper()
        if bare in _ACRONYMS or "&" in w or (len(bare) <= 4 and bare.isalpha() and not re.search(r"[AEIOUY]", bare)):
            words.append(w.upper())
        elif bare in _SMALL and i:
            words.append(w.lower())
        else:
            words.append("/".join(p[:1].upper() + p[1:].lower() for p in w.split("/")))
    return " ".join(words).strip(" ,.")


def _known_names(listings):
    """Normalized company name -> the spelling the rest of the site uses."""
    names = {}
    for names_in_industry in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).values():
        for n in names_in_industry:
            names.setdefault(normalize_company(n), n)
    for n in json.loads((DATA / "careers.json").read_text(encoding="utf-8")):
        names.setdefault(normalize_company(n), n)
    for entries in json.loads((DATA / "boards.json").read_text(encoding="utf-8")).values():
        for n in entries.values():
            names.setdefault(normalize_company(n), n)
    for f in ("workday.json", "oracle_hcm.json"):
        for n in json.loads((DATA / f).read_text(encoding="utf-8")):
            names.setdefault(normalize_company(n), n)
    for x in listings:
        n = x.get("company_name") or ""
        names.setdefault(normalize_company(n), n)
    names.pop("", None)
    return names


def _match(key, known, reverse_aliases):
    if key in known:
        return key
    if reverse_aliases.get(key) in known:
        return reverse_aliases[key]
    words = key.split()
    for i in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:i])
        if prefix in known and len(prefix) >= 3 and all(w in ENTITY_WORDS for w in words[i:]):
            return prefix
    return None


def build_past_sponsors(listings, lookups, out_path):
    data = json.loads((DATA / "h1b_employers.json").read_text(encoding="utf-8"))
    names = _known_names(listings)
    careers = _known_careers(listings)
    aliases = json.loads((DATA / "aliases.json").read_text(encoding="utf-8"))
    reverse_aliases = {normalize_company(h1b): normalize_company(name) for name, h1b in aliases.items()}

    merged = {}
    for e in data["employers"]:
        match = _match(e["key"], names, reverse_aliases)
        key = match or e["key"]
        c = merged.setdefault(key, {"name": names[match] if match else _pretty(e["name"]), "key": key,
                                    "naics": e["naics"], "place": e["place"], "approvals": 0, "new_hires": 0})
        c["approvals"] += e["approvals"]
        c["new_hires"] += e["new_hires"]

    companies = []
    for c in merged.values():
        if c["approvals"] < PAST_MIN_APPROVALS:
            continue
        name, key = c["name"], c["key"]
        industry = (lookups.known_industry(name) or industry_from_name(name)
                    or NAICS_INDUSTRY.get(c["naics"] or "") or "Other")
        category = _category(name, industry, c["naics"])
        site = careers.get(key)
        domain = (lookups.domains.get(key) or company_domains.get(name)
                  or (lookups.domain(name, site) if site else None))
        companies.append({
            "id": re.sub(r"\W+", "-", name.lower()).strip("-")[:80],
            "name": name, "careers": site, "domain": domain, "industry": industry, "category": category,
            "approvals": c["approvals"], "new_hires": c["new_hires"], "place": c["place"],
        })
    companies.sort(key=lambda c: -c["approvals"])
    out_path.write_text(json.dumps({"fiscal_year": data["fiscal_year"], "min_approvals": PAST_MIN_APPROVALS,
                                    "companies": companies}, separators=(",", ":"), ensure_ascii=False),
                        encoding="utf-8")
    counts = Counter(c["category"] for c in companies)
    log(f"Past sponsors: {len(companies)} employers with {PAST_MIN_APPROVALS}+ approvals in FY{data['fiscal_year']} "
        f"({', '.join(f'{n} {k}' for k, n in counts.most_common())}); "
        f"{sum(1 for c in companies if c['careers'])} with a known careers site")
