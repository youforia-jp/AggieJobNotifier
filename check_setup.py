"""
check_setup.py — Pre-flight validation script.
Run this once after installing dependencies to confirm everything is wired up
correctly before your first real scrape.

  python check_setup.py
"""

import os
import sys
from pathlib import Path

# Force Playwright to use a persistent user AppData directory rather than the temp folder
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    _local_appdata = os.environ.get("LOCALAPPDATA")
    if _local_appdata:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_appdata, "ms-playwright")

# Fix console encoding on Windows to prevent UnicodeEncodeError
if sys.platform.startswith("win"):
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

print("\n=== Jobs-for-Aggies Notifier — Setup Check ===")

errors: list[str] = []
warnings: list[str] = []

# 1. Python version
major, minor = sys.version_info[:2]
if (major, minor) < (3, 10):
    errors.append(f"Python 3.10+ required — you have {major}.{minor}")
else:
    print(f" [OK] Python {major}.{minor}")

# 2. Dependencies importable
deps = {
    "playwright": "playwright",
    "dotenv": "python-dotenv",
    "requests": "requests",
    "rapidfuzz": "rapidfuzz",
}
for module, package in deps.items():
    try:
        __import__(module)
        print(f" [OK] {package}")
    except ImportError:
        errors.append(f"Missing package '{package}' — run: pip install {package}")

# 3. .env file
env_path = Path(".env")
if not env_path.exists():
    errors.append(".env file not found — copy .env.example to .env and fill it in")
else:
    print(" [OK] .env file present")
    from dotenv import load_dotenv
    load_dotenv()
    missing_vars = []
    for var in ("TAMU_USERNAME", "TAMU_PASSWORD", "DISCORD_WEBHOOK_URL"):
        if not os.getenv(var):
            missing_vars.append(var)
    if missing_vars:
        errors.append(f"Missing .env variables: {', '.join(missing_vars)}")
    else:
        print(" [OK] .env variables set (TAMU_USERNAME, TAMU_PASSWORD, DISCORD_WEBHOOK_URL)")

# 4. Playwright browsers installed
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "playwright", "install", "--dry-run"],
    capture_output=True, text=True
)
if "chromium" in result.stdout.lower() or result.returncode == 0:
    print(" [OK] Playwright Chromium browser available")
else:
    warnings.append("Playwright Chromium may not be installed — run: playwright install chromium")

# 5. config.py importable
try:
    import config  # noqa: F401
    print(" [OK] config.py imported successfully")
except ImportError as exc:
    errors.append(f"config.py import failed: {exc}")

# -- Summary ------------------------------------------------------------------
print()
if warnings:
    for w in warnings:
        print(f" [WARNING] {w}")
if errors:
    print("\n [ERROR] Setup incomplete — fix the issues above:\n")
    for e in errors:
        print(f"       * {e}")
    sys.exit(1)
else:
    print(" [SUCCESS] All checks passed! Run your first scrape with:\n")
    print("       python main.py --login\n")
