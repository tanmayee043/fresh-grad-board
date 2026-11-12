"""HTTP helpers and the job record shared by every source.

Every request identifies itself honestly, checks the site's robots.txt first, and
gives up on a rate-limit answer instead of retrying.
"""

import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BOT = "fresh-grad-board"
HEADERS = {
    "User-Agent": f"{BOT}/1.0 (personal new-grad job digest; +https://github.com/tanmayee043/fresh-grad-board)",
}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- robots.txt

_robots = {}
_robots_lock = threading.Lock()


def _parse_robots(text):
    """Allow/Disallow rules for our bot, or for '*' when no group names it."""
    groups, agents, rules, in_rules = {}, [], [], False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if in_rules:
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
            for agent in agents:
                groups.setdefault(agent, rules)
        elif field in ("allow", "disallow"):
            in_rules = True
            if value:
                rules.append((field == "allow", value))
    return groups.get(BOT) or groups.get("*") or []


def _rule_matches(pattern, path):
    regex = re.escape(pattern).replace(r"\*", ".*")
    if regex.endswith(r"\$"):
        regex = regex[:-2] + "$"
    return re.match(regex, path) is not None


def allowed(url):
    """robots.txt check with the standard reading: the longest matching rule wins,
    and Allow wins a tie. (Python's urllib.robotparser takes the first match, which
    wrongly blocks sites that list 'Disallow: /' before their 'Allow' lines.)"""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        if origin not in _robots:
            try:
                req = urllib.request.Request(origin + "/robots.txt", headers=HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    _robots[origin] = _parse_robots(resp.read().decode("utf-8", errors="replace"))
            except Exception:
                _robots[origin] = []  # no readable robots.txt means no restrictions
        rules = _robots[origin]
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    best = None
    for allow, pattern in rules:
        if _rule_matches(pattern, path):
            key = (len(pattern), allow)
            if best is None or key > best:
                best = key
    return best is None or best[1]


# ---------------------------------------------------------------- requests

class RateLimited(Exception):
    """The site asked us to slow down (HTTP 429); callers should stop, not retry."""


def get(url, as_json=True, timeout=25, raise_on_429=False):
    """GET and decode; None on any failure or when robots.txt disallows the URL."""
    if not allowed(url):
        log(f"  - skipped by robots.txt: {url[:90]}")
        return None
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return json.loads(text) if as_json else text
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and raise_on_429:
            raise RateLimited(url) from exc
        log(f"  ! {url[:90]}: HTTP {exc.code}")
        return None
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


def job(company, title, url, locations, posted_at, source, text=None, requirements=None):
    """`requirements` is the minimum-qualifications text when a source gives it apart."""
    return {
        "company": company.strip(), "title": " ".join(title.split()), "url": url,
        "locations": locations, "posted_at": posted_at, "source": source, "text": text,
        "requirements": requirements,
    }
