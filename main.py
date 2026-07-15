"""
main.py — Texas A&M Symplicity Job Board Notifier
==================================================
Pipeline:
  1. Load environment variables (.env).
  2. Try to resume a saved Playwright session (session_state.json).
     If the session is expired or missing, perform a full TAMU SSO login
     and save the new session to disk.
  3. Navigate to the public-jobs SPA and intercept the internal JSON API
     responses that populate the job list.  Falls back to DOM parsing if
     the API shape changes.
  4. Filter jobs against the keyword list in config.py.
  5. Compare against jobs_state.json; send Discord embeds for new jobs only.
  6. Persist updated state.

Usage:
  python main.py                   # normal headless run
  python main.py --login           # force a fresh interactive login
  python main.py --no-filter       # skip keyword filtering (all jobs)
  python main.py --debug           # save screenshots for troubleshooting
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, quote

import requests
from dotenv import load_dotenv

# Force Playwright to use a persistent user AppData directory rather than the temp folder
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    _local_appdata = os.environ.get("LOCALAPPDATA")
    if _local_appdata:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_appdata, "ms-playwright")

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

import config

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("notifier.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / Config Defaults
# ---------------------------------------------------------------------------
import threading

stop_event = threading.Event()

TAMU_USERNAME: str = ""
TAMU_PASSWORD: str = ""
DISCORD_WEBHOOK_URL: str = ""
MAX_PAGES: int = 3
HEADLESS: bool = True
LOCATION_FILTER: list[str] = []
FUZZY_THRESHOLD: int = 80
MY_ACADEMIC_LEVEL: str = "all"
RUN_INTERVAL_MINS: int = 60

def reload_config() -> None:
    """Reload configuration from .env and config.py (called by GUI when starting)."""
    global TAMU_USERNAME, TAMU_PASSWORD, DISCORD_WEBHOOK_URL, MAX_PAGES, HEADLESS
    global LOCATION_FILTER, FUZZY_THRESHOLD, MY_ACADEMIC_LEVEL, RUN_INTERVAL_MINS
    
    import importlib
    importlib.reload(config)
    load_dotenv(override=True)

    TAMU_USERNAME = os.getenv("TAMU_USERNAME", "")
    TAMU_PASSWORD = os.getenv("TAMU_PASSWORD", "")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
    MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
    HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")

    # Load Keywords
    env_keywords = os.getenv("KEYWORDS", "")
    if env_keywords:
        config.KEYWORDS = [x.strip() for x in env_keywords.split(",") if x.strip()]

    env_locations = os.getenv("LOCATION_FILTER", "")
    if env_locations:
        locs = [x.strip() for x in env_locations.split(",") if x.strip()]
    else:
        locs = getattr(config, "LOCATION_FILTER", [])
    LOCATION_FILTER = [x for x in locs if x.strip()]

    FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", str(getattr(config, "FUZZY_THRESHOLD", 80))))
    MY_ACADEMIC_LEVEL = os.getenv("MY_ACADEMIC_LEVEL", getattr(config, "MY_ACADEMIC_LEVEL", "all")).lower().strip()
    RUN_INTERVAL_MINS = int(os.getenv("RUN_INTERVAL_MINS", str(getattr(config, "RUN_INTERVAL_MINS", 60))))

    # Load advanced search API filters from .env
    env_filters = {
        "symp_remote_onsite": os.getenv("FILTER_REMOTE_ONSITE", ""),
        "job_type": os.getenv("FILTER_JOB_TYPE", ""),
        "job_category": os.getenv("FILTER_JOB_CATEGORY", ""),
        "tamu_job_location": os.getenv("FILTER_TAMU_JOB_LOCATION", ""),
        "position_category": os.getenv("FILTER_POSITION_CATEGORY", ""),
        "school": os.getenv("FILTER_SCHOOL", ""),
        "work_authorization": os.getenv("FILTER_WORK_AUTH", ""),
    }

    # Split comma separated filters
    for key, env_val in env_filters.items():
        if env_val:
            config.FILTERS[key] = [x.strip() for x in env_val.split(",") if x.strip()]
        else:
            config.FILTERS[key] = []

    # Single string filters
    config.FILTERS["postdate"] = os.getenv("FILTER_POSTDATE", "")
    config.FILTERS["exclude_applied_jobs"] = os.getenv("FILTER_EXCLUDE_APPLIED", "")
    config.FILTERS["nationwide_jobs"] = os.getenv("FILTER_EXCLUDE_NATIONWIDE", "")

# Initial load
reload_config()

# ---------------------------------------------------------------------------
# Colour constants for Discord embeds
# ---------------------------------------------------------------------------
EMBED_COLOR_NEW = 0x4CAF50      # green  — new job
EMBED_COLOR_ERROR = 0xF44336    # red    — error notice


# ===========================================================================
# State management
# ===========================================================================

class StateManager:
    """Persist seen job IDs so we only alert on truly new postings."""

    def __init__(self, path: str = config.STATE_FILE) -> None:
        self.path = Path(path)
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                ids = set(str(jid) for jid in data.get("seen_ids", []))
                log.info("State loaded — %d previously seen jobs.", len(ids))
                return ids
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Could not parse state file, starting fresh: %s", exc)
        return set()

    def is_new(self, job_id: str) -> bool:
        return str(job_id) not in self._seen

    def mark_seen(self, job_id: str) -> None:
        self._seen.add(str(job_id))

    def save(self) -> None:
        payload = {
            "seen_ids": sorted(self._seen),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("State saved — %d total seen jobs.", len(self._seen))


# ===========================================================================
# Discord notifications
# ===========================================================================

def _truncate(text: str, limit: int = 1024) -> str:
    """Truncate a string to fit inside a Discord embed field."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_embed(job: dict[str, Any]) -> dict[str, Any]:
    """
    Construct a Discord embed dict for a single job posting.

    Expected job keys (all optional except title/id):
        id, title, employer, location, pay, job_type, posted_date, apply_url
    """
    title = job.get("title", "Untitled Position")
    employer = job.get("employer", "N/A")
    location = job.get("location", "N/A")
    pay = job.get("pay", "Not listed")
    job_type = job.get("job_type", "N/A")
    posted_date = job.get("posted_date", "N/A")
    apply_url = job.get("apply_url", config.JOBS_URL)

    # Normalize list-like fields if they come in as objects
    if isinstance(job_type, dict):
        job_type = job_type.get("label", "N/A")
    if isinstance(employer, dict):
        employer = employer.get("label", "N/A")

    fields = [
        {"name": "🏢 Employer", "value": _truncate(str(employer)), "inline": True},
        {"name": "📍 Location", "value": _truncate(str(location)), "inline": True},
        {"name": "💵 Pay", "value": _truncate(str(pay)), "inline": True},
        {"name": "📋 Type", "value": _truncate(str(job_type)), "inline": True},
        {"name": "📅 Posted", "value": _truncate(str(posted_date)), "inline": True},
    ]

    embed = {
        "title": _truncate(title, 256),
        "url": apply_url,
        "description": f"🔗 **[Click here to view & apply on Symplicity]({apply_url})**",
        "color": EMBED_COLOR_NEW,
        "fields": fields,
        "footer": {
            "text": "Jobs for Aggies • Texas A&M University",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return embed


def send_discord_notification(jobs: list[dict[str, Any]]) -> None:
    """Send one or more job embeds to Discord, batching up to 10 per request."""
    if not DISCORD_WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping notification.")
        return
    if not jobs:
        return

    # Discord allows up to 10 embeds per webhook message
    batch_size = 10
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        embeds = [build_embed(job) for job in batch]
        payload = {
            "username": "Aggie Job Bot 🤖",
            "avatar_url": "https://brand.tamu.edu/logos/university-logos/png/primary/primary-aggie.png",
            "embeds": embeds,
        }
        try:
            resp = requests.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            log.info(
                "Discord notification sent (%d/%d jobs in batch).",
                min(i + batch_size, len(jobs)),
                len(jobs),
            )
            # Respect Discord rate limits: 30 reqs / minute per webhook
            time.sleep(2)
        except requests.RequestException as exc:
            log.error("Failed to send Discord notification: %s", exc)


def send_discord_info(message: str) -> None:
    """Send a simple info/status notice to Discord."""
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "username": "Aggie Job Bot 🤖",
        "avatar_url": "https://brand.tamu.edu/logos/university-logos/png/primary/primary-aggie.png",
        "embeds": [
            {
                "title": "✅ Bot Status",
                "description": message,
                "color": 0x500000, # TAMU Maroon color
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Discord status info sent.")
    except requests.RequestException as exc:
        log.error("Failed to send Discord info message: %s", exc)


def send_discord_error(message: str) -> None:
    """Send a simple error notice to Discord."""
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "username": "Aggie Job Bot 🤖",
        "embeds": [
            {
                "title": "⚠️ Scraper Error",
                "description": _truncate(message, 4096),
                "color": EMBED_COLOR_ERROR,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as exc:
        log.error("Could not send error notification to Discord: %s", exc)


# ===========================================================================
# Keyword filtering
# ===========================================================================

def matches_keywords(title: str, keywords: list[str], threshold: int = FUZZY_THRESHOLD) -> bool:
    """
    Return True if the title contains or fuzzy-matches any of the configured keywords.
    Uses rapidfuzz for fuzzy matching.
    """
    if not keywords:
        return True
    title_lower = title.lower()
    from rapidfuzz import fuzz
    for kw in keywords:
        kw_lower = kw.lower()
        # Direct substring check (fast and precise)
        if kw_lower in title_lower:
            return True
        # Fuzzy partial match check
        if fuzz.partial_ratio(kw_lower, title_lower) >= threshold:
            return True
    return False


def matches_location(job_location: str, target_locations: list[str], threshold: int = FUZZY_THRESHOLD) -> bool:
    """
    Return True if the job location contains or fuzzy-matches any of the target locations.
    Uses rapidfuzz for fuzzy matching.
    """
    if not target_locations:
        return True
    loc_lower = job_location.lower()
    from rapidfuzz import fuzz
    for target in target_locations:
        target_lower = target.lower()
        # Direct substring check
        if target_lower in loc_lower:
            return True
        # Fuzzy partial match check
        if fuzz.partial_ratio(target_lower, loc_lower) >= threshold:
            return True
    return False


def matches_academic_level(job: dict[str, Any], my_level: str) -> bool:
    """
    Return True if the job description, title, and metadata match the target academic level.
    Supports undergrad, masters, and phd constraints.
    """
    my_level = my_level.lower().strip()
    if not my_level or my_level == "all":
        return True

    title = str(job.get("title", "")).lower()
    desc = str(job.get("description", "") or job.get("job_desc", "")).lower()
    
    # Remove HTML tags to avoid matching attributes or raw HTML tags
    desc_text = re.sub(r"<[^>]+>", " ", desc)
    combined_text = f"{title} {desc_text}"

    # Extract class/level metadata labels if present
    class_levels = job.get("classLevel", [])
    class_labels = []
    if isinstance(class_levels, list):
        for cl in class_levels:
            if isinstance(cl, dict):
                class_labels.append(cl.get("label", "").lower())
            else:
                class_labels.append(str(cl).lower())
    class_text = " ".join(class_labels)

    # Keywords lists
    undergrad_kws = {"undergrad", "undergraduate", "bachelor", "bs", "ba", "freshman", "sophomore", "junior", "senior"}
    masters_kws = {"master", "ms", "mba", "graduate assistant", "graduate student"}
    phd_kws = {"phd", "ph.d", "doctorate", "doctoral", "postdoc", "postdoctoral"}

    has_undergrad = any(kw in combined_text for kw in undergrad_kws) or any(kw in class_text for kw in {"sophomore", "junior", "senior", "freshman"})
    has_masters = any(kw in combined_text for kw in masters_kws) or "master" in class_text
    has_phd = any(kw in combined_text for kw in phd_kws) or "phd" in class_text or "doctorate" in class_text

    # Match classLevel metadata if available
    if class_labels:
        is_undergrad_meta = any(any(kw in lbl for kw in {"freshman", "sophomore", "junior", "senior", "undergraduate"}) for lbl in class_labels)
        is_masters_meta = any("master" in lbl or "graduate" in lbl for lbl in class_labels)
        is_phd_meta = any("phd" in lbl or "doctorate" in lbl for lbl in class_labels)

        if my_level == "undergraduate":
            if is_undergrad_meta:
                return True
            if (is_masters_meta or is_phd_meta) and not is_undergrad_meta:
                return False
        elif my_level == "masters":
            if is_masters_meta:
                return True
            if not is_masters_meta:
                return False
        elif my_level == "phd":
            if is_phd_meta:
                return True
            if not is_phd_meta:
                return False

    # Text-based fallback heuristic checks
    if my_level == "undergraduate":
        if (has_phd or has_masters) and not has_undergrad:
            phd_required = any(x in combined_text for x in ("phd required", "ph.d. required", "graduate student required", "doctoral candidate"))
            masters_required = any(x in combined_text for x in ("masters required", "master's required", "mba required"))
            if phd_required or masters_required or (has_phd and not has_undergrad):
                return False
    elif my_level == "masters":
        if has_phd and not has_masters and not has_undergrad:
            return False
    elif my_level == "phd":
        if not has_phd and not has_masters:
            return False

    return True


# ===========================================================================
# Job data extraction helpers
# ===========================================================================

def _extract_jobs_from_api_response(body: bytes) -> list[dict[str, Any]]:
    """
    Parse jobs from the Symplicity internal API JSON response.
    Supports both API v1 (data-keyed list) and v2 (models-keyed list).
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        log.debug("API body is not JSON: %s", exc)
        return []

    records = []
    
    # Locate list of items in the response
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            items = data["data"]
        elif "models" in data and isinstance(data["models"], list):
            items = data["models"]
        elif "data" in data and isinstance(data["data"], dict):
            items = [data["data"]]

    for item in items:
        if not isinstance(item, dict):
            continue

        # Extract Job ID
        job_id = str(
            item.get("id")
            or item.get("systemId")
            or item.get("visual_id")
            or item.get("job_id")
            or ""
        )
        if not job_id:
            continue

        # Extract Title
        title = str(
            item.get("job_title")
            or item.get("label")
            or item.get("title")
            or item.get("positionTitle")
            or "Untitled"
        )

        # Extract Employer
        employer = "N/A"
        if "name" in item:
            employer = item["name"]
        elif "employerName" in item:
            employer = item["employerName"]
        elif "employer" in item:
            emp_val = item["employer"]
            if isinstance(emp_val, dict):
                employer = emp_val.get("label") or emp_val.get("name") or "N/A"
            else:
                employer = str(emp_val)

        # Extract Location
        location = "N/A"
        if "job_location" in item:
            location = item["job_location"]
        elif "location" in item:
            loc_val = item["location"]
            if isinstance(loc_val, dict):
                location = loc_val.get("label") or "N/A"
            else:
                location = str(loc_val)
        elif "locations" in item and isinstance(item["locations"], list) and item["locations"]:
            location = item["locations"][0].get("label") or "N/A"

        # Extract Pay
        pay = str(
            item.get("salaryRange")
            or item.get("hourlyRate")
            or item.get("salary")
            or item.get("compensation")
            or "Not listed"
        )
        if pay == "Not listed" and item.get("compensation_from"):
            pay = f"${item.get('compensation_from')}"
            if item.get("compensation_to"):
                pay += f" - ${item.get('compensation_to')}"
            if item.get("compensation_frequency"):
                freq = item.get("compensation_frequency")
                pay += f" / {freq.get('label') if isinstance(freq, dict) else freq}"

        # Extract Job Type
        jt_val = item.get("job_type") or item.get("jobType") or item.get("type") or "N/A"
        if isinstance(jt_val, list):
            job_type = ", ".join(str(x) for x in jt_val)
        elif isinstance(jt_val, dict):
            job_type = jt_val.get("label") or jt_val.get("name") or "N/A"
        else:
            job_type = str(jt_val)

        # Extract Posted Date
        posted_date = str(
            item.get("postdate")
            or item.get("postedDate")
            or item.get("createdAt")
            or "N/A"
        )

        apply_url = f"{config.BASE_URL}/students/app/jobs/search?currentJobId={job_id}"

        records.append(
            {
                "id": job_id,
                "title": title,
                "employer": employer,
                "location": location,
                "pay": pay,
                "job_type": job_type,
                "posted_date": posted_date,
                "apply_url": apply_url,
                "description": item.get("description") or item.get("job_desc") or "",
                "classLevel": item.get("classLevel") or [],
            }
        )

    return records


def _extract_jobs_from_dom(page: Page) -> list[dict[str, Any]]:
    """
    Fallback DOM scraper. Tries to read job cards rendered in the SPA.
    This is a best-effort approach and may need adjustment if Symplicity
    changes its front-end markup.
    """
    log.info("Falling back to DOM extraction.")
    records: list[dict[str, Any]] = []

    # Wait for at least one job card to appear
    try:
        page.wait_for_selector("[data-automation='jobResult'], .listingContainer, .job-listing", timeout=15_000)
    except PlaywrightTimeoutError:
        log.warning("DOM fallback: no job card selectors found on page.")
        return records

    # Try multiple selectors used across Symplicity versions
    card_handles = page.query_selector_all(
        "[data-automation='jobResult'], .card-job, .listing-item, li.jobs-list__item"
    )
    log.info("DOM fallback found %d candidate cards.", len(card_handles))

    for card in card_handles:
        try:
            # Extract job ID from a data attribute or the link href
            job_id = card.get_attribute("data-id") or card.get_attribute("data-job-id") or ""

            if not job_id:
                continue

            apply_url = f"{config.BASE_URL}/students/app/jobs/search?currentJobId={job_id}"

            title_el = card.query_selector(
                "[data-automation='jobTitle'], .job-title, h2, h3, .title"
            )
            title = title_el.inner_text().strip() if title_el else "Untitled"

            employer_el = card.query_selector(
                "[data-automation='employer'], .employer-name, .company"
            )
            employer = employer_el.inner_text().strip() if employer_el else "N/A"

            location_el = card.query_selector(
                "[data-automation='location'], .location, .job-location"
            )
            location = location_el.inner_text().strip() if location_el else "N/A"

            pay_el = card.query_selector(".salary, .pay, [data-automation='salary']")
            pay = pay_el.inner_text().strip() if pay_el else "Not listed"

            records.append(
                {
                    "id": job_id,
                    "title": title,
                    "employer": employer,
                    "location": location,
                    "pay": pay,
                    "job_type": "N/A",
                    "posted_date": "N/A",
                    "apply_url": apply_url,
                }
            )
        except Exception as exc:
            log.debug("Error parsing DOM card: %s", exc)
            continue

    return records


# ===========================================================================
# Authentication
# ===========================================================================

def login_tamu_sso(page: Page, debug: bool = False) -> None:
    """
    Perform a full TAMU SSO login via the CAS / Duo flow.

    Steps:
      1. Navigate to the Symplicity job board (triggers a redirect to CAS).
      2. Fill in NetID and password on the CAS login form.
         NOTE: TAMU CAS renders #username as a hidden <input> initially
         (it has CSS display:none until the JS framework finishes).  We
         therefore wait for the element to be *attached* to the DOM
         (state='attached') rather than visible, then use force=True to
         fill it regardless of CSS visibility.
      3. Wait for Duo two-factor authentication (manual step by user).
      4. Wait until redirected back to Symplicity.
    """
    if not TAMU_USERNAME or not TAMU_PASSWORD:
        raise EnvironmentError(
            "TAMU_USERNAME and TAMU_PASSWORD must be set in your .env file."
        )

    log.info("Starting TAMU SSO login flow …")
    page.goto(config.JOBS_URL, timeout=config.NAVIGATION_TIMEOUT)

    # ------------------------------------------------------------------ CAS
    # Wait for the username field to exist in the DOM (may still be hidden)
    username_found = False
    for selector in ("#username", "input[name='username']", "input[type='text'][name*='user']"):
        try:
            page.wait_for_selector(selector, state="attached", timeout=12_000)
            username_found = True
            log.info("CAS username field found with selector: %s", selector)
            # Use force=True to bypass CSS visibility checks
            page.locator(selector).first.fill(TAMU_USERNAME, force=True)
            break
        except PlaywrightTimeoutError:
            continue

    if not username_found:
        current_url = page.url
        log.warning(
            "CAS login form not found (current URL: %s) — may already be authenticated.",
            current_url,
        )
        if debug:
            page.screenshot(path="debug_no_cas_form.png")
            log.info("Debug screenshot saved: debug_no_cas_form.png")
        return

    # Fill password — it is usually visible but use force=True for safety
    for sel in ("#password", "input[name='password']", "input[type='password']"):
        try:
            page.locator(sel).first.fill(TAMU_PASSWORD, force=True)
            log.info("Password filled.")
            break
        except Exception:
            continue

    if debug:
        page.screenshot(path="debug_before_submit.png")
        log.info("Debug screenshot saved: debug_before_submit.png")

    # Submit the form
    submitted = False
    for submit_sel in (
        "input[type='submit']",
        "button[type='submit']",
        "button:has-text('Login')",
        "button:has-text('Sign In')",
        "#submit",
    ):
        try:
            btn = page.locator(submit_sel).first
            if btn.count() > 0:
                btn.click(force=True)
                submitted = True
                log.info("CAS credentials submitted via: %s", submit_sel)
                break
        except Exception:
            continue

    if not submitted:
        log.error("Could not locate a submit button — trying Enter key on username field.")
        page.keyboard.press("Enter")

    # ------------------------------------------------------------------ Duo
    # Duo requires user interaction (push notification / TOTP).
    # In headless mode the user won't see the window, so we temporarily
    # expose a headed window for auth and then save state.
    try:
        # Duo may be inside a regular iframe or a new Duo Universal Prompt page
        page.wait_for_selector(
            "iframe[id*='duo'], #duo_iframe, #duo-frame, [data-testid='duo-iframe']",
            timeout=12_000,
        )
        log.info(
            "\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║  DUO 2FA REQUIRED — approve the push on your phone now  ║\n"
            "║  Waiting up to 120 seconds …                            ║\n"
            "╚══════════════════════════════════════════════════════════╝"
        )
        if debug:
            page.screenshot(path="debug_duo_prompt.png")
        # Wait until the Duo iframe disappears (auth complete)
        page.wait_for_selector(
            "iframe[id*='duo'], #duo_iframe, #duo-frame, [data-testid='duo-iframe']",
            state="hidden",
            timeout=120_000,
        )
        log.info("Duo 2FA completed.")
    except PlaywrightTimeoutError:
        # Duo Universal Prompt redirects to a separate page — check URL
        if "duosecurity.com" in page.url or "duouniversalprompt" in page.url:
            log.info(
                "\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  DUO UNIVERSAL PROMPT — approve the push, then wait …   ║\n"
                "║  Waiting up to 120 seconds for redirect back to TAMU …  ║\n"
                "╚══════════════════════════════════════════════════════════╝"
            )
            try:
                page.wait_for_url(f"{config.BASE_URL}/**", timeout=120_000)
            except PlaywrightTimeoutError:
                log.warning("Still not on Symplicity after Duo wait. URL: %s", page.url)
        else:
            log.info("No Duo prompt detected — assuming single-factor or already past Duo.")

    # Wait for redirect back to Symplicity
    if config.BASE_URL not in page.url:
        try:
            page.wait_for_url(f"{config.BASE_URL}/**", timeout=30_000)
            log.info("Successfully redirected to Symplicity — login complete.")
        except PlaywrightTimeoutError:
            log.warning(
                "Timed out waiting for post-SSO redirect; current URL: %s",
                page.url,
            )
            if debug:
                page.screenshot(path="debug_post_login.png")
    else:
        log.info("Already on Symplicity — login complete. URL: %s", page.url)


def load_or_create_context(
    playwright: Playwright,
    force_login: bool = False,
    debug: bool = False,
) -> tuple[Browser, BrowserContext]:
    """
    Return a (browser, context) pair.

    If session_state.json exists and force_login is False, restore that
    session (cookies + localStorage).  Otherwise do a fresh login and
    save the resulting session state.

    Login always opens a HEADED (visible) browser so the user can approve
    Duo 2FA.  After saving the session the browser is restarted in headless
    mode if HEADLESS=true.
    """
    session_path = Path(config.SESSION_FILE)

    if not force_login and session_path.exists():
        log.info("Loading saved session from %s", session_path)
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(storage_state=str(session_path))
        return browser, context

    # No saved session — always launch headed so the user can interact with Duo
    log.info("No saved session — launching HEADED browser for initial login.")
    browser = playwright.chromium.launch(
        headless=False,
        # Slow down interactions slightly so Chromium renders before we fill fields
        slow_mo=80,
    )
    context = browser.new_context(
        # Use a real-looking viewport and user-agent to avoid bot detection
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        login_tamu_sso(page, debug=debug)
    except Exception as exc:
        log.error("Login failed: %s", exc)
        if debug:
            try:
                page.screenshot(path="debug_login_error.png")
            except Exception:
                pass
        browser.close()
        raise

    # Wait until we are actually inside the authenticated app before saving session.
    # The login flow sometimes lands on /students/?signin_tab=0 (Symplicity's own
    # sign-in page) before the full redirect completes — saving there produces an
    # unauthenticated cookie jar.  Wait up to 30 s for /students/app to appear.
    log.info("Waiting for authenticated app redirect before saving session …")
    try:
        page.wait_for_url(f"{config.BASE_URL}/students/app/**", timeout=30_000)
        log.info("Confirmed authenticated app URL: %s", page.url)
    except PlaywrightTimeoutError:
        log.warning(
            "Did not reach /students/app in time (current URL: %s). "
            "Session may be incomplete — you may need to run --login again.",
            page.url,
        )

    # Save session state for future headless runs
    context.storage_state(path=str(session_path))
    log.info("Session saved to %s", session_path)
    page.close()

    # If running headless normally, restart in headless mode now
    if HEADLESS:
        log.info("Restarting in headless mode for scraping …")
        context.close()
        browser.close()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(session_path))

    return browser, context


# ===========================================================================
# Core scraping logic
# ===========================================================================

# API URL fragments that Symplicity uses for its job-list XHR calls.
_API_URL_FRAGMENTS: tuple[str, ...] = (
    "/api/v1/jobs",
    "/api/v2/jobs",
    "/api/jobs",
    "/csm/api/jobs",
    "/api/v1/positions",
    "/api/v2/positions",
    "/api/positions",
    "/csm/api/positions",
)


def build_search_url(base_url: str, keyword: str) -> str:
    """
    Build the search URL by appending keywords and any active filters from config.FILTERS.
    """
    params = []
    if keyword:
        params.append(f"keywords={quote(keyword)}")
        
    filters = getattr(config, "FILTERS", {})
    for key, val in filters.items():
        if not val:
            continue
        if isinstance(val, list):
            for item in val:
                params.append(f"{key}[]={quote(str(item))}")
        else:
            params.append(f"{key}={quote(str(val))}")
            
    query_string = "&".join(params)
    return f"{base_url}?{query_string}" if query_string else base_url


def scrape_jobs(context: BrowserContext, keywords: list[str], debug: bool = False) -> list[dict[str, Any]]:
    """
    Open the Symplicity job board and collect all job postings.

    Strategy:
      - Intercept every XHR/fetch response that looks like a Symplicity
        jobs API call (multiple URL fragment candidates).
      - For each intercepted JSON response, parse job records.
      - Query each keyword individually in the URL to narrow down results.
      - Navigate through up to MAX_PAGES pages for each keyword.
      - Fall back to DOM parsing if no API responses are captured.
    """
    page = context.new_page()
    all_jobs: list[dict[str, Any]] = []
    intercepted_bodies: list[bytes] = []

    def _handle_response(response: Response) -> None:
        url = response.url
        # Only consider successful responses from job list APIs, excluding configs/searches
        if response.status != 200:
            return
        content_type = response.headers.get("content-type", "")
        is_json = "json" in content_type or "javascript" in content_type
        url_matches = any(frag in url for frag in _API_URL_FRAGMENTS)
        is_exclude = any(x in url for x in ("/search/recent", "/auth/", "/config", "/translation", "/autocomplete"))
        
        if url_matches and is_json and not is_exclude:
            try:
                body = response.body()
                stripped = body.lstrip()
                if stripped and stripped[0:1] in (b"{", b"["):
                    intercepted_bodies.append(body)
                    log.debug(
                        "Intercepted candidate response: %s (%d bytes)", url, len(body)
                    )
            except Exception as exc:
                log.debug("Could not read response body for %s: %s", url, exc)

    page.on("response", _handle_response)

    search_keywords = keywords if keywords else [""]
    first_nav = True

    for kw in search_keywords:
        target_url = build_search_url(config.JOBS_URL, kw)
        log.info("Searching for keyword '%s' -> Navigating to: %s", kw, target_url)

        try:
            page.goto(target_url, timeout=config.NAVIGATION_TIMEOUT)
            page.wait_for_load_state("networkidle", timeout=config.NETWORK_IDLE_TIMEOUT)
        except PlaywrightTimeoutError:
            log.warning("Network idle timeout during navigation — proceeding anyway.")

        if first_nav:
            if debug:
                page.screenshot(path="debug_after_nav.png")
                log.info("Debug screenshot: debug_after_nav.png  (URL: %s)", page.url)

            # Detect session expiry — we should NOT be on the CAS or any login page, and we MUST be inside the app
            current_url = page.url
            on_symplicity = config.BASE_URL.replace("https://", "") in current_url
            on_cas = any(x in current_url for x in ("cas.tamu.edu", "sso.tamu.edu", "login", "signin"))
            on_app = "/students/app" in current_url
            if on_cas or not on_symplicity or not on_app:
                log.warning("Session appears expired (redirected to: %s).", current_url)
                page.close()
                raise SessionExpiredError("Symplicity session is expired — re-run with --login.")

            log.info("Landed on: %s", current_url)
            first_nav = False

        # Wait a brief moment for the page search XHR/fetch queries to fire and finish
        page.wait_for_timeout(3000)

        # Paginate for this specific keyword (MAX_PAGES per keyword)
        for page_num in range(MAX_PAGES):
            if page_num > 0:
                log.info("Scraping page %d of %d for keyword '%s' …", page_num + 1, MAX_PAGES, kw)

            # Parse any newly intercepted API responses
            fresh_from_api = 0
            for body in intercepted_bodies:
                jobs = _extract_jobs_from_api_response(body)
                if jobs:
                    log.info("Extracted %d jobs from an API response.", len(jobs))
                    all_jobs.extend(jobs)
                    fresh_from_api += len(jobs)
            if fresh_from_api == 0 and intercepted_bodies:
                log.debug(
                    "Intercepted %d response(s) but none yielded job records.",
                    len(intercepted_bodies),
                )
            intercepted_bodies.clear()

            # Attempt to click the "Next page" control
            if page_num < MAX_PAGES - 1:
                next_clicked = _click_next_page(page)
                if not next_clicked:
                    break
                # Wait for the SPA to re-render
                try:
                    page.wait_for_load_state("networkidle", timeout=config.NETWORK_IDLE_TIMEOUT)
                    page.wait_for_timeout(2000)
                except PlaywrightTimeoutError:
                    pass
            else:
                break

    # If API interception yielded nothing, fall back to DOM
    if not all_jobs:
        log.warning("API interception captured 0 jobs — attempting DOM fallback on last loaded page.")
        if debug:
            page.screenshot(path="debug_before_dom_fallback.png")
            log.info("Debug screenshot: debug_before_dom_fallback.png")
        all_jobs = _extract_jobs_from_dom(page)

    page.close()

    # Deduplicate by id (pages can overlap)
    seen_ids: set[str] = set()
    unique_jobs: list[dict[str, Any]] = []
    for job in all_jobs:
        if job["id"] not in seen_ids:
            seen_ids.add(job["id"])
            unique_jobs.append(job)

    log.info("Total unique jobs scraped: %d", len(unique_jobs))
    return unique_jobs


def _click_next_page(page: Page) -> bool:
    """
    Try common Symplicity 'next page' selectors.
    Returns True if a button was found and clicked.
    """
    selectors = [
        "button[aria-label='Next page']",
        "button[aria-label='next page']",
        "a[aria-label='Next page']",
        "[data-automation='paginationNextButton']",
        ".pagination__next:not([disabled])",
        "li.next:not(.disabled) a",
        "button.next-page:not([disabled])",
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                log.debug("Clicked next-page with selector: %s", sel)
                return True
        except Exception:
            continue
    return False


# ===========================================================================
# Custom exceptions
# ===========================================================================

class SessionExpiredError(Exception):
    """Raised when Playwright detects the saved session is no longer valid."""


# ===========================================================================
# Main pipeline
# ===========================================================================

def _execute_pipeline(state: StateManager, keywords: list[str], force_login: bool, debug: bool, is_first_run: bool = False) -> None:
    """Run a single execution loop of the scraper pipeline."""
    with sync_playwright() as playwright:
        browser: Browser | None = None
        try:
            browser, context = load_or_create_context(
                playwright, force_login=force_login, debug=debug
            )
        except SessionExpiredError:
            log.info("Session expired — retrying with fresh login.")
            Path(config.SESSION_FILE).unlink(missing_ok=True)
            browser, context = load_or_create_context(playwright, force_login=True, debug=debug)
        except Exception as exc:
            log.error("Could not create browser context: %s", exc)
            send_discord_error(f"Scraper startup error: {exc}")
            return

        try:
            jobs = scrape_jobs(context, keywords=keywords, debug=debug)
        except SessionExpiredError:
            log.info("Session expired during scrape — retrying with fresh login.")
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            Path(config.SESSION_FILE).unlink(missing_ok=True)
            browser, context = load_or_create_context(playwright, force_login=True, debug=debug)
            jobs = scrape_jobs(context, keywords=keywords, debug=debug)
        except Exception as exc:
            log.error("Scraping failed: %s", exc, exc_info=True)
            send_discord_error(f"Scraping error: {exc}")
            try:
                context.close()
            except Exception:
                pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            return
        else:
            try:
                context.close()
            except Exception:
                pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    # 1. Apply keyword filter
    if keywords:
        filtered_by_kw = [j for j in jobs if matches_keywords(j["title"], keywords)]
        log.info(
            "After keyword filter (%s): %d / %d jobs match.",
            ", ".join(keywords[:5]) + ("…" if len(keywords) > 5 else ""),
            len(filtered_by_kw),
            len(jobs),
        )
    else:
        filtered_by_kw = jobs
        log.info("No keyword filter applied — processing all %d jobs.", len(filtered_by_kw))

    # 2. Apply location filter
    if LOCATION_FILTER:
        filtered_by_location = [j for j in filtered_by_kw if matches_location(j["location"], LOCATION_FILTER)]
        log.info(
            "After location filter (%s): %d / %d jobs match.",
            ", ".join(LOCATION_FILTER),
            len(filtered_by_location),
            len(filtered_by_kw),
        )
    else:
        filtered_by_location = filtered_by_kw

    # 3. Apply academic level filter
    if MY_ACADEMIC_LEVEL and MY_ACADEMIC_LEVEL != "all":
        filtered = [j for j in filtered_by_location if matches_academic_level(j, MY_ACADEMIC_LEVEL)]
        log.info(
            "After academic level filter (%s): %d / %d jobs match.",
            MY_ACADEMIC_LEVEL,
            len(filtered),
            len(filtered_by_location),
        )
    else:
        filtered = filtered_by_location

    # ------------------------------------------------------------------ New jobs
    new_jobs: list[dict[str, Any]] = []
    for job in filtered:
        if state.is_new(job["id"]):
            new_jobs.append(job)
            state.mark_seen(job["id"])

    log.info("%d new job(s) to notify about.", len(new_jobs))

    if is_first_run:
        # On the first run, we treat all currently matching jobs as "old jobs"
        # and seed the seen list, but we do NOT send them to Discord.
        # Instead, we send a startup confirmation message.
        log.info("First run: Seeded %d jobs as 'old jobs'. Sending startup message to Discord.", len(new_jobs))
        send_discord_info(
            f"the script is working! you will be notified if any new jobs are published in {RUN_INTERVAL_MINS} minutes"
        )
    else:
        if new_jobs:
            send_discord_notification(new_jobs)
        else:
            log.info("No new matching jobs found — nothing sent to Discord.")

    state.save()
    log.info("Pipeline complete.")


def run(force_login: bool = False, no_filter: bool = False, debug: bool = False, continuous: bool = False) -> None:
    reload_config()
    state = StateManager()
    keywords = [] if no_filter else config.KEYWORDS

    if not continuous:
        _execute_pipeline(state, keywords, force_login=force_login, debug=debug, is_first_run=False)
        return

    log.info("Starting continuous daemon mode (running every %d minutes)...", RUN_INTERVAL_MINS)
    first_run = True
    while not stop_event.is_set():
        reload_config()  # refresh config dynamically inside loop
        try:
            loop_force_login = force_login if first_run else False
            
            _execute_pipeline(state, keywords, loop_force_login, debug, is_first_run=first_run)
            first_run = False
        except Exception as exc:
            log.error("Unhandled error in pipeline loop: %s", exc)
            send_discord_error(f"Continuous mode pipeline execution failed: {exc}")
            
        log.info("Sleeping for %d minutes before next check...", RUN_INTERVAL_MINS)
        
        # Use event wait instead of sleep so the GUI can interrupt it
        if stop_event.wait(RUN_INTERVAL_MINS * 60):
            log.info("Stop event received, terminating continuous loop.")
            break


# ===========================================================================
# CLI entry point
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Texas A&M Symplicity Job Board Notifier",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Force a fresh interactive login (deletes saved session).",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable keyword filtering and process ALL job postings.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save screenshots at key steps (debug_*.png) for troubleshooting.",
    )
    parser.add_argument(
        "--continuous", "-c",
        action="store_true",
        help="Run continuously in a loop (24/7 daemon mode).",
    )
    args = parser.parse_args()

    if args.login:
        Path(config.SESSION_FILE).unlink(missing_ok=True)
        log.info("Deleted saved session — will perform fresh login.")

    run(
        force_login=args.login,
        no_filter=args.no_filter,
        debug=args.debug,
        continuous=args.continuous,
    )


if __name__ == "__main__":
    main()
