"""Business logic and state for the Omikuji feature."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import discord

from storage.json_store import load_json_or_default, save_json_atomic

logger = logging.getLogger(__name__)


class OmikujiService:
    """Own Omikuji points and execute its Discord-facing workflow."""

    def __init__(
        self,
        bot: Any,
        *,
        points_path: str,
        rest_vc_id: int,
        resetter_user_id: int,
        panel_channel_id: int,
    ) -> None:
        self.bot = bot
        self._points_path = points_path
        self._rest_vc_id = rest_vc_id
        self._resetter_user_id = resetter_user_id
        self._panel_channel_id = panel_channel_id
        self._lock = asyncio.Lock()
        self._points: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None

    async def load(self) -> None:
        async with self._lock:
            data = load_json_or_default(self._points_path, {})
            if isinstance(data, dict):
                self._points = {
                    str(key): int(value)
                    for key, value in data.items()
                    if str(key).isdigit()
                }
            else:
                self._points = {}

    async def save(self) -> None:
        async with self._lock:
            save_json_atomic(self._points_path, self._points)

    async def get_points(self, user_id: int) -> int:
        async with self._lock:
            return int(self._points.get(str(user_id), 0))

    async def ensure_initial_points(self, user_id: int, initial: int) -> None:
        async with self._lock:
            key = str(user_id)
            if key not in self._points:
                self._points[key] = int(initial)

    async def add_points(self, user_id: int, delta: int) -> int:
        async with self._lock:
            key = str(user_id)
            points = int(self._points.get(key, 0)) + int(delta)
            if points < 0:
                points = 0
            self._points[key] = points
            return points

    async def reset_all_points(self, initial: int) -> int:
        async with self._lock:
            keys = list(self._points)
            for key in keys:
                self._points[key] = int(initial)
            return len(keys)

    @staticmethod
    def _draw_omikuji() -> str:
        table = [
            ("大吉", 6),
            ("中吉", 14),
            ("小吉", 22),
            ("吉", 26),
            ("末吉", 20),
            ("凶", 10),
            ("大凶", 2),
        ]
        pool = []
        for name, weight in table:
            pool.extend([name] * weight)
        return random.choice(pool)

    def _is_countable_vc(self, channel: discord.VoiceChannel | None) -> bool:
        if channel is None:
            return False
        if self._rest_vc_id and channel.id == self._rest_vc_id:
            return False
        return True

    async def tick_vc_points(self) -> None:
        guilds = list(self.bot.guilds)
        for guild in guilds:
            for voice_channel in getattr(guild, "voice_channels", []):
                if not self._is_countable_vc(voice_channel):
                    continue
                for member in voice_channel.members:
                    if member.bot:
                        continue
                    await self.ensure_initial_points(member.id, 500)
                    await self.add_points(member.id, 1)
        await self.save()

    async def _vc_tick_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.tick_vc_points()
            except Exception:
                logger.exception("Omikuji VC point update failed")
            await asyncio.sleep(60)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._vc_tick_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def handle_points(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        await self.ensure_initial_points(interaction.user.id, 500)
        points = await self.get_points(interaction.user.id)
        await self.save()
        await interaction.response.send_message(
            f"あなたのポイント：**{points}pt**",
            ephemeral=True,
        )

    async def handle_draw(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        await self.ensure_initial_points(interaction.user.id, 500)
        points = await self.get_points(interaction.user.id)
        if points < 50:
            await interaction.response.send_message(
                f"ポイント不足です（必要：50pt / 現在：{points}pt）",
                ephemeral=True,
            )
            return
        remaining = await self.add_points(interaction.user.id, -50)
        result = self._draw_omikuji()
        await self.save()

        embed = discord.Embed(
            title="🎍 初春おみくじ（2026）",
            description=f"結果：**{result}**",
        )
        embed.add_field(name="残りポイント", value=f"{remaining}pt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def post_panel(
        self,
        interaction: discord.Interaction,
        view: discord.ui.View,
    ) -> None:
        if self._panel_channel_id == 0:
            await interaction.response.send_message(
                "OMIKUJI_PANEL_CHANNEL_ID が未設定です。",
                ephemeral=True,
            )
            return
        channel = self.bot.get_channel(self._panel_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "パネル投稿先チャンネルが見つかりません。",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🎴 初春おみくじガチャ（2026）",
            description="ボタンから引けます（1回 50pt）\nVCに1分いると+1pt。",
        )
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"パネルを投稿しました：{channel.mention}",
            ephemeral=True,
        )

    def _is_resetter(self, user: discord.abc.User) -> bool:
        if self._resetter_user_id == 0:
            return False
        return user.id == self._resetter_user_id

    async def reset_points(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or not self._is_resetter(interaction.user):
            await interaction.response.send_message(
                "このコマンドを実行する権限がありません。",
                ephemeral=True,
            )
            return
        count = await self.reset_all_points(500)
        await self.save()
        await interaction.response.send_message(
            f"ポイントをリセットしました（対象：{count}人 / 500pt）。",
            ephemeral=True,
        )
