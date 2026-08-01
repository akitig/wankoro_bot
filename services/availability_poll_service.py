"""Scheduling, interaction, and audit workflow for anonymous availability polls."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from repositories.availability_poll_repository import (
    ANSWERS,
    ActivePoll,
    AvailabilityPollRepository,
)

try:
    import jpholiday
except ModuleNotFoundError:  # pragma: no cover - deployment validation catches this
    jpholiday = None

logger = logging.getLogger(__name__)

POLL_TEXT = (
    "🐶 いまひま？ by わんころ\n\n"
    "あそぼ！はなそ！\n\n"
    "あしあと感覚で押してみてね🐾\n"
    "押すと今の結果も見られるよ！\n"
    "あとから選び直せるよ！\n"
    "名前は出ず、あしあとだけ残るから安心してね✨"
)
LABELS = {
    "valorant": "VALORANT",
    "other_game": "その他ゲーム",
    "work_vc": "作業VC",
}
ICONS = {"valorant": "🎯", "other_game": "🎮", "work_vc": "🗣️"}


@dataclass(frozen=True, order=True)
class TimeWindow:
    start_minute: int
    end_minute: int


def parse_windows(values: tuple[str, ...]) -> tuple[TimeWindow, ...]:
    windows = []
    for value in values:
        start, end = value.split("-")
        start_hour, start_minute = map(int, start.split(":"))
        end_hour, end_minute = map(int, end.split(":"))
        windows.append(
            TimeWindow(
                start_hour * 60 + start_minute,
                end_hour * 60 + end_minute,
            )
        )
    return tuple(windows)


def default_japanese_holiday(day: date) -> bool:
    if jpholiday is None:
        raise RuntimeError("jpholiday is required for Japanese holiday detection")
    return bool(jpholiday.is_holiday(day))


def next_scheduled_at(
    *,
    now: datetime,
    timezone_info: ZoneInfo,
    weekday_windows: tuple[TimeWindow, ...],
    holiday_windows: tuple[TimeWindow, ...],
    holiday_checker: Callable[[date], bool],
    randrange: Callable[[int, int], int],
) -> datetime:
    """Choose one future second from the next applicable posting window."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(timezone_info)
    for offset in range(0, 367):
        day = local_now.date() + timedelta(days=offset)
        holiday = day.weekday() >= 5 or holiday_checker(day)
        windows = holiday_windows if holiday else weekday_windows
        midnight = datetime.combine(day, time.min, tzinfo=timezone_info)
        for window in windows:
            start = midnight + timedelta(minutes=window.start_minute)
            end = midnight + timedelta(minutes=window.end_minute)
            lower = max(start, local_now)
            if lower >= end:
                continue
            lower_second = int(lower.timestamp())
            if lower.microsecond:
                lower_second += 1
            end_second = int(end.timestamp())
            chosen = randrange(lower_second, end_second)
            return datetime.fromtimestamp(chosen, timezone_info)
    raise RuntimeError("no availability poll window found within one year")


def footprint_count(count: int) -> str:
    if count == 0:
        return ""
    if count <= 10:
        return "🐾" * count
    return f"🐾×{count}"


def result_lines(counts: dict[str, int], *, icons: bool) -> str:
    lines = []
    for answer in ANSWERS:
        count = counts[answer]
        if icons:
            footprints = footprint_count(count)
            lines.append(f"{ICONS[answer]} {LABELS[answer]}　{footprints}（{count}）")
        else:
            lines.append(f"{LABELS[answer]} {count}人")
    return "\n".join(lines)


class AvailabilityPollService:
    """Own the one-shot scheduler and Discord-facing availability workflow."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: AvailabilityPollRepository,
        channel_id: int,
        timezone_name: str,
        weekday_windows: tuple[str, ...],
        holiday_windows: tuple[str, ...],
        audit_guild_id: int,
        audit_channel_id: int,
        view_factory: Callable[[str | None, bool], discord.ui.View],
        now_factory: Callable[[], datetime] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        randrange: Callable[[int, int], int] | None = None,
        holiday_checker: Callable[[date], bool] = default_japanese_holiday,
    ) -> None:
        import random

        self.bot = bot
        self._repository = repository
        self._channel_id = channel_id
        self._timezone = ZoneInfo(timezone_name)
        self._weekday_windows = parse_windows(weekday_windows)
        self._holiday_windows = parse_windows(holiday_windows)
        self._audit_guild_id = audit_guild_id
        self._audit_channel_id = audit_channel_id
        self._view_factory = view_factory
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep_func
        self._randrange = randrange or random.randrange
        self._holiday_checker = holiday_checker
        self._scheduler_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._loaded = False

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory must return an aware datetime")
        return now

    def _choose_next(self, now: datetime | None = None) -> datetime:
        return next_scheduled_at(
            now=now or self._now(),
            timezone_info=self._timezone,
            weekday_windows=self._weekday_windows,
            holiday_windows=self._holiday_windows,
            holiday_checker=self._holiday_checker,
            randrange=self._randrange,
        )

    async def initialize(self) -> None:
        async with self._lock:
            if not self._loaded:
                self._repository.load()
                self._loaded = True
                logger.info("Availability poll state loaded")
            if self._repository.is_paused():
                logger.info("Availability poll scheduler remains paused")
                return
            next_run = self._repository.get_next_run_at()
            now = self._now()
            if next_run is None or next_run <= now:
                next_run = self._choose_next(now)
                self._repository.set_next_run_at(next_run)
                self._repository.save()
                logger.info("Availability poll next run calculated")
            else:
                logger.info("Availability poll next run restored")
            self._replace_scheduler(next_run)

    def _replace_scheduler(self, next_run: datetime) -> None:
        current = asyncio.current_task()
        if (
            self._scheduler_task is not None
            and self._scheduler_task is not current
            and not self._scheduler_task.done()
        ):
            self._scheduler_task.cancel()
        self._scheduler_task = asyncio.create_task(
            self._scheduler_wait(next_run),
            name="availability-poll-scheduler",
        )
        logger.info("Availability poll scheduler started")

    async def _scheduler_wait(self, next_run: datetime) -> None:
        try:
            await self._sleep(max(0.0, (next_run - self._now()).total_seconds()))
            await self._run_scheduled(next_run)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected availability poll scheduler failure")

    async def _run_scheduled(self, scheduled_at: datetime) -> None:
        async with self._lock:
            if self._repository.is_paused():
                return
            stored = self._repository.get_next_run_at()
            if stored != scheduled_at:
                return
            if self._repository.should_skip_next_run():
                self._repository.set_skip_next_run(False)
                logger.info("Availability poll scheduled run skipped")
            else:
                await self._publish_poll(scheduled_at)
            next_run = self._choose_next(max(self._now(), scheduled_at + timedelta(seconds=1)))
            self._repository.set_next_run_at(next_run)
            self._repository.save()
            self._replace_scheduler(next_run)

    def public_embed(self, poll_id: str, counts: dict[str, int]) -> discord.Embed:
        embed = discord.Embed(
            description=f"{POLL_TEXT}\n\n{result_lines(counts, icons=True)}",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Poll ID: {poll_id}")
        return embed

    @staticmethod
    def poll_id_from_message(message: Any) -> str | None:
        embeds = getattr(message, "embeds", ()) or ()
        if not embeds:
            return None
        text = getattr(getattr(embeds[0], "footer", None), "text", None)
        prefix = "Poll ID: "
        return text[len(prefix) :] if isinstance(text, str) and text.startswith(prefix) else None

    async def _publish_poll(self, scheduled_at: datetime) -> bool:
        channel = self.bot.get_channel(self._channel_id)
        if channel is None:
            logger.warning("Availability poll channel is unavailable")
            return False
        await self._close_active_poll()
        poll_id = scheduled_at.astimezone(self._timezone).isoformat()
        try:
            message = await channel.send(
                embed=self.public_embed(poll_id, {answer: 0 for answer in ANSWERS}),
                view=self._view_factory(poll_id, False),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to post an availability poll")
            return False
        self._repository.create_poll(
            poll_id=poll_id,
            message_id=message.id,
            channel_id=self._channel_id,
            opened_at=self._now(),
        )
        self._repository.save()
        logger.info("Availability poll posted")
        return True

    async def _close_active_poll(self) -> None:
        active = self._repository.get_active_poll()
        if active is None or active.closed_at is not None:
            return
        channel = self.bot.get_channel(active.channel_id)
        if channel is not None:
            try:
                message = await channel.fetch_message(active.message_id)
                await message.edit(
                    embed=self.public_embed(active.poll_id, self._repository.get_counts()),
                    view=self._view_factory(active.poll_id, True),
                )
            except discord.NotFound:
                logger.warning("Previous availability poll message was not found")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to close the previous availability poll")
        self._repository.close_active_poll(self._now())
        self._repository.save()
        logger.info("Previous availability poll closed")

    async def handle_answer(
        self,
        interaction: discord.Interaction,
        answer: str | None,
        poll_id: str | None,
    ) -> None:
        user = interaction.user
        if getattr(user, "bot", False):
            await self._respond(interaction, "Botは回答できません。")
            return
        async with self._lock:
            active = self._repository.get_active_poll()
            message = getattr(interaction, "message", None)
            if (
                active is None
                or active.closed_at is not None
                or poll_id != active.poll_id
                or getattr(message, "id", None) != active.message_id
            ):
                await self._respond(interaction, "このアンケートは締め切られています。")
                return
            previous = self._repository.get_answer(user.id)
            if answer is not None and answer not in ANSWERS:
                await self._respond(interaction, "選択肢を確認できませんでした。")
                return
            operation: str
            changed = False
            if answer is None:
                operation = "回答取消"
                if previous is not None:
                    self._repository.remove_answer(user.id)
                    changed = True
            elif previous == answer:
                operation = "同一回答の再選択"
            else:
                operation = "回答追加" if previous is None else "回答変更"
                self._repository.set_answer(user.id, answer)
                changed = True
            if changed:
                try:
                    self._repository.save()
                except Exception:
                    if previous is None:
                        self._repository.remove_answer(user.id)
                    else:
                        self._repository.set_answer(user.id, previous)
                    logger.exception("Failed to save an availability poll answer")
                    await self._respond(interaction, "回答を保存できませんでした。")
                    return
            counts = self._repository.get_counts()
            try:
                await message.edit(
                    embed=self.public_embed(active.poll_id, counts),
                    view=self._view_factory(active.poll_id, False),
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to update an availability poll message")
            await self._respond(
                interaction,
                self._answer_response(previous, answer, counts),
            )
            await self._send_answer_audit(
                interaction=interaction,
                active=active,
                operation=operation,
                previous=previous,
                answer=answer,
                counts=counts,
            )

    def _answer_response(
        self,
        previous: str | None,
        answer: str | None,
        counts: dict[str, int],
    ) -> str:
        if answer is None:
            first = "あしあとを消したよ。" if previous else "あしあとは残っていないよ。"
        elif previous == answer:
            first = "その場所には、もうあしあとを残しているよ🐾"
        elif previous is None:
            first = f"{ICONS[answer]} {LABELS[answer]} にあしあとを残したよ🐾"
        else:
            first = f"{ICONS[answer]} {LABELS[answer]} にあしあとを移したよ🐾"
        results = result_lines(counts, icons=False).replace("\n", " / ")
        return f"{first}\n\n現在の結果：\n{results}"

    @staticmethod
    async def _respond(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def skip_next(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            if self._repository.is_paused():
                message = (
                    "定期投稿は現在停止中だよ。\n"
                    "先に /availability_poll_resume で再開してね。"
                )
                changed = False
            elif self._repository.should_skip_next_run():
                message = "次の定期投稿は、すでにスキップ予定だよ。"
                changed = False
            else:
                self._repository.set_skip_next_run(True)
                try:
                    self._repository.save()
                except Exception:
                    self._repository.set_skip_next_run(False)
                    logger.exception("Failed to save availability poll skip state")
                    raise
                message = (
                    "次の定期投稿だけスキップするよ🐶\n"
                    "その次からは通常どおり投稿するね！"
                )
                changed = True
            await self._respond(interaction, message)
            if changed:
                await self._send_admin_audit(interaction, "次回投稿をスキップ")

    async def stop(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            if self._repository.is_paused():
                await self._respond(interaction, "定期投稿はすでに停止中だよ。")
                return
            previous_next_run = self._repository.get_next_run_at()
            previous_skip = self._repository.should_skip_next_run()
            self._repository.set_paused(True)
            self._repository.set_skip_next_run(False)
            self._repository.set_next_run_at(None)
            try:
                self._repository.save()
            except Exception:
                self._repository.set_paused(False)
                self._repository.set_skip_next_run(previous_skip)
                self._repository.set_next_run_at(previous_next_run)
                logger.exception("Failed to save availability poll paused state")
                raise
            await self._cancel_scheduler()
            await self._respond(
                interaction,
                "「いまひま？」の定期投稿を停止したよ🐶\n"
                "再開するまで新しいアンケートは投稿しないね。",
            )
            logger.info("Availability poll scheduler stopped")
            await self._send_admin_audit(interaction, "定期投稿を停止")

    async def resume(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            if not self._repository.is_paused():
                await self._respond(interaction, "定期投稿はすでに動いているよ。")
                return
            self._repository.set_paused(False)
            self._repository.set_skip_next_run(False)
            next_run = self._choose_next()
            self._repository.set_next_run_at(next_run)
            try:
                self._repository.save()
            except Exception:
                self._repository.set_paused(True)
                self._repository.set_next_run_at(None)
                logger.exception("Failed to save availability poll resumed state")
                raise
            self._replace_scheduler(next_run)
            await self._respond(
                interaction,
                "「いまひま？」の定期投稿を再開したよ🐶\n"
                "次の予定時間から投稿するね！",
            )
            logger.info("Availability poll scheduler resumed")
            await self._send_admin_audit(interaction, "定期投稿を再開")

    async def _cancel_scheduler(self) -> None:
        task = self._scheduler_task
        self._scheduler_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _audit_channel(self) -> Any | None:
        guild = self.bot.get_guild(self._audit_guild_id)
        if guild is None:
            logger.error("Availability poll audit guild is unavailable")
            return None
        channel = guild.get_channel(self._audit_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self._audit_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to resolve the availability poll audit channel")
                return None
        if getattr(getattr(channel, "guild", None), "id", None) != self._audit_guild_id:
            logger.error("Availability poll audit channel belongs to another guild")
            return None
        if not callable(getattr(channel, "send", None)):
            logger.error("Availability poll audit destination is not message-capable")
            return None
        return channel

    async def _send_answer_audit(
        self,
        *,
        interaction: discord.Interaction,
        active: ActivePoll,
        operation: str,
        previous: str | None,
        answer: str | None,
        counts: dict[str, int],
    ) -> None:
        user = interaction.user
        guild_id = getattr(interaction, "guild_id", 0) or getattr(
            getattr(interaction, "guild", None), "id", 0
        )
        link = f"https://discord.com/channels/{guild_id}/{active.channel_id}/{active.message_id}"
        embed = discord.Embed(title="🐾 「いまひま？」回答ログ")
        embed.description = (
            f"操作：{operation}\n回答者：{user.mention}\n"
            f"表示名：{user.display_name}\nUser ID：{user.id}\n\n"
            f"変更前：{LABELS.get(previous, '未回答')}\n"
            f"変更後：{LABELS.get(answer, '未回答')}\n\n"
            f"Poll ID：{active.poll_id}\n"
            f"操作日時：{self._now().astimezone(self._timezone):%Y-%m-%d %H:%M:%S %Z}\n\n"
            f"操作後の集計：\n{result_lines(counts, icons=False)}\n\n"
            f"元メッセージ：{link}"
        )
        await self._send_audit(embed)

    async def _send_admin_audit(
        self,
        interaction: discord.Interaction,
        operation: str,
    ) -> None:
        user = interaction.user
        embed = discord.Embed(
            title="⚙️ 「いまひま？」運用ログ",
            description=(
                f"操作：{operation}\n実行者：{user.mention}\n"
                f"表示名：{user.display_name}\nUser ID：{user.id}\n"
                f"操作日時：{self._now().astimezone(self._timezone):%Y-%m-%d %H:%M:%S %Z}"
            ),
        )
        await self._send_audit(embed)

    async def _send_audit(self, embed: discord.Embed) -> None:
        channel = await self._audit_channel()
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send an availability poll audit event")

    async def shutdown(self) -> None:
        async with self._lock:
            await self._cancel_scheduler()
            logger.info("Availability poll scheduler shut down")
