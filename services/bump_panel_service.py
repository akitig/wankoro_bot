"""Business workflow for the DISBOARD BUMP guidance panel."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from repositories.bump_panel_repository import BumpPanelRepository

logger = logging.getLogger(__name__)

_BUMP_SUCCESS_PATTERN = re.compile(
    r"\bbump(?:ed)?\s+(?:done|complete|completed|success|successful)\b",
    re.IGNORECASE,
)


def _message_text_fragments(message: Any) -> tuple[str, ...]:
    fragments: list[str] = []
    content = getattr(message, "content", None)
    if isinstance(content, str):
        fragments.append(content)
    for embed in getattr(message, "embeds", ()) or ():
        for value in (
            getattr(embed, "title", None),
            getattr(embed, "description", None),
            getattr(getattr(embed, "author", None), "name", None),
            getattr(getattr(embed, "footer", None), "text", None),
        ):
            if isinstance(value, str):
                fragments.append(value)
    return tuple(fragments)


def is_bump_success_message(
    message: Any,
    *,
    channel_id: int,
    disboard_bot_id: int,
) -> bool:
    """Conservatively identify a successful DISBOARD ``/bump`` response."""

    if getattr(getattr(message, "channel", None), "id", None) != channel_id:
        return False
    if getattr(getattr(message, "author", None), "id", None) != disboard_bot_id:
        return False

    metadata = getattr(message, "interaction_metadata", None)
    command_name = getattr(metadata, "name", None)
    if not isinstance(command_name, str):
        interaction = getattr(message, "interaction", None)
        command_name = getattr(interaction, "name", None)
    if isinstance(command_name, str):
        return command_name.casefold() == "bump"

    for fragment in _message_text_fragments(message):
        normalized = fragment.casefold()
        if _BUMP_SUCCESS_PATTERN.search(normalized):
            return True
        if "bump" in normalized and ("成功" in fragment or "完了" in fragment):
            return True
        if "表示順をアップ" in fragment:
            return True
    return False


class BumpPanelService:
    """Coordinate BUMP state, one-shot cooldown scheduling, and panel I/O."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: BumpPanelRepository,
        channel_id: int,
        disboard_bot_id: int,
        bump_command_id: int | None,
        cooldown_seconds: int,
        view_factory: Callable[[bool], discord.ui.View],
        now_factory: Callable[[], datetime] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.bot = bot
        self._repository = repository
        self._channel_id = channel_id
        self._disboard_bot_id = disboard_bot_id
        self._bump_command_id = bump_command_id
        self._cooldown_seconds = cooldown_seconds
        self._view_factory = view_factory
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep_func
        self._cooldown_task: asyncio.Task[None] | None = None
        self._loaded = False

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory must return a timezone-aware datetime")
        return now

    def is_available(self, now: datetime | None = None) -> bool:
        current = now or self._now()
        next_bump_at = self._repository.get_next_bump_at()
        return next_bump_at is None or next_bump_at <= current

    @staticmethod
    def panel_embed(next_bump_at: datetime | None) -> discord.Embed:
        if next_bump_at is None:
            return discord.Embed(
                title="🟢 BUMPできます",
                description=(
                    "サーバーを上位表示できます。\n"
                    "下のボタンからBUMPコマンドを開いてください。"
                ),
                color=discord.Color.green(),
            )
        unix_time = int(next_bump_at.timestamp())
        return discord.Embed(
            title="⏳ BUMP待機中",
            description=f"次回BUMP可能：<t:{unix_time}:R>",
            color=discord.Color.greyple(),
        )

    async def initialize(self) -> None:
        if not self._loaded:
            self._repository.load()
            self._loaded = True
            logger.info("BUMP panel state loaded")

        next_bump_at = self._repository.get_next_bump_at()
        now = self._now()
        if next_bump_at is not None and next_bump_at <= now:
            self._repository.clear_next_bump_at()
            self._repository.save()
            next_bump_at = None
        await self.ensure_panel()
        if next_bump_at is not None:
            self._schedule_cooldown(next_bump_at)

    def _get_channel(self) -> Any | None:
        channel = self.bot.get_channel(self._channel_id)
        if channel is None:
            logger.warning("BUMP panel channel is unavailable")
        return channel

    async def ensure_panel(self) -> None:
        channel = self._get_channel()
        if channel is None:
            return
        next_bump_at = self._repository.get_next_bump_at()
        message_id = self._repository.get_panel_message_id()
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                logger.warning("Stored BUMP panel message was not found")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to fetch the BUMP panel message")
                return
            else:
                try:
                    await message.edit(
                        embed=self.panel_embed(next_bump_at),
                        view=self._view_factory(next_bump_at is None),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Failed to update the BUMP panel")
                    return
                logger.info("BUMP panel updated")
                return
        await self._create_panel(channel, next_bump_at)

    async def _create_panel(
        self,
        channel: Any,
        next_bump_at: datetime | None,
    ) -> None:
        try:
            message = await channel.send(
                embed=self.panel_embed(next_bump_at),
                view=self._view_factory(next_bump_at is None),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to create the BUMP panel")
            return
        self._repository.set_panel_message_id(message.id)
        try:
            self._repository.save()
        except Exception:
            logger.exception("Failed to save the BUMP panel state after panel creation")
            raise
        logger.info("BUMP panel created")

    async def handle_message(self, message: Any) -> None:
        if not is_bump_success_message(
            message,
            channel_id=self._channel_id,
            disboard_bot_id=self._disboard_bot_id,
        ):
            if (
                getattr(getattr(message, "channel", None), "id", None)
                == self._channel_id
                and getattr(getattr(message, "author", None), "id", None)
                == self._disboard_bot_id
            ):
                logger.warning("Unable to confirm a DISBOARD BUMP response")
            return
        await self.record_bump_success()

    async def record_bump_success(self) -> None:
        now = self._now()
        next_bump_at = now + timedelta(seconds=self._cooldown_seconds)
        self._repository.set_bump_times(
            last_bumped_at=now,
            next_bump_at=next_bump_at,
        )
        try:
            self._repository.save()
        except Exception:
            logger.exception("Failed to save the BUMP cooldown state")
            raise
        logger.info("BUMP cooldown started")
        self._schedule_cooldown(next_bump_at)
        await self._repost_waiting_panel(next_bump_at)

    async def _repost_waiting_panel(self, next_bump_at: datetime) -> None:
        channel = self._get_channel()
        if channel is None:
            return
        message_id = self._repository.get_panel_message_id()
        if message_id:
            try:
                old_message = await channel.fetch_message(message_id)
                await old_message.delete()
            except discord.NotFound:
                logger.warning("Stored BUMP panel message was not found")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to delete the previous BUMP panel")
        await self._create_panel(channel, next_bump_at)

    def _schedule_cooldown(self, next_bump_at: datetime) -> None:
        if self._cooldown_task is not None and not self._cooldown_task.done():
            self._cooldown_task.cancel()
        self._cooldown_task = asyncio.create_task(
            self._wait_for_cooldown(next_bump_at),
            name="bump-panel-cooldown",
        )

    async def _wait_for_cooldown(self, next_bump_at: datetime) -> None:
        try:
            delay = max(0.0, (next_bump_at - self._now()).total_seconds())
            await self._sleep(delay)
            self._repository.clear_next_bump_at()
            self._repository.save()
            await self.ensure_panel()
            logger.info("BUMP cooldown ended")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected failure in the BUMP cooldown task")

    async def send_command_guide(self, interaction: discord.Interaction) -> None:
        if self._bump_command_id is None:
            message = (
                "このチャンネルで /bump を入力し、\n"
                "DISBOARDのコマンドを選択してください。"
            )
            logger.warning("DISBOARD BUMP command ID is not configured")
        else:
            message = f"BUMPはこちら：</bump:{self._bump_command_id}>"

        is_done = getattr(interaction.response, "is_done", lambda: False)
        if is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def shutdown(self) -> None:
        task = self._cooldown_task
        self._cooldown_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
