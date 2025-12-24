import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
intents = discord.Intents.all()

COGS = [
    "cogs.welcome",
    "cogs.reaction_roles",
    "cogs.valomap",
    "cogs.leave_log",
    "cogs.valocheck",
    "cogs.valorecruit",
    "cogs.dm_forward",
    "cogs.2025_xmas_gacha"
]

class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"✅ Loaded: {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")

        guild = discord.Object(id=int(os.getenv("GUILD_ID")))

        # Cog側の @app_commands.command をギルドに即反映させる
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        print(
            f"✅ Slash commands synced to guild {guild.id}: "
            f"{[cmd.name for cmd in self.tree.get_commands(guild=guild)]}"
        )

bot = MyBot(
    command_prefix="/",
    intents=intents,
    application_id=int(os.getenv("APPLICATION_ID")),
)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

async def main():
    await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
