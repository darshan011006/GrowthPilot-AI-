"""Browser end-to-end test of the demo flow (Playwright, headless Chromium).

Prerequisites: `make dev` running in demo mode and `make demo` done (login in data/demo-login.txt).
Usage: backend/.venv/bin/python scripts/e2e_demo.py [--base http://localhost:3000] [--shots DIR]

Drives the real UI: login → overview → agent run → trace → approval inbox → approve → schedule →
publish (simulated) → analytics → evaluation run → experiments → report. Fails on any browser console error.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
GOAL = ("Create a seven-day Instagram campaign for our new Kabini sofa collection aimed at urban homeowners in "
        "Bengaluru ahead of Diwali.")


def creds() -> tuple[str, str]:
    text = (ROOT / "data" / "demo-login.txt").read_text()
    email = re.search(r"email: (.+)", text).group(1).strip()
    pw = re.search(r"password: (.+)", text).group(1).strip()
    return email, pw


def wait_run(page: Page, statuses: tuple[str, ...], timeout=60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for s in statuses:
            if page.get_by_text(s, exact=True).filter(visible=True).first.is_visible():
                return s
        time.sleep(0.5)
    raise AssertionError(f"run did not reach {statuses}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--shots", default=str(ROOT / "data" / "e2e-screenshots"))
    args = ap.parse_args()
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    email, pw = creds()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        snap = lambda name: page.screenshot(path=str(shots / f"{name}.png"), full_page=True)  # noqa: E731

        page.goto(f"{args.base}/login")
        page.get_by_label("Email").filter(visible=True).fill(email)
        page.get_by_label("Password").filter(visible=True).fill(pw)
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        # Start from a clean demo dataset (exercises the one-click reset in Settings).
        page.goto(f"{args.base}/settings")
        page.get_by_label("Type RESET to confirm").fill("RESET")
        page.get_by_role("button", name="Reset demo data").click()
        expect(page.get_by_text("Demo data reset.").filter(visible=True).first).to_be_visible(timeout=20000)
        print("✓ demo data reset from Settings")
        page.goto(f"{args.base}/")
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        expect(page.get_by_text("DEMO MODE").filter(visible=True).first).to_be_visible()
        snap("01-overview")
        print("✓ login + overview")

        for path, heading in [("/brand", "Brand Brain"), ("/competitors", "Competitor Radar"), ("/research", "Research"),
                              ("/integrations", "Integrations"), ("/settings", "Settings")]:
            page.goto(f"{args.base}{path}")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            snap(f"02-{path.strip('/')}")
        page.goto(f"{args.base}/brand")
        page.get_by_role("tab", name=re.compile("Products")).click()
        expect(page.get_by_text("Kabini 3-Seater Sofa").filter(visible=True).first).to_be_visible()
        snap("02-brand-products")
        print("✓ brand / competitors / research / integrations / settings pages")

        page.goto(f"{args.base}/agent")
        page.get_by_label("Goal").filter(visible=True).fill(GOAL)
        page.get_by_role("button", name="Start run").click()
        page.wait_for_url(re.compile(r"/agent/[0-9a-f]{32}"))
        status = wait_run(page, ("Awaiting approval", "Completed", "Blocked", "Failed"))
        assert status == "Awaiting approval", f"run ended {status}"
        expect(page.get_by_text("Re-plan").filter(visible=True).first).to_be_visible()
        expect(page.get_by_text("search_web").filter(visible=True).first).to_be_visible()
        snap("03-agent-trace")
        run_url = page.url
        print("✓ agent run paused for approval (trace shows re-plan after blocked search)")

        page.goto(f"{args.base}/approvals")
        expect(page.get_by_role("heading", name="Approval Inbox")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile(r"^Approve v\d+")).filter(visible=True).first).to_be_visible(timeout=30000)
        snap("04-approvals")
        approved = 0
        for _ in range(30):
            btn = page.get_by_role("button", name=re.compile(r"^Approve v\d+")).filter(visible=True).first
            if not btn.is_visible():
                break
            card = page.locator("section").filter(has=btn).first
            ack = card.get_by_label(re.compile("reviewed the"))
            if ack.count():
                ack.check()
            btn.click()
            approved += 1
            page.wait_for_timeout(600)
        assert approved >= 5, f"approved only {approved}"
        print(f"✓ approved {approved} posts")

        page.goto(run_url)
        status = wait_run(page, ("Completed", "Blocked", "Failed"), timeout=40)
        assert status == "Completed", status
        expect(page.get_by_text("schedule_publication").filter(visible=True).first).to_be_visible()
        snap("05-agent-completed")
        print("✓ run resumed automatically and scheduled approved posts")

        page.goto(f"{args.base}/calendar")
        expect(page.get_by_role("heading", name="Content Calendar")).to_be_visible()
        page.get_by_role("button", name="Next", exact=True).click()
        snap("06-calendar")

        page.goto(f"{args.base}/content?")
        page.get_by_label("Status").filter(visible=True).select_option("scheduled")
        page.wait_for_timeout(700)
        page.locator("main table a").filter(visible=True).first.click()
        page.get_by_role("button", name="Publish now").click()
        expect(page.get_by_text("verified by provider").filter(visible=True).first).to_be_visible(timeout=15000)
        expect(page.get_by_text("simulated").filter(visible=True).first).to_be_visible()
        snap("07-published-demo")
        print("✓ published via demo adapter and verified (labelled simulated)")

        page.goto(f"{args.base}/analytics")
        page.get_by_role("button", name="Collect latest metrics").click()
        expect(page.get_by_text("Synthetic demo data").filter(visible=True).first).to_be_visible()
        snap("08-analytics")
        print("✓ analytics labelled synthetic")

        page.goto(f"{args.base}/agent")
        page.get_by_label("Goal").filter(visible=True).fill("Evaluate last month's results and recommend what to change next week.")
        page.get_by_role("button", name="Start run").click()
        page.wait_for_url(re.compile(r"/agent/[0-9a-f]{32}"))
        assert wait_run(page, ("Completed", "Blocked", "Failed")) == "Completed"
        snap("09-evaluation-run")
        page.goto(f"{args.base}/experiments")
        expect(page.get_by_text(re.compile("Supported|Inconclusive")).first).to_be_visible()
        snap("10-experiments")
        page.goto(f"{args.base}/reports")
        page.locator("main ul a").filter(visible=True).first.click()
        expect(page.get_by_text("Demo data notice").filter(visible=True).first).to_be_visible()
        snap("11-report")
        print("✓ evaluation → experiment conclusion → recommendations → report")

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{args.base}/")
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        page.wait_for_timeout(800)
        snap("12-mobile-overview")
        browser.close()

    real_errors = [e for e in errors if "favicon" not in e]
    if real_errors:
        print("✕ browser console errors:\n  " + "\n  ".join(real_errors[:20]))
        return 1
    print(f"✓ no browser console errors. Screenshots in {shots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
