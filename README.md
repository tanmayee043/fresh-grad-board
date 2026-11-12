# Fresh Grad Board

A daily list of US new-grad computer science jobs posted in the last 3 days, split into jobs that sponsor visas and jobs that don't, and grouped by industry. You can filter by sponsorship, job type (Software Engineer, Data Engineer, Forward Deployed Engineer, Networking and more), industry, posting date and remote.

## How it works

`scripts/fetch_jobs.py` runs every morning in GitHub Actions and writes `site/data/jobs.json`, which the static site in `site/` renders.

1. **Collect.** It reads the [SimplifyJobs New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) list, the public Greenhouse, Lever and Ashby job boards of the companies in `data/boards.json` (including most large quant firms), and the careers sites of Amazon, Microsoft and Netflix (`scripts/big_tech.py`). Google, Apple and Meta are left out on purpose (see below); their new-grad roles still come through the SimplifyJobs list.
2. **Filter.** It keeps US locations and CS roles (software, data, AI/ML, security, infrastructure, embedded, quant, associate PM). It drops internships and senior titles. For company boards, it also keeps only roles that look new-grad: the title says so, or the posting asks for at most 1 year of experience.
3. **Sponsorship.** It reads each posting for wording like "unable to sponsor", "U.S. citizenship required" or "security clearance", and for wording that offers sponsorship. When the posting says nothing, it checks whether the employer had H-1B petitions approved, using USCIS data in `data/h1b_sponsors.json`. Defense employers that say nothing are treated as non-sponsoring.
4. **Industry.** It uses the company map in `data/companies.json` first. If the company isn't listed, it tries hints in the company name, then the employer's NAICS code from the H-1B data, then keywords in the description.
5. **Logos.** Company websites come from `data/domains.json`, or from the careers link when it's on the company's own site. The page loads each logo from Google's favicon service, falls back to DuckDuckGo's, and shows a letter badge if neither has one.

## Fetching politely

- Requests identify themselves as `fresh-grad-board/1.0` with a link to this repo, not as a browser.
- Every URL is checked against the site's robots.txt first, and disallowed URLs are skipped.
- A rate-limit answer (HTTP 429) is never retried: that source stops for the day.
- The job feeds used are either public APIs built for this (Greenhouse, Lever, Ashby), public data (SimplifyJobs, USCIS), or job-search endpoints the site's robots.txt allows (Amazon, Microsoft, Netflix).
- Not fetched: Google (robots.txt disallows its careers results pages), Apple (its site terms forbid automated access) and Meta (rejects automated requests).

## Run locally

Needs Python 3.10 or newer; there are no dependencies.

```bash
python scripts/fetch_jobs.py
python -m http.server 8000 -d site
```

Then open http://localhost:8000.

## Maintain

- **Add a company board.** Add its token and display name to `data/boards.json`. The token is the slug in `boards.greenhouse.io/<token>`, `jobs.lever.co/<token>` or `jobs.ashbyhq.com/<token>`.
- **Add a missing logo.** Add the company's website to `data/domains.json`.
- **Fix an industry.** Add the company to `data/companies.json`.
- **Fix an H-1B name mismatch.** Map the job-board name to the USCIS employer name in `data/aliases.json`.
- **Refresh the H-1B data.** Run `python scripts/build_h1b.py` once a year, or `python scripts/build_h1b.py <export.csv>` with a newer export from the [USCIS H-1B Employer Data Hub](https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub).

## Deploy

In the repo's GitHub settings, go to **Pages** and set the source to **GitHub Actions**. The workflow in `.github/workflows/update.yml` then rebuilds and redeploys the site every day at 11:00 UTC, on every push to `main`, and whenever you run it by hand from the Actions tab.

Sponsorship labels are a best guess. Always confirm on the posting before you apply.
