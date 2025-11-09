import os
from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
import asyncio

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix="/",
    intents=intents,
    application_id=int(os.getenv("APPLICATION_ID"))
)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    # Cog 側で add_command 済みのものを、ここで同期
    guild = discord.Object(id=int(os.getenv("GUILD_ID")))
    await bot.tree.sync(guild=guild)
    print(f"✅ Slash commands synced to guild {os.getenv('GUILD_ID')}: /welcome, /ok")

from discord import app_commands

@bot.tree.command(name="pong", description="Botの応答テスト")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🐾", ephemeral=True)

async def load_cogs():
    await bot.load_extension("cogs.welcome")
    await bot.load_extension("cogs.reaction_roles")
    await bot.load_extension("cogs.valomap")

if __name__ == "__main__":
    asyncio.run(load_cogs())
    bot.run(os.getenv("DISCORD_TOKEN"))
