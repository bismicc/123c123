import asyncio
import json
import logging
import os
import random
import string

from playwright.async_api import async_playwright

log = logging.getLogger("gcloud_auto")

GCLOUD_URL = "https://console.cloud.google.com/welcome?pli=1&project=gen-lang-client-0046642574&cloudshell=true"
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")


SAMESITE_MAP = {
    "strict": "Strict",
    "lax": "Lax",
    "none": "None",
    "no_restriction": "None",
    "unspecified": None,
    "": None,
}


def load_cookies():
    if not os.path.exists(COOKIES_FILE) or os.path.getsize(COOKIES_FILE) == 0:
        raise RuntimeError(
            f"cookies.json is missing or empty. Add your Google Cloud browser cookies to: {COOKIES_FILE}"
        )
    with open(COOKIES_FILE, "r") as f:
        raw = json.load(f)

    cookies = []
    for c in raw:
        name = c.get("name", "")
        value = c.get("value")
        if not name or value is None:
            continue

        path = c.get("path", "/")

        # __Host- prefixed cookies must NOT have a domain attribute
        if name.startswith("__Host-"):
            cookie = {
                "name": name,
                "value": str(value),
                "url": "https://google.com",
            }
        else:
            domain = c.get("domain", ".google.com")
            host_only = bool(c.get("hostOnly", False))
            if not host_only and not domain.startswith(".") and not domain.startswith("http"):
                domain = "." + domain
            cookie = {
                "name": name,
                "value": str(value),
                "domain": domain,
                "path": path,
            }

        if "expirationDate" in c:
            try:
                cookie["expires"] = int(c["expirationDate"])
            except (TypeError, ValueError):
                pass

        cookie["secure"] = bool(c.get("secure", False))
        cookie["httpOnly"] = bool(c.get("httpOnly", False))

        same_raw = str(c.get("sameSite", "")).lower()
        same_mapped = SAMESITE_MAP.get(same_raw)
        if same_mapped:
            cookie["sameSite"] = same_mapped

        cookies.append(cookie)
    return cookies


async def run_console_automation():
    log.info("Starting Google Cloud console automation...")
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
            good = []
            for ck in cookies:
                try:
                    await context.add_cookies([ck])
                    good.append(ck)
                except Exception as e:
                    log.warning(f"Skipped bad cookie '{ck.get('name')}': {e}")
            log.info(f"Added {len(good)} valid cookies")

            page = await context.new_page()
            await page.bring_to_front()

            log.info(f"Navigating to {GCLOUD_URL}")
            await page.goto(GCLOUD_URL, wait_until="domcontentloaded", timeout=60000)
            log.info(f"Page loaded: {page.url}")

            # Wait 5 seconds for the page to settle
            log.info("Waiting 5 seconds for page to fully load...")
            await page.wait_for_timeout(5000)

            # Click the xterm terminal area to focus it
            log.info("Looking for terminal area...")
            terminal_selectors = [
                ".xterm-screen",
                ".xterm-helper-textarea",
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
        log.error(f"Google Cloud automation crashed: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(asctime)s | %(name)s | %(message)s",
    )
    asyncio.run(run_console_automation())
