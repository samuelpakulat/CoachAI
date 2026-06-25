#!/usr/bin/env python3
"""
Job Alert & Tracker
===================

Scrapes job listings from LinkedIn and Indeed for a set of keywords, saves the
results to a CSV, and emails you a daily alert when *new* jobs appear that
weren't already in the CSV.

Quick start
-----------
1. Edit the CONFIG block below (keywords, location, email).
2. Run it:        python3 job_tracker.py
3. To enable email alerts, set EMAIL_ENABLED = True and export your SMTP
   password (see the EMAIL section below):
       export JOB_TRACKER_EMAIL_PASSWORD="your-app-password"

Run it once a day (e.g. via cron) to get a daily diff of new postings.

A note on scraping (please read)
--------------------------------
- LinkedIn is scraped through its public, no-login "guest" jobs endpoint. This
  is the most reliable path and usually works well for personal/light use.
- Indeed actively blocks automated requests (Cloudflare / anti-bot). The Indeed
  scraper here is best-effort: when Indeed blocks the request, the script logs a
  warning and carries on with whatever it could collect. It is not guaranteed.
- Scrapers break whenever these sites change their markup, and heavy use may
  violate their Terms of Service. Keep the volume low and be a good citizen.
"""

import csv
import os
import re
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

# Keywords to search for. One search is run per keyword on each site.
KEYWORDS = [
    "remote coordinator",
    "data analyst",
    "content moderator",
    "insurance remote",
]

# Where to search. LinkedIn/Indeed both understand free-text locations.
LOCATION = "Ontario, Canada"

# Indeed domain to use (ca = Canada). e.g. "ca.indeed.com", "www.indeed.com".
INDEED_DOMAIN = "ca.indeed.com"

# How many result pages to pull per keyword, per site (keep this small/polite).
PAGES_PER_KEYWORD = 2

# File the results are stored in (acts as the persistent "yesterday's list").
CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.csv")

# ---- Email alerts -----------------------------------------------------------
# Set EMAIL_ENABLED = True to send a daily alert when new jobs are found.
# For Gmail you must create an "App Password" (Google Account > Security >
# 2-Step Verification > App passwords) and export it as JOB_TRACKER_EMAIL_PASSWORD.
# The password is read from the environment so it never lives in this file.
EMAIL_ENABLED = False
EMAIL_TO = "samuelpakulat@gmail.com"
EMAIL_FROM = "samuelpakulat@gmail.com"     # the sending account
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = EMAIL_FROM
SMTP_PASSWORD = os.environ.get("JOB_TRACKER_EMAIL_PASSWORD", "")

# Be polite: seconds to wait between HTTP requests.
REQUEST_DELAY_SECONDS = 1.5

# CSV column order.
CSV_COLUMNS = ["Job Title", "Company", "URL", "Date Found", "Status"]

# ============================================================================
# End of config
# ============================================================================

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
    date_found: str = field(default_factory=lambda: date.today().isoformat())
    status: str = "not applied"

    @property
    def key(self) -> str:
        """Stable identity for de-duplication.

        LinkedIn encodes the job id in the URL path, while Indeed encodes it in
        the ``jk`` query parameter. So we keep the path *and* the ``jk`` param
        but drop volatile tracking params (refId, trk, ...) that change between
        requests for the same job.
        """
        parts = urlsplit(self.url)
        jk = ""
        for pair in parts.query.split("&"):
            if pair.startswith("jk="):
                jk = pair
                break
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, jk, "")
        ).rstrip("/").lower()


def log(msg: str) -> None:
    print(f"[job-tracker] {msg}", flush=True)


def _get(url: str, params=None) -> requests.Response | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        log(f"  request error: {exc}")
        return None
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp


# ----------------------------------------------------------------------------
# LinkedIn (public guest jobs endpoint -- no login required)
# ----------------------------------------------------------------------------

LINKEDIN_GUEST_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)


def scrape_linkedin(keyword: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    for page in range(PAGES_PER_KEYWORD):
        params = {
            "keywords": keyword,
            "location": location,
            "start": page * 25,  # LinkedIn returns ~25 cards per page
        }
        resp = _get(LINKEDIN_GUEST_URL, params=params)
        if resp is None:
            break
        if resp.status_code == 429:
            log("  LinkedIn rate-limited (429); backing off.")
            break
        if resp.status_code != 200:
            log(f"  LinkedIn returned HTTP {resp.status_code}; stopping this keyword.")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("li")
        if not cards:
            break

        found_on_page = 0
        for card in cards:
            title_el = card.select_one(
                "h3.base-search-card__title, .base-search-card__title"
            )
            company_el = card.select_one(
                "h4.base-search-card__subtitle a, .base-search-card__subtitle"
            )
            link_el = card.select_one("a.base-card__full-link, a.base-card__full-link[href]")
            if link_el is None:
                link_el = card.select_one("a[href*='/jobs/view/']")
            if not (title_el and link_el):
                continue
            title = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else ""
            url = link_el.get("href", "").strip()
            if not url:
                continue
            jobs.append(Job(title=title, company=company, url=url, source="LinkedIn"))
            found_on_page += 1

        if found_on_page == 0:
            break
    return jobs


# ----------------------------------------------------------------------------
# Indeed (best-effort -- frequently blocked by anti-bot protection)
# ----------------------------------------------------------------------------

def scrape_indeed(keyword: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    base = f"https://{INDEED_DOMAIN}/jobs"
    for page in range(PAGES_PER_KEYWORD):
        params = {"q": keyword, "l": location, "start": page * 10}
        resp = _get(base, params=params)
        if resp is None:
            break
        if resp.status_code != 200:
            log(
                f"  Indeed returned HTTP {resp.status_code} "
                f"(likely anti-bot block); skipping."
            )
            break

        text = resp.text
        if "Cloudflare" in text and "challenge" in text.lower():
            log("  Indeed served a Cloudflare challenge; skipping.")
            break

        page_jobs = _parse_indeed(text)
        if not page_jobs:
            # No structured data found -- almost always means we were blocked
            # or the markup changed.
            if page == 0:
                log("  Indeed: no job cards parsed (blocked or markup changed).")
            break
        jobs.extend(page_jobs)
    return jobs


def _parse_indeed(html: str) -> list[Job]:
    """Pull jobs out of Indeed's embedded 'mosaic-provider-jobcards' JSON blob."""
    jobs: list[Job] = []

    # Indeed embeds job data as JSON inside a <script> tag. Locate the results
    # array and pull out the fields we care about with light-weight parsing.
    match = re.search(r'"results"\s*:\s*(\[.*?\])\s*,\s*"', html, re.DOTALL)
    if not match:
        return jobs

    blob = match.group(1)
    # Each job entry exposes jobkey / title / company fields.
    for entry in re.finditer(
        r'"jobkey":"(?P<jk>[^"]+)".*?"title":"(?P<title>[^"]*)"'
        r'(?:.*?"company":"(?P<company>[^"]*)")?',
        blob,
        re.DOTALL,
    ):
        jk = entry.group("jk")
        title = _unescape(entry.group("title") or "")
        company = _unescape(entry.group("company") or "")
        url = f"https://{INDEED_DOMAIN}/viewjob?jk={jk}"
        if title:
            jobs.append(Job(title=title, company=company, url=url, source="Indeed"))
    return jobs


def _unescape(s: str) -> str:
    return (
        s.replace("\\u0026", "&")
        .replace("\\u002F", "/")
        .replace('\\"', '"')
        .replace("\\/", "/")
        .strip()
    )


# ----------------------------------------------------------------------------
# CSV persistence
# ----------------------------------------------------------------------------

def load_existing_keys(csv_path: str) -> set[str]:
    """Return the set of URL-keys already recorded, so we can find new jobs."""
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
            writer.writerow(
                {
                    "Job Title": job.title,
                    "Company": job.company,
                    "URL": job.url,
                    "Date Found": job.date_found,
                    "Status": job.status,
                }
            )


# ----------------------------------------------------------------------------
# Email alert
# ----------------------------------------------------------------------------

def send_email_alert(new_jobs: list[Job]) -> None:
    if not EMAIL_ENABLED:
        return
    if not SMTP_PASSWORD:
        log(
            "EMAIL_ENABLED is True but JOB_TRACKER_EMAIL_PASSWORD is not set; "
            "skipping email."
        )
        return

    lines = [f"{len(new_jobs)} new job(s) found on {date.today().isoformat()}:", ""]
    for job in new_jobs:
        lines.append(f"- {job.title} @ {job.company or 'Unknown'} [{job.source}]")
        lines.append(f"  {job.url}")
        lines.append("")
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"Job Alert: {len(new_jobs)} new posting(s)"
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

def main() -> int:
    log(f"Searching {len(KEYWORDS)} keyword(s) in '{LOCATION}'.")
    existing_keys = load_existing_keys(CSV_FILE)
    log(f"{len(existing_keys)} job(s) already on file.")

    scraped: list[Job] = []
    for keyword in KEYWORDS:
        log(f"Keyword: '{keyword}'")
        li = scrape_linkedin(keyword, LOCATION)
        log(f"  LinkedIn: {len(li)} result(s)")
        scraped.extend(li)

        indeed = scrape_indeed(keyword, LOCATION)
        log(f"  Indeed:   {len(indeed)} result(s)")
        scraped.extend(indeed)

    # De-duplicate within this run (same job can match multiple keywords).
    unique: dict[str, Job] = {}
    for job in scraped:
        unique.setdefault(job.key, job)

    # New = scraped this run but not already in the CSV.
    new_jobs = [job for key, job in unique.items() if key not in existing_keys]
    log(f"Total scraped: {len(scraped)} | unique: {len(unique)} | new: {len(new_jobs)}")

    if new_jobs:
        append_jobs(CSV_FILE, new_jobs)
        log(f"Appended {len(new_jobs)} new job(s) to {CSV_FILE}.")
        send_email_alert(new_jobs)
    else:
        log("No new jobs since last run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
