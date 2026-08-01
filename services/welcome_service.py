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
        handler_role_id: int,
        inactive_voice_channel_id: int | None = None,
        excluded_user_ids: frozenset[int] = frozenset(),
        choice: Callable[[list[Any]], Any] = random.choice,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.admin_id = admin_id
        self._handler_role_id = handler_role_id
        self._inactive_voice_channel_id = inactive_voice_channel_id
        self._excluded_user_ids = excluded_user_ids
        self._choice = choice
        self.user_answers: dict[int, dict[str, Any]] = {}
        self.processing_users: set[int] = set()
        self._last_handler_id: int | None = None

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

    def _resolve_handler_candidates(self, guild: Any) -> list[Any]:
        candidates: list[Any] = []
        seen: set[int] = set()
        for member in guild.members:
            member_id = member.id
            if member_id in seen:
                continue
            seen.add(member_id)
            if getattr(member, "bot", False):
                continue
            if member_id in self._excluded_user_ids:
                continue
            if not any(
                getattr(role, "id", None) == self._handler_role_id
                for role in getattr(member, "roles", ())
            ):
                continue
            candidates.append(member)
        return candidates

    def _resolve_active_voice_candidates(self, candidates: list[Any]) -> list[Any]:
        active = []
        for member in candidates:
            voice = getattr(member, "voice", None)
            channel = getattr(voice, "channel", None)
            if channel is None:
                continue
            if (
                self._inactive_voice_channel_id is not None
                and getattr(channel, "id", None) == self._inactive_voice_channel_id
            ):
                continue
            active.append(member)
        return active

    def _choose_handler(self, candidates: list[Any]) -> Any:
        selectable = candidates
        if len(candidates) >= 2:
            selectable = [
                member for member in candidates if member.id != self._last_handler_id
            ]
        selected = self._choice(selectable)
        self._last_handler_id = selected.id
        return selected

    async def pick_staff(self, guild: Any) -> Any | None:
        candidates = self._resolve_handler_candidates(guild)
        if not candidates:
            return None
        voice_candidates = self._resolve_active_voice_candidates(candidates)
        return self._choose_handler(voice_candidates or candidates)

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
            if staff is None:
                self._last_handler_id = self.admin_id
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
