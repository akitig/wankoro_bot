import discord
from discord.ext import commands

from config import get_config
from services.dm_forward_service import DmForwardService


class DmForwardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.forward_user_id = get_config().dm_forward_user_id
        self.service = DmForwardService(bot, self.forward_user_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if not self.forward_user_id:
            return

        await self.service.forward_message(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(DmForwardCog(bot))
