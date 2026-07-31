"""Reaction Role resolution and Discord role operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Set
from typing import Any

logger = logging.getLogger(__name__)


class ReactionRoleService:
    """Resolve reaction payloads and apply the configured Discord role."""

    def __init__(
        self,
        bot: Any,
        *,
        guild_id: int,
        message_ids: Set[int],
        reaction_role_map: Mapping[int, int],
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.message_ids = message_ids
        self.reaction_role_map = reaction_role_map

    async def handle_reaction(self, payload: Any, *, add: bool) -> None:
        if payload.message_id not in self.message_ids:
            return
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        emoji_id = payload.emoji.id if payload.emoji.is_custom_emoji() else None
        role_id = self.reaction_role_map.get(emoji_id)
        if not role_id:
            return

        role = guild.get_role(role_id)
        if not role:
            return

        try:
            if add:
                await member.add_roles(role)
                logger.info("Reaction Role assigned")
            else:
                await member.remove_roles(role)
                logger.info("Reaction Role removed")
        except Exception:
            logger.exception("Reaction Role operation failed")
            raise
