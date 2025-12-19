import os
import discord
from discord.ext import commands


def _get_opt_int_env(key: str):
    v = os.getenv(key)
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


class DmForwardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.forward_user_id = _get_opt_int_env("DM_FORWARD_USER_ID")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if not self.forward_user_id:
            return

        # 転送先ユーザー取得
        target = self.bot.get_user(self.forward_user_id)
        if target is None:
            try:
                target = await self.bot.fetch_user(self.forward_user_id)
            except Exception:
                return

        # 転送本文
        content = message.content or ""
        header = (
            f"📩 **DM転送**\n"
            f"From: **{message.author}** (`{message.author.id}`)\n"
        )

        # まず本文を送る
        try:
            if content.strip():
                await target.send(header + content)
            else:
                await target.send(header + "（本文なし）")
        except Exception:
            return

        # 添付ファイルも転送（URLだけでもOKならこれで十分）
        for a in message.attachments[:10]:
            try:
                await target.send(f"📎 添付: {a.url}")
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(DmForwardCog(bot))
