import asyncio
import logging

import discord
from discord.ext import commands

from config import get_config
from logging_config import configure_logging

logger = logging.getLogger(__name__)

try:
    config = get_config()
except Exception:
    configure_logging("INFO")
    logger.critical("Bot configuration could not be loaded", exc_info=True)
    raise

configure_logging(config.log_level, secrets=(config.discord_token,))
intents = discord.Intents.all()

COGS = [
    "cogs.welcome",
    "cogs.reaction_roles",
    "cogs.valomap",
    "cogs.leave_log",
    "cogs.valocheck",
    "cogs.valorecruit",
    "cogs.dm_forward",
    "cogs.2025_xmas_gacha",
    "cogs.2026_joya_gacha",
    "cogs.2026_omikuji_gacha",
    "cogs.bump_panel",
]

class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Cog loaded: %s", cog)
            except Exception:
                logger.exception("Cog failed to load: %s", cog)

        guild = discord.Object(id=config.guild_id)

        # Cog側の @app_commands.command をギルドに即反映させる
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        logger.info(
            "Application commands synced: count=%d",
            len(self.tree.get_commands(guild=guild)),
        )

bot = MyBot(
    command_prefix="/",
    intents=intents,
    application_id=config.application_id,
)

@bot.event
async def on_ready():
    logger.info("Bot connected to Discord")

async def main():
    logger.info("Bot startup requested")
    try:
        if not config.discord_token:
            raise RuntimeError("Missing environment variable: DISCORD_TOKEN")
        await bot.start(config.discord_token)
    except Exception:
        logger.critical("Bot startup failed", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
