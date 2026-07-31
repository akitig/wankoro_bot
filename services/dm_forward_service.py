"""DM forwarding operations."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DmForwardService:
    """Resolve the forwarding target and relay one direct message."""

    def __init__(self, bot: Any, forward_user_id: int | None) -> None:
        self.bot = bot
        self.forward_user_id = forward_user_id

    async def forward_message(self, message: Any) -> None:
        target = self.bot.get_user(self.forward_user_id)
        if target is None:
            try:
                target = await self.bot.fetch_user(self.forward_user_id)
            except Exception:
                logger.exception(
                    "Failed to resolve the configured DM forwarding target"
                )
                return

        content = message.content or ""
        header = (
            "📩 **DM転送**\n"
            f"From: **{message.author}** (`{message.author.id}`)\n"
        )
        try:
            if content.strip():
                await target.send(header + content)
            else:
                await target.send(header + "（本文なし）")
        except Exception:
            logger.exception("Failed to forward a DM message")
            return

        for attachment in message.attachments[:10]:
            try:
                await target.send(f"📎 添付: {attachment.url}")
            except Exception:
                logger.exception("Failed to forward a DM attachment")
