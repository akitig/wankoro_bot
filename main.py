import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

# ======================================================
# ✅ 設定ロード
# ======================================================
load_dotenv()
intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="/",
    intents=intents,
    application_id=int(os.getenv("APPLICATION_ID"))
)

# ======================================================
# ✅ 起動時イベント
# ======================================================
@bot.event
async def on_ready():
    guild = discord.Object(id=int(os.getenv("GUILD_ID")))
    await bot.tree.sync(guild=guild)
    print(f"✅ Slash commands synced to guild {guild.id}: "
          f"{[cmd.name for cmd in bot.tree.get_commands(guild=guild)]}")
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

# ======================================================
# ✅ 応答テスト
# ======================================================
@bot.tree.command(name="pong", description="Botの応答テスト")
async def pong(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🐾", ephemeral=True)

# ======================================================
# ✅ Cogロード
# ======================================================
async def load_all_cogs():
    cogs = ["cogs.welcome", "cogs.reaction_roles", "cogs.valomap"]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"✅ Loaded: {cog}")
        except Exception as e:
            print(f"❌ Failed to load {cog}: {e}")

# ======================================================
# ✅ メインループ
# ======================================================
async def main():
    async with bot:
        await load_all_cogs()
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())