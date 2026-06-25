# Remote Job Alert & Tracker

A small Python tool that pulls **remote job listings** from several reliable
job-board APIs/feeds, saves them to a CSV, and emails you a daily alert when new
jobs appear that weren't already on the list. Built for finding steady,
entry-level remote roles (support, ops, VA, coordinator, analyst, etc.) — not
seasonal internships.

It does **not** scrape LinkedIn or Indeed (they block bots). For LinkedIn, see
[`LINKEDIN_GUIDE.md`](./LINKEDIN_GUIDE.md) — a 10-minute manual routine to run
alongside this.

## Sources

| Source | Type | Needs a key? |
|---|---|---|
| Remotive | Free JSON API (per-keyword search) | No |
| RemoteOK | Free JSON API (recent postings) | No |
| We Work Remotely | Public RSS feed | No |
| Adzuna | Free API, Canada coverage | Yes (free) — optional |
| The Muse | Free API, good for entry-level | No (optional key) |

## Setup

```bash
cd job_tracker
pip install -r requirements.txt
```

## Configure

Open `job_tracker.py` and edit the **CONFIG** block at the top:

```python
KEYWORDS = ["customer support", "virtual assistant", "operations coordinator", ...]
LOCATION = "Canada"
SOURCES  = {"remotive": True, "remoteok": True, ...}  # toggle sources
EMAIL_ENABLED = False                                  # flip to True for alerts
EMAIL_TO = "you@example.com"
```

### Optional: Adzuna (adds Canada-specific listings)

1. Sign up free at <https://developer.adzuna.com/> to get an App ID + App Key.
2. Export them before running:
   ```bash
   export ADZUNA_APP_ID="xxxx"
   export ADZUNA_APP_KEY="yyyy"
   ```
   If unset, Adzuna is skipped automatically and the other sources still run.

## Run

```bash
python3 job_tracker.py
```

First run creates `jobs.csv` and records everything it finds as "new".
Subsequent runs only add postings not already in the file.

### CSV columns

`Job Title, Company, URL, Date Found, Status, Source, Location`

(`Source` and `Location` were added so you can prioritise Canada/Worldwide roles
and apply on the company site quickly. `Status` defaults to `not applied` — flip
it to `applied` as you go.)

## Email alerts

1. In the config block set `EMAIL_ENABLED = True` and confirm `EMAIL_TO`.
2. For Gmail, create an **App Password** (Google Account → Security → 2-Step
   Verification → App passwords).
3. Export it (never stored in the script):
   ```bash
   export JOB_TRACKER_EMAIL_PASSWORD="your-16-char-app-password"
   python3 job_tracker.py
   ```

## Run it daily (cron)

```cron
0 8 * * *  cd /path/to/job_tracker && JOB_TRACKER_EMAIL_PASSWORD=xxxx /usr/bin/python3 job_tracker.py >> run.log 2>&1
```

## Tests

Offline tests (no network needed) cover every source parser, the keyword/location
filters, de-duplication and CSV round-trip:

```bash
python3 test_job_tracker.py
```

## Notes

- These are global remote boards; many roles are "Worldwide"/"Anywhere" but some
  restrict to other regions. The tool keeps Canada / Worldwide / Anywhere /
  unknown and drops ones explicitly limited to e.g. "US only" — check the
  `Location` column before applying.
- Watch for scams in the entry-level remote space: a legit employer never asks
  *you* for money or wants to "onboard" over Telegram/WhatsApp.
- This tool makes outbound requests to the job boards above, so run it from a
  network that allows them (your own machine). Some sandboxed/CI environments
  block outbound traffic.
