import logging
import os
import sys

import discord
from discord.ext import commands

import config
from keep_alive import keep_alive
from views.button_one import ButtonViewOne


class PhobosBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            case_insensitive=True,
            intents=discord.Intents.all(),
            allowed_mentions=discord.AllowedMentions(
                roles=False,
                everyone=False,
                users=True
            ),
        )

        self.logger = logging.getLogger("bot")
        self.admins = [1012091795737419857]

    async def setup_hook(self):
        await self.load_cogs()

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        self.add_view(ButtonViewOne())

    async def load_cogs(self, directory="./cogs"):
        for file in os.listdir(directory):
            if file.endswith(".py") and not file.startswith("_"):
                await self.load_extension(
                    f"{directory[2:].replace('/', '.')}.{file[:-3]}"
                )
                self.logger.info(f"Loaded: {file[:-3]}")
            elif not (
                file in ["__pycache__"]
                or file.endswith(("pyc", "txt"))
            ) and not file.startswith("_"):
                await self.load_cogs(f"{directory}/{file}")

        await self.load_extension("jishaku")

    @staticmethod
    def setup_logging():
        logging.getLogger("discord").setLevel(logging.INFO)
        logging.getLogger("discord.http").setLevel(logging.WARNING)

        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s | %(asctime)s | %(name)s | %(message)s",
            stream=sys.stdout,
        )


if __name__ == "__main__":
    keep_alive()  # 🔥 START WEB SERVER FIRST

    bot = PhobosBot()
    bot.remove_command("help")
    bot.setup_logging()

    bot.run(config.TOKEN, log_handler=None)