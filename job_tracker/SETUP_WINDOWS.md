# Windows setup (start to finish)

You only do steps 1–4 once. After that, getting jobs is just running `run.bat`
(or letting Task Scheduler do it for you).

---

## 1. Install Python

1. Open the **Microsoft Store**, search **Python 3.12** (or newest), click
   **Get / Install**.
2. To check it worked: press **Start**, type **cmd**, open **Command Prompt**,
   and run:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`. (If it opens the Store
   instead, finish the Store install and try again.)

## 2. Get the code onto your PC

Easiest, no extra tools:

1. Go to your repo on github.com → click the branch dropdown → choose
   **`claude/job-alert-tracker-jw7ksd`**.
2. Click the green **Code** button → **Download ZIP**.
3. Unzip it somewhere easy, e.g. `Documents`. Inside you'll find a
   **`job_tracker`** folder. That folder is all you need.

## 3. Install the libraries

1. Open the `job_tracker` folder in File Explorer.
2. Click the address bar, type **cmd**, press Enter (opens Command Prompt
   already in that folder).
3. Run:
   ```
   pip install -r requirements.txt
   ```

## 4. (Optional) Set up email alerts

Skip this if you just want to read jobs from the CSV.

1. Open `job_tracker.py` in Notepad. Near the top find `EMAIL_ENABLED = False`
   and change it to `EMAIL_ENABLED = True`. Save.
2. Make a Gmail **App Password**: Google Account → Security → 2-Step
   Verification → App passwords (you need 2-Step on first).
3. In the `job_tracker` folder, make a copy of `secrets.example.bat` named
   **`secrets.bat`**, open it in Notepad, and paste your app password into the
   `JOB_TRACKER_EMAIL_PASSWORD=` line. Save. (This file stays on your PC only.)

## 5. Run it

Double-click **`run.bat`** (or run `python job_tracker.py` in the Command
Prompt). The first run creates `jobs.csv` with everything it finds. Open
`jobs.csv` in Excel to browse — sort/filter by Source or Location, and change
the **Status** column from `not applied` to `applied` as you go.

Every later run only adds *new* jobs and (if email is on) emails them to you.

## 6. Make it run automatically every day

So you don't have to remember:

1. Press **Start**, type **Task Scheduler**, open it.
2. Right side → **Create Basic Task**.
3. Name: `Job Tracker`. Next.
4. Trigger: **Daily**, pick a time (e.g. 8:00 AM). Next.
5. Action: **Start a program**. Next.
6. **Program/script**: click **Browse** and select your **`run.bat`**
   (the one inside `job_tracker`). Next → **Finish**.

That's it — your PC will run it each morning. If email is on, you'll just get
the new jobs in your inbox; otherwise open `jobs.csv` when you sit down.

> Note: Task Scheduler runs it only while your PC is on. If it's off at 8 AM,
> it runs at the next login (there's a checkbox "Run task as soon as possible
> after a scheduled start is missed" in the task's properties if you want that).

---

## If something goes wrong

- **`python` not recognized** → the Store install didn't finish, or reopen
  Command Prompt after installing.
- **`pip` not recognized** → use `python -m pip install -r requirements.txt`.
- **No jobs found** → check `run.log` in the folder for errors. A day with few
  postings is normal; the tool only saves *new* ones it hasn't seen before.
- **Email didn't send** → confirm `EMAIL_ENABLED = True`, that `secrets.bat`
  exists with your App Password (a normal Gmail password won't work), and check
  `run.log`.

See `README.md` for full config options and `LINKEDIN_GUIDE.md` for the manual
LinkedIn routine to run alongside this.
