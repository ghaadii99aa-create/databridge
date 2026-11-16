"""Browser walkthrough of PUBLIC DEMO MODE with two separate visitors (Playwright).

Start a demo server first (DEMO_MODE=true, built frontend served by the backend), then:
    python scripts/e2e_demo.py --base http://127.0.0.1:8000 --chrome "C:/Program Files/Google/Chrome/Application/chrome.exe"
Exit code 0 when every check passes. Note the demo's upload rate limit (10 per hour per IP):
restart the server before running it repeatedly.
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "databridge-demo-shots"))
ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH"))
args = ap.parse_args()
U, S = args.base.rstrip("/"), args.out
TMP = Path(tempfile.mkdtemp(prefix="databridge-demo-"))
Path(S).mkdir(parents=True, exist_ok=True)
results = []
def check(name, ok):
    results.append((name, bool(ok))); print(("PASS " if ok else "FAIL ") + name)

with sync_playwright() as p:
    b = p.chromium.launch(**({"executable_path": args.chrome} if args.chrome else {}))
    a = b.new_context(viewport={"width": 1366, "height": 900}); pa = a.new_page()
    errors = []; pa.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pa.goto(U + "/"); pa.wait_for_load_state("networkidle")
    check("demo notice visible", pa.get_by_text("Public demo.").is_visible())
    check("overview populated (no empty state)", pa.get_by_text("Load sample dataset").count() == 0)
    check("sample shown on overview", pa.get_by_text("Retail sales (SAMPLE)").first.is_visible())
    pa.screenshot(path=f"{S}/01-overview.png", full_page=True)

    pa.goto(U + "/datasets"); pa.wait_for_load_state("networkidle")
    check("upload panel shows 10 MB and 50,000 rows", pa.get_by_text("Up to 10 MB and 50,000 rows").is_visible())
    pa.get_by_role("link", name="Retail sales (SAMPLE)").click(); pa.wait_for_load_state("networkidle")
    pa.get_by_text("Create pipeline").first.wait_for(timeout=10000)
    check("sample: no Rename/Delete", pa.get_by_role("button", name="Rename").count() == 0 and pa.get_by_role("button", name="Delete").count() == 0)
    check("sample: Create pipeline available", pa.get_by_text("Create pipeline").first.is_visible())
    pa.screenshot(path=f"{S}/02-sample-detail.png", full_page=True)

    pa.goto(U + "/pipelines"); pa.get_by_text("Clean retail sales (SAMPLE)").first.wait_for(timeout=10000)
    check("shared pipeline: Make a copy, no Edit/Delete/Run",
          pa.get_by_role("link", name="Make a copy").is_visible() and pa.get_by_role("button", name="Delete").count() == 0
          and pa.get_by_role("button", name="Run", exact=True).count() == 0)
    pa.screenshot(path=f"{S}/03-pipelines.png", full_page=True)

    pa.goto(U + "/quality"); pa.get_by_text("Raw data assessment").wait_for(timeout=10000)
    check("quality page shows score, no Re-assess on sample",
          pa.get_by_text("Raw data assessment").is_visible() and pa.get_by_role("button", name="Re-assess").count() == 0)
    pa.goto(U + "/explorer"); pa.wait_for_load_state("networkidle")
    check("explorer shows rows", pa.locator("table tbody tr").count() > 5)
    pa.goto(U + "/analytics"); pa.wait_for_load_state("networkidle"); pa.wait_for_timeout(1500)
    check("analytics draws charts", pa.locator("svg.recharts-surface").count() > 0)
    pa.screenshot(path=f"{S}/04-analytics.png", full_page=True)
    pa.goto(U + "/reports"); pa.get_by_role("link", name="Download").first.wait_for(timeout=10000)
    check("shared report: download, no delete", pa.get_by_role("link", name="Download").count() >= 1
          and pa.locator("button[aria-label^='Delete']").count() == 0)

    # visitor A uploads a private file
    open(str(TMP / "private-a.csv"), "w").write("id,city,amount\n1,Riyadh,10\n2,Jeddah,20\n")
    pa.goto(U + "/datasets"); pa.wait_for_load_state("networkidle")
    pa.locator("input[type=file]").set_input_files(str(TMP / "private-a.csv"))
    pa.get_by_role("button", name="Upload and profile").click()
    for _ in range(80):  # the upload navigates to /datasets/<new id>
        if pa.url.rstrip("/").split("/")[-1].isdigit():
            break
        pa.wait_for_timeout(250)
    pa.get_by_role("button", name="Delete").wait_for(timeout=10000)
    check("A's upload is editable by A", pa.get_by_role("button", name="Delete").count() == 1)
    a_url = pa.url

    # oversized row count shows a clear message
    with open(str(TMP / "rows.csv"), "w") as f:
        f.write("id,v\n"); f.writelines(f"{i},{i}\n" for i in range(50_001))
    pa.goto(U + "/datasets"); pa.wait_for_load_state("networkidle")
    pa.locator("input[type=file]").set_input_files(str(TMP / "rows.csv"))
    pa.get_by_role("button", name="Upload and profile").click()
    alert = pa.get_by_role("alert").filter(has_text="50,000")
    alert.wait_for(timeout=20000)
    check("50,001-row file: clear error shown", "50,001 rows" in alert.inner_text())
    pa.screenshot(path=f"{S}/05-row-limit.png", full_page=True)

    # visitor B: separate browser
    bctx = b.new_context(viewport={"width": 1366, "height": 900}); pb = bctx.new_page()
    pb.goto(U + "/datasets"); pb.wait_for_load_state("networkidle")
    check("B sees the sample", pb.get_by_text("Retail sales (SAMPLE)").first.is_visible())
    check("B does not see A's upload", pb.get_by_text("private-a").count() == 0)
    pb.goto(a_url); pb.wait_for_load_state("networkidle"); pb.wait_for_timeout(800)
    check("B opening A's URL gets not found", pb.get_by_text("does not exist").count() > 0)
    pb.screenshot(path=f"{S}/06-visitor-b.png", full_page=True)

    # mobile layout still fine
    m = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    for path in ["/", "/datasets", "/datasets/1", "/quality", "/pipelines", "/runs/1", "/explorer", "/analytics", "/analyst", "/reports"]:
        m.goto(U + path); m.wait_for_load_state("networkidle"); m.wait_for_timeout(600)
        check(f"mobile {path}: no horizontal overflow", m.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
    m.goto(U + "/"); m.wait_for_load_state("networkidle")
    m.screenshot(path=f"{S}/07-mobile.png", full_page=True)
    check("no console errors for A", not [e for e in errors if "413" not in e and "404" not in e])
    b.close()
print(f"{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
