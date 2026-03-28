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

browser = None
page = None
playwright = None
context = None
credential_data = None

async def automate_password_reset(email):  # Just Sends Code
    global browser, page, playwright, credential_data, context
    config.AUTHVALUE = ""
    config.EMAIL_REENTER = False  # Reset the flag at the start
    config.MASKED_EMAIL = ""  # Reset the masked email

    # Check if we're continuing from an email verification
    if page is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
        page = await context.new_page()
    else:
        context = page.context

    # Virtual authenticator: fires immediately but fails user verification
    # This makes Microsoft's passkey attempt resolve instantly and fall through
    # to "Sign in another way" instead of hanging indefinitely
    cdp = await context.new_cdp_session(page)
    await cdp.send("WebAuthn.enable", {"enableUI": False})
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
        "options": {
            "protocol": "ctap2",
            "transport": "internal",
            "hasResidentKey": True,
            "hasUserVerification": True,
            "isUserVerified": False,           # False = auth FAILS = no hang
            "automaticPresenceSimulation": True, # True = fires immediately, doesn't wait
        }
    })

    credential_data = None

    async def log_request(route, request):
        global request_payload
        print(f"Intercepted request URL: {request.url}")
        if "https://login.live.com/GetCredentialType.srf" in request.url:
            try:
                # Capture the POST data (payload) from the request
                if request.method == 'POST':  # Check if it's a POST request
                    request_payload = await request.post_data()
                    print(f"Captured Request Payload: {request_payload}")
                else:
                    print("Non-POST request, no payload.")
            except Exception as e:
                print(f"Error capturing request payload: {e}")
        await route.continue_()  # Continue the request, otherwise it will be blocked

    async def log_response(response):
        global credential_data
        if "https://login.live.com/GetCredentialType.srf" in response.url:
            try:
                response_text = await response.text()
                response_json = json.loads(response_text)
                proofs = response_json.get("Credentials", {}).get("OtcLoginEligibleProofs", [])
                if proofs and "data" in proofs[0]:
                    credential_data = proofs[0]["data"]
                    print(f"Credential Data Captured: {credential_data}")
            except Exception as e:
                print(f"Error parsing response: {e}")

    page.on("response", log_response)
    page.on("route", log_request)

    # Only navigate to the login page if we're not already on it
    if not page.url.startswith("https://login.live.com"):
        while True:
            try:
                await page.goto("https://login.live.com")
                await page.get_by_role("textbox", name="Email or phone number").wait_for(timeout=1000)
                break
            except Exception:
                print("Textbox not found, refreshing...")
                await page.reload()

    # Only fill the email if we're not already on the email verification page
    if not page.url.startswith("https://login.live.com/ppsecure/"):
        await page.get_by_role("textbox", name="Email or phone number").fill(email)
        await page.get_by_test_id("primaryButton").click()
        await page.wait_for_timeout(3000)


    # Check for "Could not find account" error message
    try:
        error_element = page.locator('span:has-text("We couldn\'t find a Microsoft account. Try entering your details again, or create an account.")')
        if await error_element.count() > 0:
            print("Account not found error detected")
            config.ACCOUNT_NOT_FOUND = True  # Set a flag to indicate this error
            return False
    except Exception as e:
        print(f"Error checking for account not found message: {e}")

    # Try Other ways → Send a code
    try:
        other_ways_button = page.get_by_text("Sign in another way")
        await other_ways_button.click()
        if await other_ways_button.count() > 0:
            await other_ways_button.first.click()
            await page.wait_for_timeout(2000)  # Wait for options to appear

            # Check if email is hidden or visible
            email_hidden = False
            try:
                # Look for masked email pattern
                masked_email_element = page.locator('text=We\'ll send a code to')
                if await masked_email_element.count() > 0:
                    masked_email_text = await masked_email_element.inner_text()
                    if "send a code to " in masked_email_text:
                        masked_email = masked_email_text.split("send a code to ")[1]
                        # Check if email is masked (contains asterisks)
                        email_hidden = "*" in masked_email
                        config.MASKED_EMAIL = masked_email
                        print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
            except Exception as e:
                print(f"Error checking for masked email: {e}")

            # Try multiple selectors for "Send a code" button/span
            send_code_found = False

            # Try button with name "Send a code"
            try:
                send_button = page.get_by_role("button", name="Send a code")
                if await send_button.count() > 0:
                    await send_button.first.click()
                    send_code_found = True
                    print("Clicked 'Send a code' button")
            except Exception as e:
                print(f"Error clicking 'Send a code' button: {e}")

            # Try span with specific text if button didn't work
            if not send_code_found:
                try:
                    # Try multiple selectors for the span element
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

            # If we found and clicked the send code option
            if send_code_found:
                # Wait for page to load after clicking "Send a code"
                await page.wait_for_timeout(2000)

                # Check for "To verify this is your email" message
                try:
                    email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                    if await email_verify_text.count() > 0:
                        print("Email re-verification required")
                        config.EMAIL_REENTER = True  # Set flag to indicate email re-entry is needed
                        return False  # Don't close the browser, keep the page open
                except Exception as e:
                    print(f"Error checking for email verification message: {e}")

                # If no email verification needed, continue with normal flow
                return True
    except TimeoutError:
        pass

    # Try direct Send a code (without clicking "Sign in another way" first)
    try:
        # Check if email is hidden or visible
        email_hidden = False
        try:
            # Look for masked email pattern
            masked_email_element = page.locator('text=We\'ll send a code to')
            if await masked_email_element.count() > 0:
                masked_email_text = await masked_email_element.inner_text()
                if "send a code to " in masked_email_text:
                    masked_email = masked_email_text.split("send a code to ")[1]
                    # Check if email is masked (contains asterisks)
                    email_hidden = "*" in masked_email
                    config.MASKED_EMAIL = masked_email
                    print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
        except Exception as e:
            print(f"Error checking for masked email: {e}")

        # Try multiple selectors for "Send a code" button/span
        send_code_found = False

        # Try button with name "Send a code"
        try:
            send_code_button = page.get_by_role("button", name="Send a code")
            if await send_code_button.count() > 0:
                await send_code_button.first.click()
                send_code_found = True
                print("Clicked 'Send a code' button (direct)")
        except Exception as e:
            print(f"Error clicking 'Send a code' button (direct): {e}")
            # Try span with specific text if button didn't work
            if not send_code_found:
                    try:
                        # Try multiple selectors for the span element
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

                # If we found and clicked the send code option
                    if send_code_found:
                    # Wait for page to load after clicking "Send a code"
                        await page.wait_for_timeout(2000)

                    # Check for "To verify this is your email" message
                    try:
                        email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                        if await email_verify_text.count() > 0:
                            print("Email re-verification required")
                            config.EMAIL_REENTER = True  # Set flag to indicate email re-entry is needed
                            return False  # Don't close the browser, keep the page open
                    except Exception as e:
                        print(f"Error checking for email verification message: {e}")

                    # If no email verification needed, continue with normal flow
                    return True
    except TimeoutError:
        pass

    # Try primary button as fallback
    try:
        # Check if email is hidden or visible
        email_hidden = False
        try:
            # Look for masked email pattern
            masked_email_element = page.locator('text=We\'ll send a code to')
            if await masked_email_element.count() > 0:
                masked_email_text = await masked_email_element.inner_text()
                if "send a code to " in masked_email_text:
                    masked_email = masked_email_text.split("send a code to ")[1]
                    # Check if email is masked (contains asterisks)
                    email_hidden = "*" in masked_email
                    config.MASKED_EMAIL = masked_email
                    print(f"Email detected: {masked_email}, Hidden: {email_hidden}")
        except Exception as e:
            print(f"Error checking for masked email: {e}")

        primary_button = page.get_by_test_id("primaryButton")
        if await primary_button.count() > 0:
            await primary_button.first.click()

            # Wait for page to load after clicking primary button
            await page.wait_for_timeout(2000)

            # Check for "To verify this is your email" message
            try:
                email_verify_text = page.locator('text=To verify this is your email, enter it here.')
                if await email_verify_text.count() > 0:
                    print("Email re-verification required")
                    config.EMAIL_REENTER = True  # Set flag to indicate email re-entry is needed
                    return False  # Don't close the browser, keep the page open
            except Exception as e:
                print(f"Error checking for email verification message: {e}")

            # If no email verification needed, continue with normal flow
            return True
    except TimeoutError:
        pass

    return False


async def automate_auto_change(email, code, newemail, newpass):
    global browser, page, playwright

    # If no active session exists, we need to initialize one
    if not page:
        print("No active session found. Run automate_password_reset first.")
        return

    try:
        # Generate a new password if not provided
        if not newpass:
            newpass = generate_password()
            print(f"Generated new password: {newpass}")

        # Validate code format before submitting
        if code and (not code.isdigit() or len(code) != 6):
            config.INCORRECT_CODE = True
            return False

        if config.AUTHVALUE == "" or code is not None:
            # Check if we're already on the code entry page
            try:
                code_inputs = page.locator('input[aria-label*="Enter code digit"]')
                if await code_inputs.count() > 0:
                    print("Already on code entry page")
                else:
                    print("Not on code entry page, looking for code inputs...")
                    # Try to find code inputs with different selectors
                    code_inputs = page.locator('input[type="text"][maxlength="1"]')
                    if await code_inputs.count() > 0:
                        print("Found code inputs with alternative selector")
            except Exception as e:
                print(f"Error checking for code entry page: {e}")

            # Fill in the code
            for i, digit in enumerate(code, start=1):
                try:
                    # Try different selectors for code input fields
                    code_input = page.locator(f'input[aria-label*="Enter code digit {i}"]')
                    if await code_input.count() == 0:
                        code_input = page.locator(f'input[name="otc{i}"]')
                    if await code_input.count() == 0:
                        code_input = page.locator(f'input[placeholder*="{i}"]')
                    if await code_input.count() == 0:
                        code_input = code_inputs.nth(i-1)  # Use the nth input if no specific selector works

                    await code_input.fill(digit)
                except Exception as e:
                    print(f"Error filling code digit {i}: {e}")

            await page.keyboard.press("Enter")
            await asyncio.sleep(2)

            # Check for incorrect code message
            try:
                error_element = page.locator('span:has-text("That code is incorrect. Check the code and try again.")')
                if await error_element.count() > 0:
                    print("Incorrect code detected")
                    config.INCORRECT_CODE = True
                    return False
            except Exception as e:
                print(f"Error checking for incorrect code message: {e}")

        # This is the key part that clicks the "Yes" button after entering the code
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
        context = page.context
        cookies = await context.cookies()

        for cookie in cookies:
            if cookie['name'] == '__Host-MSAAUTHP':
                print(f"Cookie __Host-MSAAUTHP: {cookie['value']}")
                config.LastCookie = {cookie['value']}

        await asyncio.sleep(15)

        # Check if we're already on the account page
#        current_url = page.url
      #  if not current_url.startswith("https://account.live.com/"):
     ##    try:
         #       await page.goto("https://account.live.com/")
         #       await page.wait_for_load_state('load')
          #  except Exception as e:
            #    print(f"Error navigating to account page: {e}")
            #    # Try alternative navigation
            #    try:
               #     await page.goto("https://account.microsoft.com/")
                #    await page.wait_for_load_state('load')
                #except Exception as e2:
                  #  print(f"Error navigating to alternative account page: {e2}")
                #    # If we can't navigate, continue with the current page
                  #  print("Continuing with current page")

        # Fixed close button clicking with multiple fallback selectors
        try:
            # First try with the specific ID
            close_button = page.locator('#landing-page-dialog\\.close')
            await close_button.wait_for(state="visible", timeout=100000)
            await close_button.click()
            print("Clicked close button with ID selector")
        except Exception as e:
            print(f"ID selector failed: {e}")
            try:
                # Try with the aria-label as fallback
                close_button = page.locator('button[aria-label="Close"]')
                await close_button.wait_for(state="visible", timeout=5000)
                await close_button.click()
                print("Clicked close button with aria-label")
            except Exception as e2:
                print(f"aria-label selector failed: {e2}")
                try:
                    # Try with the data-bi-id as another fallback
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

        # Handle recovery code
        await handle_recovery_code(page)

        await page.locator("#AddProofLink").click()
        await page.locator("#Add_email").click()
        await page.get_by_placeholder("someone@example.com").fill(newemail)
        await page.click('input.btn.btn-block.btn-primary#iNext')

        security_code = get_security_code_by_email(config.MAILSLURP_API_KEY, newemail)
        await page.fill("#iOttText", security_code)
        await page.click("#iNext")

        # Fixed email removal process
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
            # Click the Email0 div to expand it
            await page.locator('#Email0').click()
            print("Clicked Email0 div")

            # Wait for the Remove button to be visible and click it
            await page.wait_for_selector('#Email0 #Remove', timeout=5000)
            await page.locator('#Email0 #Remove').click()
            print("Clicked Remove button")

            # Wait for and click the confirmation button (iBtn_action)
            try:
                await page.wait_for_selector('button#iBtn_action', timeout=5000)
                await asyncio.sleep(1)
                await page.evaluate("document.querySelector('button#iBtn_action').click()")
                print("Clicked confirmation button (iBtn_action) via JS")
            except:
                pass

            try:
                await page.wait_for_selector('button#iBtn_action', timeout=5000)
                await asyncio.sleep(1)
                await page.evaluate("document.querySelector('button#iBtn_action').click()")
                print("Clicked confirmation button (iBtn_action) via JS")
            except:
                # If iBtn_action isn't found, try alternative confirmation button selectors
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
                            await confirmation_button.click()
                            print(f"Clicked confirmation button with selector: {selector}")
                            break
                    except:
                        continue
                else:
                    print("Could not find confirmation button")
                    await page.screenshot(path="confirmation_dialog_debug.png")

        except Exception as e:
            print(f"Error in email removal process: {e}")
            await page.screenshot(path="email_removal_debug.png")

        finally:
            # Always stop the watcher when email removal is done
            stop_event.set()
            stuck_watcher.cancel()
            try:
                await stuck_watcher
            except asyncio.CancelledError:
                pass

        # Dismiss any lingering modal backdrop before password change
        try:
            backdrop = page.locator('div.modal-backdrop')
            if await backdrop.count() > 0:
                print("Modal backdrop detected, attempting to dismiss...")
                # Try pressing Escape to close the modal
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
                # Check if backdrop is gone
                if await backdrop.count() > 0:
                    # Try clicking outside the modal
                    await page.mouse.click(10, 10)
                    await asyncio.sleep(1)
                # If still there, force-remove it via JS
                if await backdrop.count() > 0:
                    await page.evaluate("document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")
                    await page.evaluate("document.body.classList.remove('modal-open')")
                    print("Removed modal backdrop via JavaScript")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error dismissing modal backdrop: {e}")

        # NEW: Password change functionality
        try:
            # Check if the password section exists
            password_section_exists = await page.locator('a[aria-label="Enter password"]').count() > 0

            if not password_section_exists:
                print("Password section not found, clicking to add it")
                # Click the "Enter password" link to add the password option
                await page.locator('a[aria-label="Enter password"]').click()
                await asyncio.sleep(2)  # Wait for the section to expand

            # Click the "Change password" button
            await page.locator('#ChangePassword').click()
            print("Clicked Change password button")

            # Fill in the new password fields (newpass is already generated above if needed)
            await page.fill('#iPassword', newpass)
            await page.fill('#iRetypePassword', newpass)
            print("Filled password fields")

            # Click the Save button
            await page.click('#UpdatePasswordAction')
            print("Clicked Save button to update password")

            # Wait for password update to complete
            await asyncio.sleep(3)

            # Check if password update was successful
            try:
                success_element = await page.locator('.ms-MessageBar:has-text("Your password has been updated")').count() > 0
                if success_element:
                    print("Password updated successfully")
                else:
                    print("Password update status unclear, clicking")
                    await page.mouse.click(
                        page.viewport_size["width"] / 2,
                        page.viewport_size["height"] / 2
                    )
            except:
                print("Could not verify password update status")

        except Exception as e:
            print(f"Error in password change process: {e}")
            await page.screenshot(path="password_change_debug.png")

    except Exception as e:
        print(f"An error occurred in automate_auto_change: {e}")
        # Keep browser open on error for debugging
        print("Keeping browser open for 60 seconds for manual inspection...")
        await asyncio.sleep(60)

    finally:
        # Increase the sleep time significantly before closing
        print("Waiting 10 seconds before closing browser...")
        await asyncio.sleep(10)
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()

        # NEW: Password change functionality

async def handle_recovery_code(page):
    """
    Handles the recovery code generation process.
    This function waits for the link, clicks it, waits for the modal,
    extracts the code, stores it, and then closes the modal.
    """
    try:
        print("Attempting to find and click the 'Generate a new code' link...")

        # Wait for the link to be visible and attached to the DOM
        recovery_link_locator = page.locator("#RecoveryCodeLink")
        await recovery_link_locator.wait_for(state="visible", timeout=10000)

        # Click the link
        await recovery_link_locator.click()
        print("Clicked 'Generate a new code' link.")

        # Wait for the modal container to appear
        modal_locator = page.locator("#ModalContent")
        await modal_locator.wait_for(state="visible", timeout=10000)
        print("Recovery code modal is visible.")

        # Now, wait for the actual code text to be inside the modal
        # We'll wait for a <strong> tag that looks like a recovery code
        print("Waiting for the recovery code to be generated and displayed...")
        code_locator = modal_locator.get_by_text(re.compile(r"[A-Z0-9-]{16,}"))
        await code_locator.wait_for(state="visible", timeout=15000) # Give it extra time

        # Extract the code
        recovery_code = await code_locator.inner_text()
        print(f"Successfully captured recovery code: {recovery_code}")

        # Store the code
        config.LastRecoveryCode = recovery_code

        # Close the modal
        await page.get_by_role("button", name="Got it").click()
        print("Closed the recovery code modal.")

    except PlaywrightTimeoutError as e:
        print(f"ERROR: Timed out waiting for a recovery code element. {e}")
        # Take a screenshot for debugging
        await page.screenshot(path="recovery_code_timeout_error.png")
        # Print the modal's content to see what's actually there
        try:
            if await modal_locator.count() > 0:
                modal_html = await modal_locator.inner_html()
                print(f"Modal HTML at time of timeout: {modal_html}")
        except Exception as html_e:
            print(f"Could not get modal HTML: {html_e}")
        # Re-raise the exception to stop the script or handle it higher up
        raise

    except Exception as e:
        print(f"An unexpected error occurred in handle_recovery_code: {e}")
        await page.screenshot(path="recovery_code_unexpected_error.png")
        raise

def get_security_code_by_email(api_key, email_address, timeout=90000):
    # Extract UUID from email (works for any domain)
    if "@" in email_address:
        inbox_id = email_address.split("@")[0]
    else:
        inbox_id = email_address  # Already a UUID

    config = Configuration()
    config.api_key['x-api-key'] = api_key

    with ApiClient(config) as api_client:
        wait_api = WaitForControllerApi(api_client)
        start_time = time.time()

        while time.time() - start_time < timeout / 1000:  # Convert ms to seconds
            try:
                email = wait_api.wait_for_latest_email(
                    inbox_id=inbox_id,
                    timeout=5000
                )

                if email:
                    # Parse the HTML email body
                    soup = BeautifulSoup(email.body, "html.parser")

                    # Find text containing "Security code:"
                    security_text = soup.find(
                        string=lambda text: text and "Security code:" in text
                    )

                    if security_text:
                        # Get next span containing the code
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

    # Use aiohttp with SSL verification bypassed
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
    """Helper function to fill input and press Enter."""
    await page.fill(selector, text)
    await page.press(selector, "Enter")



async def continue_password_reset():
    """
    Continues the password reset process after email verification.
    This function is called after the user has entered their email in the verification modal.
    """
    global page

    try:
        # Wait for the page to process the email
        await page.wait_for_timeout(3000)

        # Check if we're already on the code entry page
        try:
            code_input = page.locator('input[aria-label*="Enter code digit"]')
            if await code_input.count() > 0:
                print("Already on code entry page")
                return True
        except Exception as e:
            print(f"Error checking for code entry page: {e}")

        # Look for "Already received a code?" button
        try:
            already_button = page.get_by_role("button", name="Already received a code?")
            if await already_button.count() > 0:
                await already_button.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked 'Already received a code?' button")
                return True
        except Exception as e:
            print(f"Error clicking 'Already received a code?' button: {e}")

        # Try clicking the primary button as a fallback
        try:
            primary_button = page.get_by_test_id("primaryButton")
            if await primary_button.count() > 0:
                await primary_button.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked primary button")
                return True
        except Exception as e:
            print(f"Error clicking primary button: {e}")

        # Check for any other buttons that might continue the flow
        try:
            continue_buttons = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Send")')
            if await continue_buttons.count() > 0:
                await continue_buttons.first.click()
                await page.wait_for_timeout(2000)
                print("Clicked continue/next/send button")
                return True
        except Exception as e:
            print(f"Error clicking continue button: {e}")

        # If we get here, we might need to wait for the code to be sent
        print("Waiting for code to be sent...")
        await page.wait_for_timeout(5000)

        # Check again for code inputs after waiting
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
