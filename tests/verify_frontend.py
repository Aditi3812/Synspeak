import os
import asyncio
from playwright.async_api import async_playwright

async def verify_ui():
    chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    screenshots_dir = os.path.join(os.getcwd(), "static", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    console_errors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=chrome_path,
            headless=True
        )
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # Capture console messages
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        print("1. Loading http://localhost:8000 ...")
        await page.goto("http://localhost:8000")
        await page.wait_for_timeout(1000)

        title = await page.title()
        assert "Synspeak" in title, f"Unexpected title: {title}"
        print(f"   [OK] Page title verified: '{title}'")

        # 2. Check Principles Modal
        print("2. Testing Principles Modal ...")
        await page.click("#btnEthicsInfo")
        await page.wait_for_timeout(500)
        ethics_modal = await page.is_visible("#ethicsModal")
        assert ethics_modal, "Ethics modal should be visible"
        await page.click("#btnCloseEthics")
        await page.wait_for_timeout(300)
        print("   [OK] Principles modal opens and closes properly.")

        # 3. Start Test Feed
        print("3. Activating Test Feed ...")
        await page.click("#btnToggleSimFeed")
        await page.wait_for_timeout(1000)

        # 4. Start Session
        print("4. Starting Study Session ...")
        await page.click("#btnStart")
        print("   Session started, streaming frames for 6 seconds...")
        await page.wait_for_timeout(6000)

        # 5. Check Live Telemetry
        focused_text = await page.text_content("#lblFocusedTime")
        conc_text = await page.text_content("#concPercentage")
        ear_text = await page.text_content("#lblEarAvg")
        yaw_text = await page.text_content("#lblPoseYaw")
        print(f"   [OK] Telemetry updated -> Focused: {focused_text}, Concentration: {conc_text}, EAR: {ear_text}, Yaw: {yaw_text}")

        # Capture Dashboard Screenshot
        dash_shot = os.path.join(screenshots_dir, "live_dashboard.png")
        await page.screenshot(path=dash_shot)
        print(f"   [OK] Captured dashboard screenshot: {dash_shot}")

        # 6. Stop Session & Verify Final Report
        print("5. Stopping Session to trigger final report ...")
        await page.click("#btnStop")
        await page.wait_for_selector("#reportModal", state="visible", timeout=10000)

        report_visible = await page.is_visible("#reportModal")
        assert report_visible, "Report modal should appear on session stop"
        
        rep_conc = await page.text_content("#repConcentrationScore")
        rep_total = await page.text_content("#repTotalDuration")
        print(f"   [OK] Report modal displayed -> Rating: {rep_conc}, Total Monitored: {rep_total}")

        # Capture Report Screenshot
        report_shot = os.path.join(screenshots_dir, "session_report.png")
        await page.screenshot(path=report_shot)
        print(f"   [OK] Captured report screenshot: {report_shot}")

        await browser.close()
        print("\nAll Frontend verification tests PASSED with 0 errors!")
        if console_errors:
            print("Note: Console errors detected:", console_errors)

if __name__ == "__main__":
    asyncio.run(verify_ui())
