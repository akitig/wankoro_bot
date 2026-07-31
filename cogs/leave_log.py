import logging

import discord
from discord.ext import commands

from config import get_config
from services.leave_log_service import LeaveLogService

logger = logging.getLogger(__name__)


class LeaveLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        config = get_config()
        self.LEAVE_LOG_CHANNEL_ID = config.require_id(
            config.leave_log_channel_id,
            "LEAVE_LOG_CHANNEL_ID",
        )
        self.service = LeaveLogService(self.LEAVE_LOG_CHANNEL_ID)

    # ======================================================
    # ✅ 退出イベント（leave/kick/ban）
    # ======================================================
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.service.handle_member_remove(member)

    # ======================================================
    # ✅ BAN検知イベント
    # ======================================================
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.service.record_ban(guild, user)

    # ======================================================
    # ✅ KICK検知イベント（AuditLog）
    # ======================================================
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        await self.service.record_audit_log_entry(entry)

    # ======================================================
    # ✅ 起動時ログ
    # ======================================================
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Leave-log event handlers ready")


async def setup(bot):
    await bot.add_cog(LeaveLog(bot))
