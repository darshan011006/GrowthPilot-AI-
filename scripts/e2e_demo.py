"""Browser end-to-end test of the Poojaloka demo (Playwright, headless Chromium).

Prerequisites: `make dev` running in demo mode and `make demo` done (login in data/demo-login.txt).
Usage: backend/.venv/bin/python scripts/e2e_demo.py [--base http://localhost:3000] [--shots DIR]

Drives the real UI: login → reset to the Poojaloka demo → brand / catalogue / competitors / integrations →
multi-platform agent run with live timeline → approval inbox (per-platform tabs) → automatic resume and scheduling →
simulated publish + verification → asset library → analytics → evaluation run → apply a recommendation → report →
usage page → mobile. Fails on any browser console error.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
GOAL = ("Create a seven-day Deepavali campaign for Poojaloka's diyas, brass items and pooja essentials across "
        "Instagram, Facebook, Pinterest and Threads, aimed at families in Bengaluru.")
EVAL = "Evaluate last month's results and recommend what to change next."


def creds() -> tuple[str, str]:
    text = (ROOT / "data" / "demo-login.txt").read_text()
    email = re.search(r"email: (.+)", text).group(1).strip()
    pw = re.search(r"password: (.+)", text).group(1).strip()
    return email, pw


def wait_run(page: Page, statuses: tuple[str, ...], timeout=120) -> str:
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
        page.on("dialog", lambda d: d.accept())

        page.goto(f"{args.base}/login")
        page.get_by_label("Email").filter(visible=True).fill(email)
        page.get_by_label("Password").filter(visible=True).fill(pw)
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        page.goto(f"{args.base}/settings")
        page.get_by_label("Demo brand").select_option("poojaloka")
        page.get_by_label("Type RESET to confirm").fill("RESET")
        page.get_by_role("button", name="Reset demo data").click()
        expect(page.get_by_text("Demo data reset.").filter(visible=True).first).to_be_visible(timeout=60000)
        print("✓ demo data reset to Poojaloka from Settings")
        page.goto(f"{args.base}/")
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        expect(page.get_by_text("DEMO MODE").filter(visible=True).first).to_be_visible()
        expect(page.get_by_text("Poojaloka", exact=True).filter(visible=True).first).to_be_visible()
        snap("01-overview")
        print("✓ login + overview")

        page.goto(f"{args.base}/brand")
        expect(page.get_by_text("Where this profile came from").first).to_be_visible()
        page.get_by_role("tab", name=re.compile("Catalogue")).click()
        expect(page.get_by_text("Matki Diya 1 Box 125").filter(visible=True).first).to_be_visible()
        expect(page.get_by_text(re.compile("Dated snapshot")).filter(visible=True).first).to_be_visible()
        snap("02-brand-catalogue")
        page.get_by_role("tab", name=re.compile("Festivals")).click()
        expect(page.get_by_text("Clay diyas").filter(visible=True).first).to_be_visible()
        page.get_by_role("tab", name="Marketing").click()
        expect(page.get_by_text("Content pillars").filter(visible=True).first).to_be_visible()
        snap("02-brand-marketing")
        page.goto(f"{args.base}/competitors")
        expect(page.get_by_text("Devalaya Mart (fictional)").filter(visible=True).first).to_be_visible()
        snap("02-competitor-gallery")
        page.get_by_role("tab", name="Side by side").click()
        expect(page.get_by_text("Positioning notes").filter(visible=True).first).to_be_visible()
        snap("02-competitor-compare")
        page.goto(f"{args.base}/integrations")
        for name in ("Google Gemini (LLM)", "Brave Search (web research)"):
            expect(page.get_by_text(name).filter(visible=True).first).to_be_visible()
        expect(page.get_by_text("Threads").filter(visible=True).first).to_be_visible()
        snap("02-integrations")
        for path, heading in [("/research", "Research"), ("/usage", "Usage & Budgets"), ("/assets", "Asset Library")]:
            page.goto(f"{args.base}{path}")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        print("✓ brand / catalogue / festivals / competitors / integrations / research / usage / assets")

        page.goto(f"{args.base}/agent")
        page.get_by_label("Goal").filter(visible=True).fill(GOAL)
        page.get_by_role("button", name="Start run").click()
        page.wait_for_url(re.compile(r"/agent/[0-9a-f]{32}"))
        status = wait_run(page, ("Awaiting approval", "Completed", "Blocked", "Failed"))
        assert status == "Awaiting approval", f"run ended {status}"
        for text in ("Re-plan", "Rendering poster images", "Adapting posts for each platform", "Agent team"):
            expect(page.get_by_text(text).filter(visible=True).first).to_be_visible()
        page.get_by_role("button", name="Details").filter(visible=True).nth(3).click()
        expect(page.get_by_text("Specialist:").filter(visible=True).first).to_be_visible()
        snap("03-agent-timeline")
        run_url = page.url
        print("✓ agent run: delegation, re-plan, rendered images, platform variants; paused for approval")

        page.goto(f"{args.base}/approvals")
        expect(page.get_by_role("heading", name="Approval Inbox")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile(r"^Approve (all|instagram)")).filter(visible=True).first).to_be_visible(timeout=30000)
        snap("04-approvals")
        approved = 0
        for _ in range(40):
            bulk = page.get_by_role("button", name=re.compile(r"^Approve all \d+ passing")).filter(visible=True).first
            if bulk.is_visible():
                card = page.locator("section").filter(has=bulk).first
                ack = card.get_by_label(re.compile("reviewed the warnings on every version"))
                if ack.count():
                    ack.check()
                n = int(re.search(r"\d+", bulk.inner_text()).group(0))
                bulk.click()
                approved += n
                page.wait_for_timeout(900)
                continue
            single = page.get_by_role("button", name=re.compile(r"^Approve \w+ v\d+")).filter(visible=True).first
            if not single.is_visible():
                break
            card = page.locator("section").filter(has=single).first
            ack = card.get_by_label(re.compile("reviewed the"))
            if ack.count():
                ack.first.check()
            single.click()
            approved += 1
            page.wait_for_timeout(700)
        assert approved >= 10, f"approved only {approved}"
        print(f"✓ approved {approved} platform versions")

        page.goto(run_url)
        status = wait_run(page, ("Completed", "Blocked", "Failed"), timeout=60)
        assert status == "Completed", status
        expect(page.get_by_text("Preparing the schedule").filter(visible=True).first).to_be_visible()
        snap("05-agent-completed")
        print("✓ run resumed automatically and scheduled approved versions on each platform")

        page.goto(f"{args.base}/calendar")
        expect(page.get_by_role("heading", name="Content Calendar")).to_be_visible()
        page.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_timeout(600)
        snap("06-calendar")

        page.goto(f"{args.base}/content")
        page.get_by_label("Status").filter(visible=True).select_option("scheduled")
        page.get_by_label("Platform").filter(visible=True).select_option("instagram")
        page.wait_for_timeout(900)
        snap("06-creative-gallery")
        page.locator("main a[href^='/content/']").filter(visible=True).first.click()
        expect(page.get_by_role("tablist", name="Platform versions")).to_be_visible()
        page.get_by_role("button", name="Publish now").click()
        expect(page.get_by_text("verified by provider").filter(visible=True).first).to_be_visible(timeout=15000)
        expect(page.get_by_text("simulated").filter(visible=True).first).to_be_visible()
        snap("07-published-demo")
        print("✓ published one platform version via the demo adapter and verified (labelled simulated)")

        page.goto(f"{args.base}/assets")
        page.locator("main button img").filter(visible=True).first.click()
        expect(page.get_by_text("Image checks").filter(visible=True).first).to_be_visible()
        snap("08-asset-detail")
        page.keyboard.press("Escape")
        print("✓ asset library shows provenance and image checks")

        page.goto(f"{args.base}/analytics")
        page.get_by_role("button", name="Collect latest metrics").click()
        expect(page.get_by_text("Synthetic demo data").filter(visible=True).first).to_be_visible()
        snap("09-analytics")
        print("✓ analytics labelled synthetic")

        page.goto(f"{args.base}/agent")
        page.get_by_label("Goal").filter(visible=True).fill(EVAL)
        page.get_by_role("button", name="Start run").click()
        page.wait_for_url(re.compile(r"/agent/[0-9a-f]{32}"))
        assert wait_run(page, ("Completed", "Blocked", "Failed")) == "Completed"
        snap("10-evaluation-run")
        page.goto(f"{args.base}/experiments")
        expect(page.get_by_text(re.compile("Supported|Inconclusive")).first).to_be_visible()
        apply = page.get_by_role("button", name="Approve & apply change").filter(visible=True).first
        expect(apply).to_be_visible()
        apply.click()
        expect(page.get_by_text(re.compile(r"^applied ")).filter(visible=True).first).to_be_visible(timeout=10000)
        snap("11-experiments")
        page.goto(f"{args.base}/reports")
        page.locator("main ul a").filter(visible=True).first.click()
        expect(page.get_by_text("Demo data notice").filter(visible=True).first).to_be_visible()
        snap("12-report")
        print("✓ evaluation → conclusion with confidence → approved change → report")

        page.goto(f"{args.base}/usage")
        expect(page.get_by_text("Price list used for estimates").filter(visible=True).first).to_be_visible()
        snap("13-usage")

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{args.base}/")
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        page.wait_for_timeout(800)
        snap("14-mobile-overview")
        page.goto(f"{args.base}/approvals")
        page.wait_for_timeout(600)
        snap("15-mobile-approvals")
        browser.close()

    real_errors = [e for e in errors if "favicon" not in e]
    if real_errors:
        print("✕ browser console errors:\n  " + "\n  ".join(real_errors[:20]))
        return 1
    print(f"✓ no browser console errors. Screenshots in {shots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
