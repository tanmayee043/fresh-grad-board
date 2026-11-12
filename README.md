# Fresh Grad Board

A daily list of US new-grad computer science jobs posted in the last 3 days, split into jobs that sponsor visas and jobs that don't, and grouped by industry. You can filter by sponsorship, job type (Software Engineer, Data Engineer, Forward Deployed Engineer, Networking and more), industry, posting date and remote.

## How it works

`scripts/fetch_jobs.py` runs every morning in GitHub Actions and writes `site/data/jobs.json`, which the static site in `site/` renders.

1. **Collect.** It reads the [SimplifyJobs New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) list, plus the public Greenhouse, Lever and Ashby job boards of the companies in `data/boards.json`.
2. **Filter.** It keeps US locations and CS roles (software, data, AI/ML, security, infrastructure, embedded, quant, associate PM). It drops internships and senior titles. For company boards, it also keeps only roles that look new-grad: the title says so, or the posting asks for at most 1 year of experience.
3. **Sponsorship.** It reads each posting for wording like "unable to sponsor", "U.S. citizenship required" or "security clearance", and for wording that offers sponsorship. When the posting says nothing, it checks whether the employer had H-1B petitions approved, using USCIS data in `data/h1b_sponsors.json`. Defense employers that say nothing are treated as non-sponsoring.
4. **Industry.** It uses the company map in `data/companies.json` first. If the company isn't listed, it tries hints in the company name, then the employer's NAICS code from the H-1B data, then keywords in the description.
5. **Logos.** Company websites come from `data/domains.json`, or from the careers link when it's on the company's own site. The page loads each logo from Google's favicon service, falls back to DuckDuckGo's, and shows a letter badge if neither has one.

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
