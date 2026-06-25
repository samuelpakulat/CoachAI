#!/usr/bin/env python3
"""
Remote Job Alert & Tracker
==========================

Pulls remote job listings from several *reliable* job-board APIs/feeds (the
kind that are meant to be queried and don't block you), saves new postings to a
CSV, and emails you a daily alert when new jobs appear that weren't already on
the list.

Sources (no scraping of LinkedIn/Indeed -- those block bots):
  - Remotive          (free JSON API, per-keyword search)
  - RemoteOK          (free JSON API, recent postings)
  - We Work Remotely  (public RSS feed)
  - Adzuna            (free API, Canada coverage -- needs a free key, optional)
  - The Muse          (free API, good for entry-level -- optional)

Quick start
-----------
1. Edit the CONFIG block below (keywords, location, email, source keys).
2. Install deps:   pip install -r requirements.txt
3. Run it:         python3 job_tracker.py

Run it once a day (e.g. via cron) to get a daily diff of new postings.
"""

import csv
import os
import smtplib
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from email.mime.text import MIMEText
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

# ============================================================================
# CONFIG  --  edit this block
# ============================================================================

# Keywords to search for. Steady, entry-level remote roles that hire year-round.
KEYWORDS = [
    # original picks
    "remote coordinator",
    "data analyst",
    "content moderator",
    "insurance remote",
    # widened: ongoing entry-level remote categories that hire students
    "customer support",
    "customer success",
    "virtual assistant",
    "administrative assistant",
    "sales development representative",
    "operations coordinator",
    "community moderator",
    "social media coordinator",
    "data entry",
    "quality assurance tester",
]

# Soft location preference. Jobs explicitly restricted to other regions (e.g.
# "US only", "Europe only") are dropped; Canada / Worldwide / Anywhere / unknown
# are kept. Used by Adzuna's location filter too.
LOCATION = "Canada"

# How many result pages to pull per source (keep small/polite).
PAGES = 2

# Which sources to use.
SOURCES = {
    "remotive": True,
    "remoteok": True,
    "weworkremotely": True,
    "adzuna": True,     # only runs if ADZUNA keys are set below
    "themuse": True,
}

# Adzuna: free keys from https://developer.adzuna.com/ (read from env so they
# never live in this file). Leave unset to skip Adzuna.
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

# The Muse: optional API key (works without one, just lower rate limits).
THEMUSE_API_KEY = os.environ.get("THEMUSE_API_KEY", "")

# File the results are stored in (acts as the persistent "yesterday's list").
CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.csv")

# ---- Email alerts -----------------------------------------------------------
# Set EMAIL_ENABLED = True to send a daily alert when new jobs are found.
# For Gmail, create an "App Password" (Google Account > Security > 2-Step
# Verification > App passwords) and export it as JOB_TRACKER_EMAIL_PASSWORD.
EMAIL_ENABLED = False
EMAIL_TO = "samuelpakulat@gmail.com"
EMAIL_FROM = "samuelpakulat@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = EMAIL_FROM
SMTP_PASSWORD = os.environ.get("JOB_TRACKER_EMAIL_PASSWORD", "")

# Be polite: seconds to wait between HTTP requests.
REQUEST_DELAY_SECONDS = 1.5

# CSV column order. (Source + Location added so you can prioritise Canada-OK
# roles and apply on the company site quickly.)
CSV_COLUMNS = ["Job Title", "Company", "URL", "Date Found", "Status", "Source", "Location"]

# ============================================================================
# End of config
# ============================================================================

# Let the cloud scheduler (GitHub Actions) toggle email via an env var, so it
# can be enabled without editing this file.
_env_email = os.environ.get("EMAIL_ENABLED")
if _env_email is not None:
    EMAIL_ENABLED = _env_email.strip().lower() in ("1", "true", "yes")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str = ""
    location: str = ""
    date_found: str = field(default_factory=lambda: date.today().isoformat())
    status: str = "not applied"

    @property
    def key(self) -> str:
        """Stable identity for de-duplication: URL without query/fragment.

        All the sources used here put the job id in the URL *path*, so dropping
        query strings (tracking params) gives a stable key.
        """
        parts = urlsplit(self.url)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", "")
        ).rstrip("/").lower()


def log(msg: str) -> None:
    print(f"[job-tracker] {msg}", flush=True)


# ----------------------------------------------------------------------------
# Filtering helpers
# ----------------------------------------------------------------------------

def matches_keywords(text: str, keywords: list[str]) -> str | None:
    """Return the first keyword that matches, or None.

    A keyword matches when every word in it appears in `text` (case-insensitive),
    so "remote coordinator" matches "Remote Project Coordinator".
    """
    haystack = (text or "").lower()
    for kw in keywords:
        if all(tok in haystack for tok in kw.lower().split()):
            return kw
    return None


_LOCATION_ALLOW = ("canada", "anywhere", "worldwide", "global", "north america",
                   "americas", "ontario", "toronto", "remote", "flexible")
_LOCATION_BLOCK = ("usa only", "us only", "united states only", "us-only",
                   "europe only", "uk only", "eu only", "emea only", "apac only",
                   "india only", "us based", "u.s. only")


def location_ok(loc: str) -> bool:
    """Permissive location filter: keep unless clearly restricted away from Canada."""
    l = (loc or "").lower().strip()
    if not l:
        return True
    if any(a in l for a in _LOCATION_ALLOW):
        return True
    if any(b in l for b in _LOCATION_BLOCK):
        return False
    return True  # unknown / unrestricted -> keep, you can eyeball the column


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

def _get(url: str, params=None, accept_json=True) -> requests.Response | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept": "application/json" if accept_json else "application/rss+xml, text/xml",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=25)
    except requests.RequestException as exc:
        log(f"  request error: {exc}")
        return None
    time.sleep(REQUEST_DELAY_SECONDS)
    if resp.status_code != 200:
        log(f"  HTTP {resp.status_code} from {urlsplit(url).netloc}")
        return None
    return resp


# ----------------------------------------------------------------------------
# Source: Remotive  (per-keyword JSON search)
# ----------------------------------------------------------------------------

def fetch_remotive(keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []
    for kw in keywords:
        resp = _get("https://remotive.com/api/remote-jobs", params={"search": kw, "limit": 50})
        if resp is None:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        jobs.extend(parse_remotive(data))
    return jobs


def parse_remotive(data: dict) -> list[Job]:
    out: list[Job] = []
    for j in data.get("jobs", []):
        loc = j.get("candidate_required_location", "")
        if not location_ok(loc):
            continue
        out.append(Job(
            title=j.get("title", "").strip(),
            company=j.get("company_name", "").strip(),
            url=j.get("url", "").strip(),
            source="Remotive",
            location=loc,
        ))
    return [j for j in out if j.title and j.url]


# ----------------------------------------------------------------------------
# Source: RemoteOK  (single JSON feed of recent jobs -> filter client-side)
# ----------------------------------------------------------------------------

def fetch_remoteok(keywords: list[str]) -> list[Job]:
    resp = _get("https://remoteok.com/api")
    if resp is None:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    return parse_remoteok(data, keywords)


def parse_remoteok(data: list, keywords: list[str]) -> list[Job]:
    out: list[Job] = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue  # skips the leading legal-notice element
        title = (j.get("position") or "").strip()
        tags = " ".join(j.get("tags", []) or [])
        if not matches_keywords(f"{title} {tags}", keywords):
            continue
        loc = (j.get("location") or "").strip()
        if not location_ok(loc):
            continue
        url = (j.get("url") or "").strip()
        if url.startswith("/"):
            url = "https://remoteok.com" + url
        out.append(Job(
            title=title,
            company=(j.get("company") or "").strip(),
            url=url,
            source="RemoteOK",
            location=loc,
        ))
    return [j for j in out if j.title and j.url]


# ----------------------------------------------------------------------------
# Source: We Work Remotely  (RSS feed -> filter client-side)
# ----------------------------------------------------------------------------

def fetch_weworkremotely(keywords: list[str]) -> list[Job]:
    resp = _get("https://weworkremotely.com/remote-jobs.rss", accept_json=False)
    if resp is None:
        return []
    return parse_wwr(resp.text, keywords)


def parse_wwr(xml_text: str, keywords: list[str]) -> list[Job]:
    out: list[Job] = []
    soup = BeautifulSoup(xml_text, "xml")
    for item in soup.find_all("item"):
        raw_title = (item.title.get_text(strip=True) if item.title else "")
        link = (item.link.get_text(strip=True) if item.link else "")
        region_el = item.find("region")
        loc = region_el.get_text(strip=True) if region_el else ""
        # WWR titles look like "Company Name: Job Title"
        if ":" in raw_title:
            company, title = raw_title.split(":", 1)
        else:
            company, title = "", raw_title
        title, company = title.strip(), company.strip()
        if not matches_keywords(title, keywords):
            continue
        if not location_ok(loc):
            continue
        out.append(Job(title=title, company=company, url=link,
                       source="WeWorkRemotely", location=loc))
    return [j for j in out if j.title and j.url]


# ----------------------------------------------------------------------------
# Source: Adzuna  (per-keyword JSON search, Canada -- needs free API keys)
# ----------------------------------------------------------------------------

def fetch_adzuna(keywords: list[str]) -> list[Job]:
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        log("  Adzuna skipped (ADZUNA_APP_ID / ADZUNA_APP_KEY not set).")
        return []
    jobs: list[Job] = []
    for kw in keywords:
        for page in range(1, PAGES + 1):
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "what": kw,
                "where": LOCATION,
                "content-type": "application/json",
                "results_per_page": 25,
            }
            resp = _get(f"https://api.adzuna.com/v1/api/jobs/ca/search/{page}", params=params)
            if resp is None:
                break
            try:
                data = resp.json()
            except ValueError:
                break
            page_jobs = parse_adzuna(data)
            if not page_jobs:
                break
            jobs.extend(page_jobs)
    return jobs


def parse_adzuna(data: dict) -> list[Job]:
    out: list[Job] = []
    for j in data.get("results", []):
        loc = (j.get("location", {}) or {}).get("display_name", "")
        out.append(Job(
            title=(j.get("title") or "").strip(),
            company=(j.get("company", {}) or {}).get("display_name", "").strip(),
            url=(j.get("redirect_url") or "").strip(),
            source="Adzuna",
            location=loc,
        ))
    return [j for j in out if j.title and j.url]


# ----------------------------------------------------------------------------
# Source: The Muse  (JSON, good for entry-level -> filter client-side)
# ----------------------------------------------------------------------------

def fetch_themuse(keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []
    for page in range(PAGES):
        params = {"page": page, "location": "Flexible / Remote"}
        if THEMUSE_API_KEY:
            params["api_key"] = THEMUSE_API_KEY
        resp = _get("https://www.themuse.com/api/public/jobs", params=params)
        if resp is None:
            break
        try:
            data = resp.json()
        except ValueError:
            break
        page_jobs = parse_themuse(data, keywords)
        jobs.extend(page_jobs)
        if not data.get("results"):
            break
    return jobs


def parse_themuse(data: dict, keywords: list[str]) -> list[Job]:
    out: list[Job] = []
    for j in data.get("results", []):
        title = (j.get("name") or "").strip()
        if not matches_keywords(title, keywords):
            continue
        locs = ", ".join(loc.get("name", "") for loc in j.get("locations", []) or [])
        if not location_ok(locs):
            continue
        out.append(Job(
            title=title,
            company=(j.get("company", {}) or {}).get("name", "").strip(),
            url=(j.get("refs", {}) or {}).get("landing_page", "").strip(),
            source="TheMuse",
            location=locs,
        ))
    return [j for j in out if j.title and j.url]


# ----------------------------------------------------------------------------
# CSV persistence
# ----------------------------------------------------------------------------

def load_existing_keys(csv_path: str) -> set[str]:
    keys: set[str] = set()
    if not os.path.exists(csv_path):
        return keys
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("URL") or "").strip()
            if url:
                keys.add(Job(title="", company="", url=url).key)
    return keys


def append_jobs(csv_path: str, jobs: list[Job]) -> None:
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for job in jobs:
            writer.writerow({
                "Job Title": job.title,
                "Company": job.company,
                "URL": job.url,
                "Date Found": job.date_found,
                "Status": job.status,
                "Source": job.source,
                "Location": job.location,
            })


# ----------------------------------------------------------------------------
# Email alert
# ----------------------------------------------------------------------------

def send_email_alert(new_jobs: list[Job]) -> None:
    if not EMAIL_ENABLED:
        return
    if not SMTP_PASSWORD:
        log("EMAIL_ENABLED is True but JOB_TRACKER_EMAIL_PASSWORD is not set; skipping email.")
        return

    lines = [f"{len(new_jobs)} new remote job(s) found on {date.today().isoformat()}:", ""]
    for job in new_jobs:
        loc = f" ({job.location})" if job.location else ""
        lines.append(f"- {job.title} @ {job.company or 'Unknown'}{loc} [{job.source}]")
        lines.append(f"  {job.url}")
        lines.append("")
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"Remote Job Alert: {len(new_jobs)} new posting(s)"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        log(f"Email alert sent to {EMAIL_TO}.")
    except Exception as exc:  # noqa: BLE001 -- report any SMTP failure plainly
        log(f"Failed to send email: {exc}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

FETCHERS = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "weworkremotely": fetch_weworkremotely,
    "adzuna": fetch_adzuna,
    "themuse": fetch_themuse,
}


def main() -> int:
    log(f"Searching {len(KEYWORDS)} keyword(s), location preference '{LOCATION}'.")
    existing_keys = load_existing_keys(CSV_FILE)
    log(f"{len(existing_keys)} job(s) already on file.")

    scraped: list[Job] = []
    for name, enabled in SOURCES.items():
        if not enabled:
            continue
        try:
            results = FETCHERS[name](KEYWORDS)
        except Exception as exc:  # noqa: BLE001 -- one bad source shouldn't kill the run
            log(f"  {name}: error ({exc}); continuing.")
            results = []
        log(f"  {name}: {len(results)} result(s)")
        scraped.extend(results)

    # De-duplicate within this run: by URL, and collapse obvious cross-source
    # duplicates that share the same title + company.
    unique: dict[str, Job] = {}
    seen_title_company: set[tuple[str, str]] = set()
    for job in scraped:
        if job.key in unique:
            continue
        tc = (job.title.lower().strip(), job.company.lower().strip())
        if tc != ("", "") and tc in seen_title_company:
            continue
        unique[job.key] = job
        seen_title_company.add(tc)

    new_jobs = [job for key, job in unique.items() if key not in existing_keys]
    log(f"Total: {len(scraped)} | unique: {len(unique)} | new: {len(new_jobs)}")

    if new_jobs:
        append_jobs(CSV_FILE, new_jobs)
        log(f"Appended {len(new_jobs)} new job(s) to {CSV_FILE}.")
        send_email_alert(new_jobs)
    else:
        log("No new jobs since last run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
