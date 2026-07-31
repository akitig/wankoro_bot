"""Leave, kick, and ban notification operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord

logger = logging.getLogger(__name__)


class LeaveLogService:
    """Track moderation events and send member departure notifications."""

    def __init__(
        self,
        leave_log_channel_id: int,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.leave_log_channel_id = leave_log_channel_id
        self.recent_bans: dict[int, str] = {}
        self.recent_kicks: dict[int, str] = {}
        self._sleep = sleep

    async def handle_member_remove(self, member: Any) -> None:
        guild = member.guild
        channel = guild.get_channel(self.leave_log_channel_id)
        if not channel:
            logger.warning("Leave log channel is unavailable")
            return

        await self._sleep(1)

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

        roles = [
            role.mention
            for role in member.roles
            if role != guild.default_role
        ]
        role_list = ", ".join(roles) if roles else "なし"
        titles = {
            "leave": "📕 退出者が出ました",
            "kick": "🦶 ユーザーが追放されました",
            "ban": "🕊️ ユーザーがBANされました",
        }
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
        logger.info("Leave notification sent: event_type=%s", event_type)

    async def record_ban(self, guild: Any, user: Any) -> None:
        try:
            entry = await guild.fetch_ban(user)
            reason = entry.reason if entry.reason else "理由なし"
        except Exception:
            logger.exception("Failed to fetch ban details")
            reason = "理由なし"
        self.recent_bans[user.id] = reason
        logger.info("Member ban event recorded")

    async def record_audit_log_entry(self, entry: Any) -> None:
        if entry.action == discord.AuditLogAction.kick:
            target = entry.target
            if isinstance(target, discord.User):
                self.recent_kicks[target.id] = entry.reason or "理由なし"
                logger.info("Member kick event recorded")
