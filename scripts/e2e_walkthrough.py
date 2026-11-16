"""End-to-end browser test: drive the demonstration workflow through the real UI and save screenshots.

Requires an EMPTY database and a running app (e.g. scripts/start-production.ps1), plus Playwright:
    pip install playwright && python -m playwright install chromium
    python scripts/e2e_walkthrough.py --base http://127.0.0.1:8000
Fails (non-zero exit) on any step that does not appear or on browser console errors.
"""
import argparse, os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "docs" / "screenshots"))
ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH"), help="optional browser executable")
args = ap.parse_args()
BASE, OUT = args.base, args.out
Path(OUT).mkdir(parents=True, exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch(**({"executable_path": args.chrome} if args.chrome else {}))
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    def shot(name, full=True):
        page.wait_for_timeout(500)
        page.screenshot(path=f"{OUT}/{name}.png", full_page=full)

    t0 = time.time(); page.goto(BASE + "/"); page.get_by_text("No data yet").wait_for()
    print("overview empty-state visible in", round(time.time() - t0, 2), "s")
    shot("01-overview-empty")

    page.get_by_role("button", name="Load sample dataset").click()
    page.wait_for_url("**/datasets/*"); page.get_by_text("Raw preview").wait_for()
    shot("02-dataset-detail")

    page.get_by_role("link", name="Review findings").click()
    page.get_by_text("Findings").first.wait_for(); shot("03-quality")

    page.goto(BASE + "/datasets"); page.get_by_text("All datasets").wait_for(); shot("04-datasets", full=False)

    page.goto(BASE + "/pipelines/new"); page.get_by_text("Cleaning rules").wait_for()  # first ready dataset is preselected
    page.get_by_label("Transaction ID is required").check()
    page.get_by_label("Transaction Date is required").check()
    shot("05-pipeline-editor")
    page.get_by_role("button", name="Save and run").click()
    page.wait_for_url("**/runs/*"); page.get_by_text("Quality before and after").wait_for(timeout=30000)
    shot("06-run")

    page.get_by_role("link", name="Explore output").click()
    page.get_by_text("Processed, typed columns").wait_for()
    page.get_by_label("Filter column").select_option(label="Region")
    page.get_by_label("Filter value").fill("Central")
    page.get_by_role("button", name="Add filter").click()
    page.get_by_role("button", name="Revenue (SAR)").click(); page.get_by_role("button", name="Revenue (SAR)").click()
    page.wait_for_timeout(800); shot("07-explorer", full=False)
    page.get_by_role("tab", name="Column statistics").click(); page.wait_for_timeout(800); shot("08-explorer-stats", full=False)

    page.goto(BASE + "/analytics"); page.get_by_text("Distribution of").wait_for(timeout=15000)
    page.wait_for_timeout(1200); shot("09-analytics")

    page.goto(BASE + "/analyst"); page.get_by_text("Common questions").wait_for()
    page.get_by_role("button", name="What are the most important findings?").click()
    page.get_by_text("Statistical analysis (computed").first.wait_for(); shot("10-analyst")

    page.goto(BASE + "/reports"); page.get_by_role("button", name="Generate report").click()
    page.get_by_text("Report generated").wait_for(); shot("11-reports", full=False)

    page.goto(BASE + "/"); page.get_by_text("Recent pipeline runs").wait_for(); page.wait_for_timeout(1500); shot("12-overview")

    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    m.goto(BASE + "/"); m.get_by_text("Recent pipeline runs").wait_for(); m.wait_for_timeout(1200)
    m.screenshot(path=f"{OUT}/13-mobile-overview.png", full_page=False)
    m.get_by_role("button", name="Open menu").click(); m.wait_for_timeout(300)
    m.screenshot(path=f"{OUT}/14-mobile-menu.png")
    b.close()

print("console errors:", errors or "none")
sys.exit(1 if errors else 0)
