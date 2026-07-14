"""
gui.py — Jobs for Aggies Notifier Desktop App
==============================================
Dark-mode customtkinter GUI with Aggie Maroon theme.
- Left panel: centered scrollable settings
- Right panel: logs + controls
- Auto-installs Playwright browsers on startup
"""

import os
import subprocess
import sys
import threading
import logging
import customtkinter as ctk
from dotenv import load_dotenv, set_key

# Force Playwright to use a persistent user AppData directory rather than the temp folder
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    _local_appdata = os.environ.get("LOCALAPPDATA")
    if _local_appdata:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_appdata, "ms-playwright")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# When running as a PyInstaller bundle the .env lives next to the .exe
if getattr(sys, "frozen", False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

ENV_FILE = os.path.join(_base_dir, ".env")
if not os.path.exists(ENV_FILE):
    open(ENV_FILE, "w").close()

# ---------------------------------------------------------------------------
# Colour palette (Aggie Maroon)
# ---------------------------------------------------------------------------
MAROON       = "#500000"
MAROON_HOVER = "#3a0000"
MAROON_LIGHT = "#7a1f1f"
SURFACE      = "#1a1a1a"
SURFACE2     = "#242424"
TEXT_DIM     = "#888888"

# ---------------------------------------------------------------------------
# Option mappings (filter label → API value)
# ---------------------------------------------------------------------------
REMOTE_OPTIONS   = {"On-site": "onsite", "Hybrid": "hybrid", "Remote": "remote"}
JOB_TYPE_OPTIONS = {"Part Time Student": "18", "Full Time": "3", "Internship": "5", "Co-op": "10"}
JOB_CAT_OPTIONS  = {
    "Work Study Eligible": "3", "Work Study Not Required": "4",
    "Work Study Required": "1", "Work Study Preferred": "2", "Grad Assistantship": "5",
}
TAMU_LOC_OPTIONS = {
    "On-Campus": "1", "Off-Campus": "2",
    "Off-Campus (TAMU Payroll)": "3", "On-Campus (Non-TAMU Payroll)": "4",
    "Outside B/CS (Summer Only)": "5",
}
WORK_AUTH_OPTIONS = {"US Citizen/National": "1", "Legally Auth to Work": "2", "Requires Visa": "22"}
SCHOOL_OPTIONS   = {"Any Campus": "", "College Station": "0010", "Galveston": "0020"}
POSTDATE_OPTIONS = {"Any Time": "", "Past 24 Hours": "1", "Past Week": "7", "Past Month": "30"}
ACADEMIC_OPTIONS = ["All", "Undergraduate", "Masters", "PhD"]


# ---------------------------------------------------------------------------
# Logging handler that routes records to the GUI textbox
# ---------------------------------------------------------------------------
class TextBoxLogHandler(logging.Handler):
    def __init__(self, text_widget: ctk.CTkTextbox):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", msg + "\n")
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Aggie Job Notifier")
        self.geometry("1000x720")
        self.minsize(850, 600)

        # Set window / taskbar icon
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            icon_path = os.path.join(_base_dir, "icon.ico")

        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        load_dotenv(ENV_FILE, override=True)
        self.scraper_thread: threading.Thread | None = None

        # Root grid: left panel | right panel
        self.grid_columnconfigure(0, weight=0)   # sidebar — fixed width
        self.grid_columnconfigure(1, weight=1)   # main — expands
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_panel()
        self._setup_logging()

        # Auto-install playwright on startup (non-blocking)
        threading.Thread(target=self._auto_install_playwright, daemon=True).start()

    # ------------------------------------------------------------------
    # Sidebar (centered, scrollable)
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        # Outer frame for centering
        outer = ctk.CTkFrame(self, fg_color=SURFACE, width=320, corner_radius=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_propagate(False)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(outer, fg_color=MAROON, corner_radius=0, height=70)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        ctk.CTkLabel(
            hdr, text="⚙️  Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="white"
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Scrollable body
        self.sidebar = ctk.CTkScrollableFrame(outer, fg_color=SURFACE2, corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # ---- Credentials ----
        self._section("🔑  Credentials")
        self.username_entry  = self._entry("TAMU NetID",           "TAMU_USERNAME")
        self.password_entry  = self._entry("TAMU Password",         "TAMU_PASSWORD",  show="*")
        self.webhook_entry   = self._entry("Discord Webhook URL",   "DISCORD_WEBHOOK_URL")

        # ---- Scraper Settings ----
        self._section("🤖  Scraper Settings")
        self.interval_entry  = self._entry("Run Interval (seconds)", "RUN_INTERVAL_SECS", default="3600")
        self.keywords_entry  = self._entry(
            "Title Keywords (comma-separated)", "KEYWORDS",
            default="Developer,Software,IT Support,Grader,Research,Data,Engineer,Analyst,Tutor,Assistant,Intern"
        )
        self.location_entry  = self._entry("Location Filter (comma-separated)", "LOCATION_FILTER")

        ctk.CTkLabel(self.sidebar, text="Academic Level:", anchor="w",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=24, pady=(8, 2))
        self.academic_menu = ctk.CTkOptionMenu(
            self.sidebar, values=ACADEMIC_OPTIONS,
            fg_color=SURFACE, button_color=MAROON, button_hover_color=MAROON_HOVER,
            dropdown_fg_color=SURFACE2
        )
        self.academic_menu.pack(fill="x", padx=24, pady=(0, 10))
        saved_lvl = os.getenv("MY_ACADEMIC_LEVEL", "all").title()
        self.academic_menu.set("PhD" if saved_lvl == "Phd" else saved_lvl)

        # ---- Advanced Search Filters ----
        self._section("🔍  Advanced Search Filters")

        ctk.CTkLabel(self.sidebar, text="School Campus:", anchor="w",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=24, pady=(8, 2))
        self.school_menu = ctk.CTkOptionMenu(
            self.sidebar, values=list(SCHOOL_OPTIONS.keys()),
            fg_color=SURFACE, button_color=MAROON, button_hover_color=MAROON_HOVER,
            dropdown_fg_color=SURFACE2
        )
        self.school_menu.pack(fill="x", padx=24, pady=(0, 10))
        self._set_menu_by_value(self.school_menu, SCHOOL_OPTIONS, os.getenv("FILTER_SCHOOL", ""))

        ctk.CTkLabel(self.sidebar, text="Posted Date Range:", anchor="w",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=24, pady=(8, 2))
        self.postdate_menu = ctk.CTkOptionMenu(
            self.sidebar, values=list(POSTDATE_OPTIONS.keys()),
            fg_color=SURFACE, button_color=MAROON, button_hover_color=MAROON_HOVER,
            dropdown_fg_color=SURFACE2
        )
        self.postdate_menu.pack(fill="x", padx=24, pady=(0, 10))
        self._set_menu_by_value(self.postdate_menu, POSTDATE_OPTIONS, os.getenv("FILTER_POSTDATE", ""))

        self.remote_vars   = self._checkbox_group("Remote / On-site",    REMOTE_OPTIONS,   "FILTER_REMOTE_ONSITE")
        self.job_type_vars = self._checkbox_group("Job Type",             JOB_TYPE_OPTIONS, "FILTER_JOB_TYPE")
        self.job_cat_vars  = self._checkbox_group("Job Category",         JOB_CAT_OPTIONS,  "FILTER_JOB_CATEGORY")
        self.tamu_loc_vars = self._checkbox_group("TAMU Job Location",    TAMU_LOC_OPTIONS, "FILTER_TAMU_JOB_LOCATION")
        self.work_auth_vars = self._checkbox_group("Work Authorization",  WORK_AUTH_OPTIONS,"FILTER_WORK_AUTH")

        self.excl_applied_var    = ctk.BooleanVar(value=os.getenv("FILTER_EXCLUDE_APPLIED", "") == "1")
        self.excl_nationwide_var = ctk.BooleanVar(value=os.getenv("FILTER_EXCLUDE_NATIONWIDE", "") == "1")
        ctk.CTkCheckBox(
            self.sidebar, text="Exclude Jobs Already Applied To",
            variable=self.excl_applied_var,
            checkmark_color="white", fg_color=MAROON, hover_color=MAROON_LIGHT
        ).pack(anchor="w", padx=30, pady=4)
        ctk.CTkCheckBox(
            self.sidebar, text="Exclude Nationwide Listings",
            variable=self.excl_nationwide_var,
            checkmark_color="white", fg_color=MAROON, hover_color=MAROON_LIGHT
        ).pack(anchor="w", padx=30, pady=(4, 16))

        # ---- Save Button ----
        ctk.CTkButton(
            self.sidebar, text="💾  Save Settings",
            command=self.save_settings,
            fg_color=MAROON, hover_color=MAROON_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"), height=40, corner_radius=8
        ).pack(fill="x", padx=24, pady=(4, 24))

    # ------------------------------------------------------------------
    # Main right panel
    # ------------------------------------------------------------------
    def _build_main_panel(self):
        panel = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(panel, fg_color=MAROON, corner_radius=0, height=70)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            hdr, text="Aggie Job Notifier 🤘",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white"
        ).grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # Control buttons in header
        btn_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=16, pady=10)

        self.start_btn = ctk.CTkButton(
            btn_frame, text="▶  Start", command=self.start_scraper,
            fg_color="#2e7d32", hover_color="#1b5e20",
            font=ctk.CTkFont(weight="bold"), width=110, height=36, corner_radius=8
        )
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="⏹  Stop", command=self.stop_scraper,
            fg_color="#b71c1c", hover_color="#7f0000",
            font=ctk.CTkFont(weight="bold"), width=110, height=36, corner_radius=8,
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.login_btn = ctk.CTkButton(
            btn_frame, text="🔐  Force Login", command=self.force_login,
            fg_color=MAROON_LIGHT, hover_color=MAROON_HOVER,
            width=130, height=36, corner_radius=8
        )
        self.login_btn.pack(side="left")

        # Status bar
        self.status_var = ctk.StringVar(value="Status: Ready — click ▶ Start to begin.")
        status_bar = ctk.CTkFrame(panel, fg_color=SURFACE2, height=30, corner_radius=0)
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        ctk.CTkLabel(status_bar, textvariable=self.status_var,
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(side="left", padx=12)

        # Log textbox
        self.log_box = ctk.CTkTextbox(
            panel, state="disabled", font=ctk.CTkFont(family="Courier New", size=11),
            fg_color="#0e0e0e", text_color="#d4d4d4", corner_radius=0
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

    # ------------------------------------------------------------------
    # Sidebar UI helpers
    # ------------------------------------------------------------------
    def _section(self, title: str):
        ctk.CTkLabel(
            self.sidebar, text=title,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=MAROON_LIGHT, anchor="w"
        ).pack(fill="x", padx=16, pady=(18, 4))

    def _entry(self, label: str, env_key: str, default: str = "", show=None) -> ctk.CTkEntry:
        ctk.CTkLabel(self.sidebar, text=label + ":", anchor="w",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=24, pady=(6, 2))
        e = ctk.CTkEntry(self.sidebar, show=show,
                         fg_color=SURFACE, border_color=MAROON_LIGHT)
        e.pack(fill="x", padx=24, pady=(0, 8))
        e.insert(0, os.getenv(env_key, default))
        return e

    def _checkbox_group(self, label: str, options: dict, env_key: str) -> dict:
        ctk.CTkLabel(self.sidebar, text=label + ":", anchor="w",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=12)).pack(
            fill="x", padx=24, pady=(10, 4))
        saved = set(x.strip() for x in os.getenv(env_key, "").split(",") if x.strip())
        vars_map: dict[str, ctk.BooleanVar] = {}
        for name, val in options.items():
            v = ctk.BooleanVar(value=(val in saved))
            ctk.CTkCheckBox(
                self.sidebar, text=name, variable=v,
                checkmark_color="white", fg_color=MAROON, hover_color=MAROON_LIGHT
            ).pack(anchor="w", padx=36, pady=2)
            vars_map[val] = v
        return vars_map

    @staticmethod
    def _set_menu_by_value(menu: ctk.CTkOptionMenu, options: dict, saved_val: str):
        for name, val in options.items():
            if val == saved_val:
                menu.set(name)
                return

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _setup_logging(self):
        handler = TextBoxLogHandler(self.log_box)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))
        # Import lazily to avoid circular init
        import main as _main
        _main.log.addHandler(handler)
        _main.log.setLevel(logging.INFO)
        self._main = _main

    # ------------------------------------------------------------------
    # Playwright auto-install
    # ------------------------------------------------------------------
    def _auto_install_playwright(self):
        """Run `playwright install chromium` silently on startup."""
        try:
            self.log_box.after(0, self._set_status, "Checking Playwright browser installation…")
            if getattr(sys, "frozen", False):
                import playwright._impl._driver
                driver_executable, driver_cli = playwright._impl._driver.compute_driver_executable()
                cmd = [driver_executable, *driver_cli, "install", "chromium"]
            else:
                cmd = [sys.executable, "-m", "playwright", "install", "chromium"]

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=300,
                creationflags=creation_flags
            )
            if result.returncode == 0:
                self.log_box.after(0, self._set_status, "Status: Ready — click ▶ Start to begin.")
                self._main.log.info("Playwright browser check complete.")
            else:
                self._main.log.warning(
                    "Playwright install returned non-zero: %s", result.stderr.strip()
                )
        except Exception as exc:
            self._main.log.warning("Could not auto-install Playwright: %s", exc)

    # ------------------------------------------------------------------
    # Save settings
    # ------------------------------------------------------------------
    def save_settings(self):
        def _s(key, val): set_key(ENV_FILE, key, val)
        _s("TAMU_USERNAME",    self.username_entry.get())
        _s("TAMU_PASSWORD",    self.password_entry.get())
        _s("DISCORD_WEBHOOK_URL", self.webhook_entry.get())
        _s("KEYWORDS",         self.keywords_entry.get())
        _s("LOCATION_FILTER",  self.location_entry.get())
        _s("MY_ACADEMIC_LEVEL", self.academic_menu.get().lower())
        _s("RUN_INTERVAL_SECS", self.interval_entry.get())
        _s("FILTER_SCHOOL",    SCHOOL_OPTIONS[self.school_menu.get()])
        _s("FILTER_POSTDATE",  POSTDATE_OPTIONS[self.postdate_menu.get()])

        def checked(d: dict) -> str:
            return ",".join(v for v, var in d.items() if var.get())

        _s("FILTER_REMOTE_ONSITE",     checked(self.remote_vars))
        _s("FILTER_JOB_TYPE",          checked(self.job_type_vars))
        _s("FILTER_JOB_CATEGORY",      checked(self.job_cat_vars))
        _s("FILTER_TAMU_JOB_LOCATION", checked(self.tamu_loc_vars))
        _s("FILTER_WORK_AUTH",         checked(self.work_auth_vars))
        _s("FILTER_EXCLUDE_APPLIED",   "1" if self.excl_applied_var.get() else "")
        _s("FILTER_EXCLUDE_NATIONWIDE","1" if self.excl_nationwide_var.get() else "")

        self._main.log.info("✅ Settings saved to .env")

    # ------------------------------------------------------------------
    # Scraper controls
    # ------------------------------------------------------------------
    def _set_status(self, msg: str):
        self.status_var.set(msg)

    def _scraper_worker(self, force_login: bool = False):
        # Ensure playwright is installed before scraping
        self._auto_install_playwright()
        try:
            self._main.run(force_login=force_login, continuous=True)
        except Exception as exc:
            self._main.log.error("Scraper error: %s", exc)
        finally:
            self.after(0, self._on_stopped)

    def start_scraper(self):
        if self.scraper_thread and self.scraper_thread.is_alive():
            return
        self.save_settings()
        self._main.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.login_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status("Status: Scraper running…")
        self._main.log.info("▶ Starting scraper in continuous mode…")
        self.scraper_thread = threading.Thread(target=self._scraper_worker, daemon=True)
        self.scraper_thread.start()

    def stop_scraper(self):
        self._main.log.info("⏹ Stopping scraper (finishing current cycle)…")
        self._main.stop_event.set()
        self.stop_btn.configure(state="disabled")
        self._set_status("Status: Stopping…")

    def force_login(self):
        if self.scraper_thread and self.scraper_thread.is_alive():
            self._main.log.warning("Stop the scraper first before forcing a new login.")
            return
        self.save_settings()
        self._main.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.login_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status("Status: Logging in (check for browser window)…")
        self._main.log.info("🔐 Starting with FORCE LOGIN…")
        self.scraper_thread = threading.Thread(
            target=self._scraper_worker, kwargs={"force_login": True}, daemon=True
        )
        self.scraper_thread.start()

    def _on_stopped(self):
        self.start_btn.configure(state="normal")
        self.login_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_status("Status: Stopped. Click ▶ Start to run again.")
        self._main.log.info("Scraper stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = App()
    app.mainloop()
