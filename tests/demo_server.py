"""Run the app against the local fake Wattpad (for trying the publish UI without a real account).

    python -m tests.demo_server        → http://127.0.0.1:8766  (separate data dir: data_demo/)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.update(DATA_DIR=str(ROOT / "data_demo"), OUTPUT_DIR=str(ROOT / "data_demo" / "output"),
                  APP_PORT="8766", LLM_PROVIDER="mock", TRANSLATE_PROVIDER="mock", WATTPAD_HEADLESS="true", WATTPAD_PUBLISH_WAIT="5",
                  WATTPAD_PROFILE_DIR=str(ROOT / "data_demo" / "wp_profile"), WATTPAD_BROWSER_CHANNEL="")

from tests.fake_wattpad import FakeWattpad  # noqa: E402

fake = FakeWattpad()
os.environ["WATTPAD_BASE_URL"] = fake.base
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:  # stands in for the one-time manual login
    ctx = p.chromium.launch_persistent_context(os.environ["WATTPAD_PROFILE_DIR"], headless=True)
    ctx.new_page().goto(fake.base + "/dev-login")
    ctx.close()
print(f"Fake Wattpad at {fake.base}", file=sys.stderr)

from app.main import run  # noqa: E402

run()
