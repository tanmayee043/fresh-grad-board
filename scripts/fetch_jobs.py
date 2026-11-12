"""Collect US new-grad CS jobs posted in the last 3 days into site/data/jobs.json.

    python scripts/fetch_jobs.py [--hours 72]
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from common import (
    INDUSTRIES, NAICS_INDUSTRY, PINNED_ROLES, ROLE_ORDER, classify_role, html_to_text, industry_from_name, industry_from_text,
    looks_new_grad, normalize_company, split_locations, sponsorship_from_text, us_locations,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data" / "jobs.json"
SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (fresh-grad-board job digest)"}
# Applicant-tracking hosts: a link on one of these says nothing about the company's own site.
ATS_HOSTS = (
    "myworkdayjobs", "greenhouse", "lever.co", "ashbyhq", "workable", "oraclecloud", "applytojob",
    "jobvite", "icims", "smartrecruiters", "taleo", "successfactors", "ultipro", "paylocity", "adp.com",
    "bamboohr", "recruitee", "breezy", "dayforce", "rippling", "simplify", "linkedin", "indeed",
    "eightfold", "phenompeople", "avature", "jazzhr", "pinpointhq", "teamtailor", "gem.com",
    "careers-page", "jibeapply", "hirebridge", "applicantpro", "paycom", "paycor", "workforcenow", "brassring",
)
GENERIC_TAILS = {
    "TECHNOLOGIES", "TECHNOLOGY", "HOLDINGS", "GROUP", "SYSTEMS", "SOLUTIONS", "SOFTWARE",
    "INTERNATIONAL", "GLOBAL", "LABS", "AI", "BANK", "FINANCIAL", "HEALTH", "INDUSTRIES",
}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def get(url, as_json=True, timeout=25):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if as_json else body
    except Exception as exc:  # one bad source must not sink the run
        log(f"  ! {url[:90]}: {exc.__class__.__name__}: {exc}")
        return None


def iso_to_epoch(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def job(company, title, url, locations, posted_at, source, text=None):
    return {
        "company": company.strip(), "title": " ".join(title.split()), "url": url,
        "locations": locations, "posted_at": posted_at, "source": source, "text": text,
    }


# ---------------------------------------------------------------- sources

def from_simplify(since):
    listings = get(SIMPLIFY_URL, timeout=90) or []
    out = []
    for x in listings:
        if not (x.get("active") and x.get("is_visible")) or x.get("date_posted", 0) < since:
            continue
        out.append(job(x["company_name"], x["title"], x["url"], x.get("locations") or [],
                       x["date_posted"], "SimplifyJobs"))
    log(f"SimplifyJobs: {len(out)} recent listings")
    return out


def from_greenhouse(token, company, since):
    data = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true") or {}
    out = []
    for x in data.get("jobs", []):
        posted = iso_to_epoch(x.get("first_published") or x.get("updated_at"))
        if not posted or posted < since:
            continue
        locs = split_locations((x.get("location") or {}).get("name", ""))
        out.append(job(company, x["title"], x["absolute_url"], locs,
                       posted, "Greenhouse", html_to_text(x.get("content"))))
    return out


def from_lever(token, company, since):
    data = get(f"https://api.lever.co/v0/postings/{token}?mode=json") or []
    out = []
    for x in data:
        posted = (x.get("createdAt") or 0) // 1000
        if posted < since:
            continue
        cats = x.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location", "")]
        if x.get("country") == "US" and not us_locations(locs):
            locs = [f"{loc}, US" for loc in locs]
        lists = " ".join(f"{l.get('text', '')} {html_to_text(l.get('content'))}" for l in x.get("lists", []))
        text = " ".join([x.get("descriptionPlain", ""), lists, x.get("additionalPlain", "")])
        out.append(job(company, x["text"], x["hostedUrl"], locs, posted, "Lever", text))
    return out


def from_ashby(token, company, since):
    data = get(f"https://api.ashbyhq.com/posting-api/job-board/{token}") or {}
    out = []
    for x in data.get("jobs", []):
        posted = iso_to_epoch(x.get("publishedAt"))
        if not x.get("isListed", True) or not posted or posted < since:
            continue
        locs = [x.get("location", "")] + [s.get("location", "") for s in x.get("secondaryLocations") or []]
        country = ((x.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        if country in ("United States", "USA", "US") and not us_locations(locs):
            locs = [f"{loc}, US" for loc in locs]
        out.append(job(company, x["title"], x["jobUrl"], locs, posted, "Ashby",
                       x.get("descriptionPlain") or html_to_text(x.get("descriptionHtml"))))
    return out


def from_boards(since):
    boards = json.loads((DATA / "boards.json").read_text(encoding="utf-8"))
    fetchers = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby}
    tasks = [(fetchers[ats], token, name) for ats, entries in boards.items() for token, name in entries.items()]
    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda t: t[0](t[1], t[2], since), tasks))
    out = [j for batch in results for j in batch]
    log(f"Company boards: {len(out)} recent postings across {len(tasks)} companies")
    return out


# ---------------------------------------------------------------- descriptions

_ashby_cache = {}


def fetch_description(url):
    """Pull the posting text for a SimplifyJobs link so sponsorship can be checked."""
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", clean)
    if m:
        x = get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}")
        return html_to_text(x.get("content")) if x else None
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", clean)
    if m:
        x = get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}")
        if not x:
            return None
        lists = " ".join(html_to_text(l.get("content")) for l in x.get("lists", []))
        return " ".join([x.get("descriptionPlain", ""), lists, x.get("additionalPlain", "")])
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", clean)
    if m:
        if m[1] not in _ashby_cache:
            _ashby_cache[m[1]] = get(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}") or {}
        for x in _ashby_cache[m[1]].get("jobs", []):
            if x.get("id") == m[2]:
                return x.get("descriptionPlain")
        return None
    m = re.match(r"https://(([^./]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/(job/.+)", clean)
    if m:
        x = get(f"https://{m[1]}/wday/cxs/{m[2]}/{m[3]}/{m[4]}")
        return html_to_text(((x or {}).get("jobPostingInfo") or {}).get("jobDescription")) or None
    page = get(url, as_json=False)
    if not page:
        return None
    # Many applicant-tracking pages embed the posting as JSON-LD even when the
    # visible page is rendered by JavaScript.
    for block in re.findall(r'(?is)<script[^>]+ld\+json[^>]*>(.*?)</script>', page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("description"):
                return html_to_text(item["description"])
    # Fall back to the visible text, cut before any application form: its
    # questions ("Do you require sponsorship?") are not the employer's policy.
    text = re.split(r"(?i)attach resume|apply for this job|first name\s*\*|submit application", html_to_text(page))[0]
    return text if len(text) > 800 else None


# ---------------------------------------------------------------- enrichment

class Lookups:
    def __init__(self):
        companies = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
        self.industry = {normalize_company(c): ind for ind, names in companies.items() for c in names}
        domains = json.loads((DATA / "domains.json").read_text(encoding="utf-8"))
        self.domains = {normalize_company(k): v for k, v in domains.items()}
        aliases = json.loads((DATA / "aliases.json").read_text(encoding="utf-8"))
        self.aliases = {normalize_company(k): normalize_company(v) for k, v in aliases.items()}
        h1b = json.loads((DATA / "h1b_sponsors.json").read_text(encoding="utf-8"))
        self.h1b_year = h1b["fiscal_year"]
        self.h1b = h1b["employers"]
        self.h1b_by_first = {}
        for name in self.h1b:
            self.h1b_by_first.setdefault(name.split()[0], []).append(name)

    def domain(self, company, url):
        """Company website for its logo: the domain map first, else the careers link
        when it is on the company's own site rather than a job-board host."""
        n = normalize_company(company)
        if n in self.domains:
            return self.domains[n]
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if not host or any(ats in host for ats in ATS_HOSTS):
            return None
        return ".".join(host.split(".")[-2:])

    def known_industry(self, company):
        n = normalize_company(company)
        if n in self.industry:
            return self.industry[n]
        words = n.split()
        for i in range(len(words) - 1, 0, -1):
            prefix = " ".join(words[:i])
            if len(prefix) >= 5 and prefix in self.industry:
                return self.industry[prefix]
        return None

    def h1b_record(self, company):
        """(approvals, NAICS) for the employer, summing subsidiaries like 'GOOGLE LLC'."""
        n = normalize_company(company)
        n = self.aliases.get(n, n)
        words = n.split()
        # 'Dell Technologies' files as 'DELL USA' / 'DELL PRODUCTS': drop generic tails.
        while len(words) > 1 and words[-1] in GENERIC_TAILS:
            words.pop()
        for candidate in dict.fromkeys([n, " ".join(words)]):
            approvals, naics = self._h1b_lookup(candidate)
            if approvals:
                return approvals, naics
        return 0, None

    def _h1b_lookup(self, n):
        if not n:
            return 0, None
        matches = [self.h1b[n]] if n in self.h1b else []
        if len(n) >= 4:
            matches += [self.h1b[name] for name in self.h1b_by_first.get(n.split()[0], [])
                        if name.startswith(n + " ")]
        if not matches:
            return 0, None
        top = max(matches, key=lambda r: r["approvals"])
        return sum(r["approvals"] for r in matches), top["naics"]


def enrich(j, lookups):
    approvals, naics = lookups.h1b_record(j["company"])
    j["industry"] = (lookups.known_industry(j["company"]) or industry_from_name(j["company"])
                     or NAICS_INDUSTRY.get(naics or "") or industry_from_text(j["text"]) or "Other")
    status, evidence = sponsorship_from_text(j["text"])
    if status:
        j["sponsorship"], j["basis"], j["evidence"] = status, "posting", evidence
    elif j["industry"] == "Defense & Aerospace":
        j["sponsorship"], j["basis"] = "no", "defense"
    elif approvals:
        j["sponsorship"], j["basis"] = "yes", "h1b"
    else:
        j["sponsorship"], j["basis"] = "no", "unknown"
    j["h1b_approvals"] = approvals
    j["has_description"] = bool(j["text"])
    j["domain"] = lookups.domain(j["company"], j["url"])


# ---------------------------------------------------------------- main

def dedupe(jobs):
    seen = {}
    for j in jobs:
        key = (normalize_company(j["company"]), re.sub(r"\W+", "", j["title"].lower()))
        if key in seen:
            kept = seen[key]
            kept["locations"] = list(dict.fromkeys(kept["locations"] + j["locations"]))
            kept["text"] = kept["text"] or j["text"]
            kept["posted_at"] = max(kept["posted_at"], j["posted_at"])
        else:
            seen[key] = j
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=72)
    args = parser.parse_args()

    now = int(time.time())
    since = now - args.hours * 3600
    lookups = Lookups()

    raw = from_simplify(since) + from_boards(since)
    jobs = []
    for j in raw:
        j["locations"] = us_locations(j["locations"])
        j["role"] = classify_role(j["title"])
        if not j["locations"] or not j["role"]:
            continue
        if j["source"] != "SimplifyJobs" and not looks_new_grad(j["title"], j["text"]):
            continue
        jobs.append(j)
    jobs = dedupe(jobs)
    log(f"Kept {len(jobs)} US new-grad CS jobs; fetching missing descriptions…")

    missing = [j for j in jobs if not j["text"]]
    with ThreadPoolExecutor(12) as pool:
        for j, text in zip(missing, pool.map(lambda j: fetch_description(j["url"]), missing)):
            j["text"] = text
    log(f"Descriptions found for {sum(1 for j in missing if j['text'])}/{len(missing)} SimplifyJobs links")

    for j in jobs:
        enrich(j, lookups)
        j["remote"] = any("remote" in loc.lower() for loc in j["locations"])
        j["id"] = re.sub(r"\W+", "-", f"{j['company']}-{j['title']}".lower()).strip("-")[:120]
        del j["text"]
    jobs.sort(key=lambda j: j["posted_at"], reverse=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": now,
        "window_hours": args.hours,
        "h1b_fiscal_year": lookups.h1b_year,
        "industries": INDUSTRIES + ["Other"],
        "roles": ROLE_ORDER,
        "pinned_roles": PINNED_ROLES,
        "jobs": jobs,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    yes = sum(j["sponsorship"] == "yes" for j in jobs)
    log(f"Wrote {len(jobs)} jobs ({yes} sponsor visas) to {OUT}")


if __name__ == "__main__":
    main()
