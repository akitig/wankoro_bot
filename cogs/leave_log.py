import asyncio
import logging

import discord
from discord.ext import commands

from config import get_config

logger = logging.getLogger(__name__)


class LeaveLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        config = get_config()
        self.LEAVE_LOG_CHANNEL_ID = config.require_id(
            config.leave_log_channel_id,
            "LEAVE_LOG_CHANNEL_ID",
        )
        self.recent_bans = {}
        self.recent_kicks = {}

    # ======================================================
    # ✅ 退出イベント（leave/kick/ban）
    # ======================================================
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        channel = guild.get_channel(self.LEAVE_LOG_CHANNEL_ID)
        if not channel:
            logger.warning("Leave log channel is unavailable")
            return

        # Kick/Ban情報を待つ（AuditLog反映遅延対策）
        await asyncio.sleep(1)

        reason = None
        event_type = "leave"
        color = 0xFF6B6B

        if member.id in self.recent_kicks:
            reason = self.recent_kicks.pop(member.id)
            event_type = "kick"
            color = 0xFFD166
        elif member.id in self.recent_bans:
            reason = self.recent_bans.pop(member.id)
            event_type = "ban"
            color = 0x6B8AFF

        # 退出時のロール一覧
        roles = [r.mention for r in member.roles if r != guild.default_role]
        role_list = ", ".join(roles) if roles else "なし"

        # タイトルごとに変化
        titles = {
            "leave": "📕 退出者が出ました",
            "kick": "🦶 ユーザーが追放されました",
            "ban": "🕊️ ユーザーがBANされました",
        }

        # Embed生成
        embed = discord.Embed(title=titles[event_type], color=color)
        embed.add_field(
            name="👤 ユーザー:",
            value=f"{member.mention}",
            inline=False,
        )
        embed.add_field(
            name="🆔 ID:",
            value=f"`{member.id}`",
            inline=False,
        )
        embed.add_field(
            name="🎭 退出時ロール:",
            value=role_list,
            inline=False,
        )
        if reason:
            embed.add_field(
                name="📝 理由:",
                value=reason,
                inline=False,
            )
        embed.set_thumbnail(
            url=member.display_avatar.url if member.display_avatar else None
        )

        await channel.send(embed=embed)
        logger.info(
            "Leave notification sent: event_type=%s",
            event_type,
        )

    # ======================================================
    # ✅ BAN検知イベント
    # ======================================================
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        try:
            entry = await guild.fetch_ban(user)
            reason = entry.reason if entry.reason else "理由なし"
        except Exception:
            logger.exception("Failed to fetch ban details")
            reason = "理由なし"

        self.recent_bans[user.id] = reason
        logger.info("Member ban event recorded")

    # ======================================================
    # ✅ KICK検知イベント（AuditLog）
    # ======================================================
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        if entry.action == discord.AuditLogAction.kick:
            target = entry.target
            if isinstance(target, discord.User):
                self.recent_kicks[target.id] = entry.reason or "理由なし"
                logger.info("Member kick event recorded")

    # ======================================================
    # ✅ 起動時ログ
    # ======================================================
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Leave-log event handlers ready")


async def setup(bot):
    await bot.add_cog(LeaveLog(bot))