"""
config.py — Central configuration for the Jobs-for-Aggies Notifier.

Edit KEYWORDS to match the roles you are interested in.
All matching is case-insensitive substring and fuzzy matching against the job title.
"""

# ---------------------------------------------------------------------------
# Title Keyword filters
# ---------------------------------------------------------------------------
# A new job is forwarded to Discord ONLY if its title contains at least one
# of these strings (fuzzy or substring matching). Set to [] to disable filtering.
KEYWORDS: list[str] = [
    "Developer",
    "Software",
    "IT Support",
    "Grader",
    "Research",
    "Data",
    "Engineer",
    "Analyst",
    "Tutor",
    "Assistant",
    "Intern",
]

# Fuzzy matching similarity threshold (0 to 100). Higher means stricter.
# Typical values are between 75 and 90.
FUZZY_THRESHOLD = 80

# ---------------------------------------------------------------------------
# Location Filter (client-side filtering)
# ---------------------------------------------------------------------------
# Keep only jobs whose location contains/fuzzy-matches one of these targets.
# Leave empty [] to skip location filtering.
# Set via .env (LOCATION_FILTER) or here. E.g. ["College Station", "Remote"]
LOCATION_FILTER: list[str] = []

# ---------------------------------------------------------------------------
# Academic Level Filter (client-side filtering)
# ---------------------------------------------------------------------------
# Options: "undergraduate", "masters", "phd", or "all" (no filtering).
# The script scans both job titles, descriptions, and classLevel metadata to
# filter out positions that do not match your target academic level.
MY_ACADEMIC_LEVEL = "undergraduate"

# ---------------------------------------------------------------------------
# Daemon / Loop interval (in seconds)
# ---------------------------------------------------------------------------
# Used when running the scraper continuously with the --continuous flag.
# Default: 3600 seconds (1 hour). Recommended: 1800 (30 mins) to 7200 (2 hours).
RUN_INTERVAL_SECS = 3600

# ---------------------------------------------------------------------------
# Symplicity API Search Filters (server-side filtering)
# ---------------------------------------------------------------------------
# Populate these lists with option IDs to query the job board directly.
# Leave list values empty [] to apply no filtering for that parameter.
# Option IDs and descriptions are listed in the comments below.
FILTERS: dict[str, list[str] | str] = {
    "symp_remote_onsite": [],  # Remote/On-Site
    "job_type": [],            # Position Type
    "job_category": [],        # Job Category (Work Study etc.)
    "tamu_job_location": [],   # On-Campus vs Off-Campus
    "position_category": [],   # Position Category
    "school": [],              # School Location
    "postdate": "",            # Posted Date range
    "work_authorization": [],  # Work Authorization status
    "exclude_applied_jobs": "", # Exclude Jobs I've Applied For ("1" = Yes)
    "nationwide_jobs": "",     # Exclude Nationwide Jobs ("1" = Yes)
}

"""
FILTER OPTIONS REFERENCE
========================

1. symp_remote_onsite (Remote/On-Site)
   - "onsite" : On-site
   - "hybrid" : Hybrid
   - "remote" : Remote

2. job_type (Position Type)
   - "18"     : Part Time Student Employment
   - "3"      : Full Time
   - "5"      : Internship
   - "10"     : Co-op

3. job_category (Job Category)
   - "3"      : Work Study Eligible
   - "4"      : Work Study Not Required
   - "1"      : Work Study Required
   - "2"      : Work Study Preferred
   - "5"      : Graduate Assistantship

4. tamu_job_location (Job Location)
   - "1"      : On-Campus
   - "2"      : Off-Campus
   - "3"      : Off-Campus (TAMU Payroll)
   - "4"      : On-Campus (Non-TAMU Payroll)
   - "5"      : Outside Bryan/College Station - Summer Only

5. school (School Campus)
   - "0010"   : College Station
   - "0020"   : Galveston

6. postdate (Posted Date Range)
   - ""       : Any time
   - "30"     : Past month
   - "7"      : Past week
   - "1"      : Past 24 hours

7. exclude_applied_jobs
   - "1"      : Yes (Exclude)
   - ""       : No

8. nationwide_jobs
   - "1"      : Yes (Exclude)
   - ""       : No

9. work_authorization
   - "1"      : US Citizen or US National
   - "2"      : Legally authorized to work in US (Permanent Resident, DACA etc.)
   - "22"     : Will require visa sponsorship

10. position_category
   - "27" : Accounting
   - "3"  : Agriculture
   - "2"  : Animal Care
   - "35" : Call Center
   - "1"  : Child Care
   - "28" : Cleaning Services
   - "20" : Clerical
   - "18" : Community Service
   - "31" : Community Service Program
   - "25" : Construction
   - "19" : Customer Service
   - "34" : Engineering
   - "17" : Food Services
   - "36" : Grader
   - "32" : Health Services
   - "29" : Household Services
   - "26" : Human Resources
   - "33" : IT Services
   - "16" : Laboratory Assistant
   - "30" : Lawn Care
   - "15" : Library
   - "14" : Marketing
   - "13" : Media & Computer
   - "12" : Miscellaneous
   - "23" : Office Assistant
   - "11" : One-Time/Immediate
   - "21" : Peer Counseling/Mentoring
   - "10" : Personal Care Attendant
   - "9"  : Reads & Counts Tutoring
   - "24" : Receptionist
   - "8"  : Research Assistant
   - "7"  : Retail/Sales
   - "4"  : Social Media
   - "6"  : Tutoring (K-12)
   - "5"  : Tutoring (University Level)
   - "22" : Youth Development
"""

# ---------------------------------------------------------------------------
# Symplicity target URL
# ---------------------------------------------------------------------------
BASE_URL = "https://jobsforaggies-tamu-csm.symplicity.com"
JOBS_URL = f"{BASE_URL}/students/app/jobs/search"

# The internal API endpoint the SPA calls (used for network interception).
API_JOBS_PATH = "/csm/api/v1/jobs"

# ---------------------------------------------------------------------------
# Local state & session files
# ---------------------------------------------------------------------------
STATE_FILE = "jobs_state.json"         # tracks seen job IDs
SESSION_FILE = "session_state.json"    # Playwright browser storage state

# ---------------------------------------------------------------------------
# Timeouts (milliseconds)
# ---------------------------------------------------------------------------
NAVIGATION_TIMEOUT = 60_000    # 60 s for full page loads
NETWORK_IDLE_TIMEOUT = 30_000  # 30 s wait-for-network-idle
API_INTERCEPT_TIMEOUT = 30_000 # 30 s to receive the intercepted API call

# ---------------------------------------------------------------------------
# Retry / pagination
# ---------------------------------------------------------------------------
MAX_RETRIES = 3          # attempts before giving up on a page
RESULTS_PER_PAGE = 25    # Symplicity default; change if you override in the URL
