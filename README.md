# Jobs-for-Aggies Notifier 🐾

> [!CAUTION]
> **⚠️ IMPORTANT: YOUR COMPUTER MUST BE TURNED ON, AWAKE, AND CONNECTED TO THE INTERNET FOR THIS NOTIFIER TO RUN!**
> If your PC goes to sleep, shuts down, or loses connection, the scraper will stop checking for new jobs. If you want 24/7 autonomous monitoring without leaving your computer on, you must host this code on a cloud server (such as an AWS EC2 instance).

> [!NOTE]
> **📣 COMING SOON: PUBLIC DISCORD SERVER & BOT**
> I will be launching a public Discord server featuring a shared bot that broadcasts job updates directly. Once it goes live, you will not need to run this code or keep your computer on at all! Updates will be sent to major/level specific channels automatically. Stay tuned!

A standalone, zero-code Windows desktop application that monitors the **Texas A&M Symplicity Job Board** and sends Discord alerts whenever a new job matching your keywords is posted.

---

## Quick Start (No Code Required)

### 1 — Download the Project
1. Download this project as a ZIP file (click the green **Code** button at the top right, then **Download ZIP**).
2. Extract the ZIP file to a folder on your computer (e.g., your Desktop).

### 2 — Open the Application
Double-click **[AggieJobNotifier.exe](file:///c:/Users/juanp/Desktop/JobsforAggiesNotifier/AggieJobNotifier.exe)** in the folder. A dark-mode desktop window will open.

### 3 — Fill in your Settings
Configure the settings in the left panel of the application window:
* **TAMU NetID**: Your full TAMU email address (e.g., `netid@tamu.edu`).
* **TAMU Password**: Your TAMU login password.
* **Discord Webhook URL**: The webhook URL of the Discord channel where you want to receive alerts (configured in Discord via *Channel Settings → Integrations → Webhooks*).
* **Run Interval (minutes)**: How often the bot checks for new jobs (default: `60` minutes).
* **Title Keywords**: Comma-separated list of roles you want to search for (e.g., `Developer, Software, IT Support, Assistant`). Leave empty to get notified for **all** matching jobs.
* **Fuzzy Matching & Advanced Filters**: Check any checkboxes for remote/onsite, job types, campus location, or work authorization limits to filter results.

### 4 — Start the Scraper
Click the **▶ Start** button. 

* **First-time Login (Duo 2FA)**: On your very first run, the application will open a **visible browser window**. Watch the browser, enter your NetID/password if prompted, and **approve the Duo push on your phone**.
* Once approved, the bot saves a secure login session (`session_state.json`) and restarts in **headless (hidden) mode**. From this point forward, you won't need to approve Duo again unless the session expires (usually once a week).

---

## How the Scraper Behaves

* **Startup Confirmation**: When you start the scraper, it immediately fetches all jobs currently on the board, remembers them as "old jobs" (seeding them so they **do not** spam your Discord channel), and sends a confirmation message to Discord:
  > **Bot Status: the script is working! you will be notified if any new jobs are published in X minutes.**
* **Real-time Notifications**: Every X minutes, the bot re-checks the job board. If a newly published job matches your filters, it is sent to your Discord channel as a premium styled embed.

---

## 📅 Run Automatically on Computer Startup
To make the notifier run automatically every time you turn on your computer:
1. Press `Win + R`, type `shell:startup`, and press Enter. This opens your Windows **Startup** folder.
2. Right-click [AggieJobNotifier.exe](file:///c:/Users/juanp/Desktop/JobsforAggiesNotifier/AggieJobNotifier.exe), select **Create shortcut**, and drag that shortcut into the Startup folder.
3. The notifier will now launch automatically in the background whenever you log in to Windows!

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Playwright browser error on startup | The application downloads Chromium automatically on first run. If it fails, check your internet connection and restart the app. |
| Discord message not sent | Double-check that your Discord Webhook URL is entered correctly and that the channel hasn't deleted the webhook integration. |
| Script hangs at Duo | If you don't approve the Duo push on your phone within 90 seconds, the login will time out. Stop the scraper and click **Force Login** to try again. |

---

<details>
<summary>💻 For Developers / Advanced Configuration</summary>

### Running from Source IDE

If you want to run or modify the Python source code directly:

1. **Setup Environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```
2. **Configure Settings**:
   Copy `.env.example` to `.env` and edit settings, or use the centralized configurations in `config.py`.
3. **Execution**:
   * GUI application: `python gui.py`
   * Scraper pipeline (single headless check): `python main.py`
   * CLI continuous mode: `python main.py --continuous`
   * Run pre-flight check: `python check_setup.py`
4. **Packaging the EXE**:
   Rebuild the standalone package using PyInstaller:
   ```bash
   pyinstaller --noconfirm AggieJobNotifier.spec
   ```
</details>

---

*Built with ❤️ for Aggies.*
