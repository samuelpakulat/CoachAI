# Job Alert & Tracker

A small Python tool that scrapes job listings from **LinkedIn** and **Indeed**
for keywords you choose, saves them to a CSV, and emails you a daily alert when
*new* jobs appear that weren't already on the list.

## What it does

- Searches each keyword on LinkedIn and Indeed, filtered to your location
  (default: Ontario, Canada).
- Saves results to `jobs.csv` with columns:
  `Job Title, Company, URL, Date Found, Status`.
- On each run, compares against what's already in `jobs.csv` and only adds new
  postings (so the CSV doubles as "yesterday's list").
- Optionally emails you the new jobs.

## Setup

```bash
cd job_tracker
pip install -r requirements.txt
```

## Configure

Open `job_tracker.py` and edit the **CONFIG** block at the top:

```python
KEYWORDS = ["remote coordinator", "data analyst", "content moderator", "insurance remote"]
LOCATION = "Ontario, Canada"
EMAIL_ENABLED = False          # flip to True once email is set up
EMAIL_TO = "you@example.com"
```

## Run

```bash
python3 job_tracker.py
```

First run creates `jobs.csv` and records everything it finds as "new".
Subsequent runs only add postings that weren't already in the file.

## Email alerts

1. In the config block set `EMAIL_ENABLED = True` and confirm `EMAIL_TO` /
   `EMAIL_FROM`.
2. For Gmail, create an **App Password**
   (Google Account → Security → 2-Step Verification → App passwords).
3. Export it before running (it is never stored in the script):

   ```bash
   export JOB_TRACKER_EMAIL_PASSWORD="your-16-char-app-password"
   python3 job_tracker.py
   ```

If you use a different provider, change `SMTP_HOST` / `SMTP_PORT` in the config.

## Run it daily (cron)

Example: run every day at 8am and log the output.

```cron
0 8 * * *  cd /path/to/job_tracker && JOB_TRACKER_EMAIL_PASSWORD=xxxx /usr/bin/python3 job_tracker.py >> run.log 2>&1
```

## Important notes on scraping

- **LinkedIn** is scraped through its public, no-login "guest" jobs endpoint.
  This is the most reliable path and works well for light personal use.
- **Indeed** actively blocks automated requests (Cloudflare / anti-bot). The
  Indeed scraper is **best-effort**: when Indeed blocks the request the script
  logs a warning and continues. Don't be surprised if it returns nothing on a
  given day.
- Scrapers break whenever these sites change their HTML, and high-volume
  scraping may violate their Terms of Service. Keep `PAGES_PER_KEYWORD` low and
  run no more than a couple of times a day.
- If you outgrow scraping, consider an official/aggregator API (e.g. a job board
  API) for reliability.

> Note: this tool makes outbound requests to linkedin.com and indeed.com, so it
> must be run from a network that allows those (e.g. your own machine). Some
> sandboxed/CI environments block them.
