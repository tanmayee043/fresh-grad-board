"""A second curated new-grad list, published daily as Markdown tables on GitHub.

Only the GitHub lists are read. The source's own job pages sit behind a bot check,
so there is no description to check experience against; instead only rows whose
title clearly says entry level are kept ("New Grad", "Early Career", "Junior",
"Associate", "Engineer I" ...). The "Apply" link opens the job on the source's site.
"""

import re
import urllib.parse
from datetime import datetime, timezone

from common import new_grad_title, remember
from net import get, job, log

# The lists are renamed for each graduating class; update the year when they roll over.
LISTS = ["2026-Software-Engineer-New-Grad", "2026-Engineering-New-Grad", "2026-Data-Analysis-New-Grad"]
RAW = "https://raw.githubusercontent.com/jobright-ai/{repo}/{branch}/README.md"
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _row_date(text):
    """'Nov 12' -> that day this year (last year if that would be in the future)."""
    now = datetime.now(timezone.utc)
    try:
        day = datetime.strptime(f"{text.strip()} {now.year}", "%b %d %Y").replace(hour=12, tzinfo=timezone.utc)
    except ValueError:
        return None
    if day.timestamp() > now.timestamp() + 86400:
        day = day.replace(year=now.year - 1)
    return min(int(day.timestamp()), int(now.timestamp()))


def _rows(repo):
    readme = get(RAW.format(repo=repo, branch="master"), as_json=False) or \
        get(RAW.format(repo=repo, branch="main"), as_json=False) or ""
    company = domain = None
    for line in readme.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not LINK.search(cells[1]):
            continue
        if cells[0] != "↳":
            m = LINK.search(cells[0])
            company = m.group(1) if m else cells[0].strip("* ")
            domain = (urllib.parse.urlsplit(m.group(2)).hostname or "").removeprefix("www.") if m else None
        title, url = LINK.search(cells[1]).groups()
        yield company, domain, title, url.split("?")[0], cells[2], cells[3], cells[4]


def from_jobright(since):
    out, seen = [], set()
    for repo in LISTS:
        for company, domain, title, url, location, work_model, date in _rows(repo):
            posted = _row_date(date)
            remember(company, title, posted)
            if not posted or posted < since or url in seen or not new_grad_title(title):
                continue
            seen.add(url)
            locs = [location] + (["Remote in USA"] if "remote" in work_model.lower() else [])
            out.append(job(company, title, url, locs, posted, "Jobright", domain=domain))
    log(f"Second curated list: {len(out)} recent entry-level listings")
    return out
