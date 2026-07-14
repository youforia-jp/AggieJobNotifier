# Jobs-for-Aggies Notifier 🐾

> [!CAUTION]
> **⚠️ IMPORTANT: YOUR COMPUTER MUST BE TURNED ON, AWAKE, AND CONNECTED TO THE INTERNET FOR THIS NOTIFIER TO RUN!**
> If your PC goes to sleep, shuts down, or loses connection, the scraper will stop checking for new jobs. If you want 24/7 autonomous monitoring without leaving your computer on, you must host this code on a cloud server (such as an AWS EC2 instance).

> [!NOTE]
> **📣 COMING SOON: PUBLIC DISCORD SERVER & BOT**
> I will be launching a public Discord server featuring a shared bot that broadcasts job updates directly. Once it goes live, you will not need to run this code or keep your computer on at all! Updates will be sent to major/level specific channels automatically. Stay tuned!

A production-ready Python scraper that monitors the **Texas A&M Symplicity Job Board** and sends Discord alerts whenever a new job matching your keywords is posted.

---

## How it works

```
Playwright (Chromium) → TAMU SSO Login (once)
    → Navigate Jobs SPA
        → Intercept Internal JSON API  ──► fallback: DOM parsing
            → Keyword Filter
                → Compare with jobs_state.json
                    → Send Discord Embed for new jobs
                        → Save updated state
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 + |
| pip | latest |
| A TAMU NetID | — |
| A Discord Server (with a webhook) | — |

---

## Quick Start

### 1 — Clone / download the project

```bash
cd ~/JobsforAggiesNotifier
```

### 2 — Create a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4 — Install Playwright's Chromium browser

```bash
playwright install chromium
```

### 5 — Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Variable | Description |
|---|---|
| `TAMU_USERNAME` | Your full TAMU email, e.g. `juan@tamu.edu` |
| `TAMU_PASSWORD` | Your TAMU password |
| `DISCORD_WEBHOOK_URL` | Webhook URL from Discord server settings |
| `MAX_PAGES` | How many pages of results to scrape (default `3`) |
| `HEADLESS` | `true` for background runs; `false` to see the browser |

### 6 — Customise your keyword filters

Edit `config.py` → `KEYWORDS` list.  Any job whose title contains one of these strings (case-insensitive) will trigger a notification.

```python
KEYWORDS = [
    "Developer",
    "IT Support",
    "Grader",
    "Research",
    # add your own …
]
```

Set `KEYWORDS = []` to receive **all** job postings without filtering.

### 7 — Configure Advanced Website Filters & Fuzzy Matching

You can apply advanced search filters (e.g. Remote vs On-site, Job Type, Work Study requirement, etc.) directly at the server level by editing `config.py`.

Open `config.py` and populate the lists in the `FILTERS` dictionary with the desired options documented in the comments. For example:

```python
FILTERS = {
    "symp_remote_onsite": ["remote", "hybrid"],  # Only show Remote & Hybrid roles
    "job_type": ["5"],                            # Only show Internships
    "tamu_job_location": ["1"],                   # Only show On-Campus jobs
}
```

#### Fuzzy Matching & Location Filter
* **Fuzzy Matching (`rapidfuzz`)**: The scraper uses fuzzy partial-ratio matching to evaluate keyword matches in job titles. You can adjust `FUZZY_THRESHOLD=80` in `.env` (default is `80`; higher is stricter).
* **Location Filtering**: Add a comma-separated list to `LOCATION_FILTER` in `.env` (e.g. `LOCATION_FILTER=College Station, Remote`) to filter scraped listings by location.


---

## First-time Authentication (IMPORTANT)

The TAMU SSO uses **Duo 2-Factor Authentication**.  You must complete this once interactively.

```bash
python main.py --login
```

This will:
1. Open a **visible** Chromium window.
2. Fill in your NetID and password automatically.
3. Pause and print a message like:

```
╔══════════════════════════════════════════════════════════╗
║  DUO 2FA REQUIRED — approve the push on your phone now  ║
║  Waiting up to 90 seconds …                             ║
╚══════════════════════════════════════════════════════════╝
```

4. After you approve the push in the Duo app, it saves your session to **`session_state.json`**.
5. All future **headless** runs reuse this session — no password prompt, no Duo.

> **⚠️ Keep `session_state.json` private.**  
> It contains your authenticated cookies.  Add it to `.gitignore`.

---

## Normal headless run

```bash
python main.py
```

Flags:

| Flag | Description |
|---|---|
| `--login` | Force a fresh interactive login (deletes old session) |
| `--no-filter` | Bypass keyword filtering — notify on ALL new jobs |

---

## Session expiry

Symplicity sessions typically last **a few days to a week**.  
When the session expires, the script detects the CAS redirect and automatically:
1. Deletes the stale `session_state.json`.
2. Re-launches a headed browser and prompts for Duo.
3. Saves the fresh session and continues the run.

You can also force a refresh manually:

```bash
python main.py --login
```

---

## Scheduling — run it daily automatically

### Windows — Task Scheduler

1. Open **Task Scheduler** → *Create Basic Task*.
2. Set the trigger to **Daily** at your preferred time.
3. For the Action, choose **Start a Program**:
   - Program: `C:\path\to\JobsforAggiesNotifier\.venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\path\to\JobsforAggiesNotifier`
4. Check *Run whether user is logged on or not* and *Run with highest privileges*.

### macOS / Linux — cron

Open your crontab:

```bash
crontab -e
```

Add a line to run at 8:00 AM every day:

```cron
0 8 * * * /home/youruser/JobsforAggiesNotifier/.venv/bin/python /home/youruser/JobsforAggiesNotifier/main.py >> /home/youruser/JobsforAggiesNotifier/cron.log 2>&1
```

> **Tip**: If Duo triggers during an automated run (session expired), the script will hang because there is no display.  
> To avoid this, run `python main.py --login` manually to refresh the session before the scheduled window.

---

## File reference

| File | Purpose |
|---|---|
| `main.py` | Core Playwright automation, filtering, Discord notifications |
| `config.py` | Keywords, URLs, timeouts — edit here |
| `.env` | Secrets (never commit this) |
| `.env.example` | Template for `.env` |
| `requirements.txt` | Python package dependencies |
| `jobs_state.json` | Auto-generated; tracks seen job IDs |
| `session_state.json` | Auto-generated; saved browser session (keep private) |
| `notifier.log` | Auto-generated; rolling log file |

---

## Discord embed preview

Each new matching job will appear in your Discord channel like this:

```
🤖 Aggie Job Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Software Developer Intern
  ─────────────────────────────
  🏢 Employer    │ 📍 Location    │ 💵 Pay
  Acme Corp      │ College Station│ $18/hr
  ─────────────────────────────
  📋 Type: Full-time Internship
  📅 Posted: 2026-07-13
  [Click title to open application]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Jobs for Aggies • Texas A&M University
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `TAMU_USERNAME and TAMU_PASSWORD must be set` | Your `.env` file is missing or not loaded |
| Script hangs at Duo | Duo wasn't approved within 90 s — re-run `--login` |
| 0 jobs scraped (API) and 0 (DOM) | Symplicity updated its markup; open an issue with a screenshot of the page |
| Discord message not sent | Check `DISCORD_WEBHOOK_URL` is correct and the webhook still exists |
| `SessionExpiredError` loop | Delete `session_state.json` and run `--login` again |

---

## Security notes

- `.env` and `session_state.json` should **never** be committed to git.  
  Add both to `.gitignore`:
  ```
  .env
  session_state.json
  ```
- The notifier only reads the job board — it does not submit applications.

---

*Built with ❤️ for Aggies.*
