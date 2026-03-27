import asyncio
import json
import logging
import os
import random
import string

from playwright.async_api import async_playwright

log = logging.getLogger("replit_auto")

REPLIT_URL = "https://replit.com/@bismic123/bismicproject"
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")


def load_cookies():
    with open(COOKIES_FILE, "r") as f:
        raw = json.load(f)

    cookies = []
    for c in raw:
        domain = c.get("domain", ".replit.com")
        # Playwright requires domain to start with a dot for host cookies
        if not domain.startswith(".") and not domain.startswith("http"):
            domain = "." + domain

        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/"),
        }
        if "expirationDate" in c:
            cookie["expires"] = int(c["expirationDate"])
        if "secure" in c:
            cookie["secure"] = bool(c["secure"])
        if "httpOnly" in c:
            cookie["httpOnly"] = bool(c["httpOnly"])
        same = c.get("sameSite", "")
        if same:
            same = same.capitalize()
            if same in ("Strict", "Lax", "None"):
                cookie["sameSite"] = same
        cookies.append(cookie)
    return cookies


async def run_console_automation():
    log.info("Starting Replit console automation...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            cookies = load_cookies()
            log.info(f"Loaded {len(cookies)} cookies")
            await context.add_cookies(cookies)

            page = await context.new_page()
            await page.bring_to_front()

            log.info(f"Navigating to {REPLIT_URL}")
            await page.goto(REPLIT_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            log.info(f"Page loaded: {page.url}")

            # Find and click the Console tab
            log.info("Looking for Console tab...")
            tab_selectors = [
                'button:has-text("Console")',
                '[role="tab"]:has-text("Console")',
                '[data-tab-bar="true"] button:has-text("Console")',
            ]
            tab_clicked = False
            for selector in tab_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        tab_clicked = True
                        log.info(f"Clicked Console tab via: {selector}")
                        break
                except Exception as e:
                    log.warning(f"Tab selector '{selector}' failed: {e}")

            if not tab_clicked:
                log.warning("Console tab not found, proceeding anyway")

            await page.wait_for_timeout(3000)

            # Click the xterm terminal area to focus it
            log.info("Looking for terminal area...")
            terminal_selectors = [
                ".xterm-screen",
                ".xterm-helper-textarea",
                "[class*='WorkflowsConsole'] canvas",
                "canvas.xterm-link-layer",
            ]
            term_clicked = False
            for selector in terminal_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        term_clicked = True
                        log.info(f"Clicked terminal via: {selector}")
                        break
                except Exception as e:
                    log.warning(f"Terminal selector '{selector}' failed: {e}")

            if not term_clicked:
                log.warning("Terminal area not found, trying keyboard anyway")

            await page.wait_for_timeout(1000)
            # Press Enter once to make sure the terminal has focus
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)

            log.info("Keep-alive loop running...")
            while True:
                try:
                    letter = random.choice(string.ascii_lowercase)
                    await page.keyboard.type(letter)
                    await asyncio.sleep(0.15)
                    await page.keyboard.press("Backspace")
                    log.debug(f"Typed '{letter}' + Backspace")
                    await asyncio.sleep(random.uniform(3.0, 7.0))
                except Exception as e:
                    log.error(f"Error in keep-alive loop: {e}")
                    await asyncio.sleep(5)

    except Exception as e:
        log.error(f"Replit automation crashed: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(asctime)s | %(name)s | %(message)s",
    )
    asyncio.run(run_console_automation())
