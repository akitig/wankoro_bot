"""Business operations and state for the Welcome workflow."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from typing import Any

import discord

logger = logging.getLogger(__name__)


class WelcomeService:
    """Create Welcome rooms and own the answers for active workflows."""

    def __init__(
        self,
        bot: Any,
        *,
        guild_id: int,
        admin_id: int,
        staff_role_ids: tuple[int, int, int],
        choice: Callable[[list[Any]], Any] = random.choice,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.admin_id = admin_id
        self.staff_role_ids = staff_role_ids
        self._choice = choice
        self.user_answers: dict[int, dict[str, Any]] = {}
        self.processing_users: set[int] = set()

    def is_processing(self, member_id: int) -> bool:
        return member_id in self.processing_users

    def get_answers(self, member_id: int) -> dict[str, Any]:
        return self.user_answers[member_id]

    def set_answer(self, member_id: int, key: str, value: Any) -> None:
        self.user_answers[member_id][key] = value

    def toggle_time(self, member_id: int, label: str) -> list[str]:
        answers = self.user_answers[member_id]
        times = answers.setdefault("time", [])
        if label in times:
            times.remove(label)
        else:
            times.append(label)
        return times

    async def pick_staff(self, guild: Any) -> Any | None:
        roles = [guild.get_role(role_id) for role_id in self.staff_role_ids]
        candidates = [
            member
            for member in guild.members
            if any(role in member.roles for role in roles)
        ]
        if not candidates:
            return None

        voice_candidates = [
            member
            for voice_channel in guild.voice_channels
            for member in voice_channel.members
            if member in candidates
        ]
        return self._choice(voice_candidates or candidates)

    @staticmethod
    def _channel_name(guild: Any, member: Any) -> str:
        base = f"welcome-{member.name.lower()}"
        name = base
        suffix = 2
        while discord.utils.get(guild.channels, name=name):
            name = f"{base}-{suffix}"
            suffix += 1
        return name

    @staticmethod
    def _permission_overwrites(
        guild: Any,
        member: Any,
        staff: Any | None,
    ) -> dict[Any, discord.PermissionOverwrite]:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True,
                use_external_stickers=True,
            ),
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        return overwrites

    async def create_welcome_room(
        self,
        member: Any,
        *,
        welcome_embed: Callable[[], discord.Embed],
        question_view: Callable[[], discord.ui.View],
    ) -> Any | None:
        guild = self.bot.get_guild(self.guild_id)

        if self.is_processing(member.id):
            logger.warning("Skipped duplicate welcome workflow")
            return None
        self.processing_users.add(member.id)

        try:
            staff = await self.pick_staff(guild)
            staff_id = staff.id if staff else self.admin_id
            staff_mention = staff.mention if staff else f"<@{self.admin_id}>"
            self.user_answers[member.id] = {"staff_id": staff_id}

            category = discord.utils.get(guild.categories, name="welcome")
            if category is None:
                category = await guild.create_category("welcome")

            channel = await guild.create_text_channel(
                self._channel_name(guild, member),
                category=category,
                overwrites=self._permission_overwrites(guild, member, staff),
            )

            try:
                await channel.send(
                    f"🔥 ようこそ {member.mention} さん！\n"
                    f"案内担当 → {staff_mention}"
                )
                await channel.send(embed=welcome_embed())
                await channel.send(
                    "🧩 **Q1. 25歳以上ですか？**",
                    view=question_view(),
                )
            except discord.Forbidden:
                logger.exception("Bot cannot send messages to a welcome channel")
                permissions = channel.permissions_for(guild.me)
                logger.debug(
                    "Welcome channel permissions: view=%s send=%s embed=%s manage=%s",
                    permissions.view_channel,
                    permissions.send_messages,
                    permissions.embed_links,
                    permissions.manage_messages,
                )
                return None

            return channel
        except discord.Forbidden:
            logger.exception("Missing permission while creating a welcome channel")
            return None
        finally:
            self.processing_users.discard(member.id)
