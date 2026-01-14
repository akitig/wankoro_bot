import asyncio
import json
import os
import random
from dataclasses import dataclass
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands


def _get_env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _get_env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


@dataclass
class t_omikuji_env:
    rest_vc_id: int
    resetter_user_id: int
    panel_channel_id: int
    points_path: str


def _load_env() -> t_omikuji_env:
    default_path = os.path.join("data", "2026_omikujii_points.json")
    return t_omikuji_env(
        rest_vc_id=_get_env_int("OMIKUJI_REST_VC_ID", 0),
        resetter_user_id=_get_env_int("OMIKUJI_RESETTER_USER_ID", 0),
        panel_channel_id=_get_env_int("OMIKUJI_PANEL_CHANNEL_ID", 0),
        points_path=_get_env_str("OMIKUJI_POINTS_PATH", default_path),
    )


class OmikujiStore:
    def __init__(self, path: str):
        self._path = path
        self._lock = asyncio.Lock()
        self._points: Dict[str, int] = {}

    def _ensure_dir(self) -> None:
        d = os.path.dirname(self._path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    async def load(self) -> None:
        async with self._lock:
            self._ensure_dir()
            if not os.path.exists(self._path):
                self._points = {}
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._points = {
                        str(k): int(v) for k, v in data.items()
                        if str(k).isdigit()
                    }
                else:
                    self._points = {}
            except (OSError, ValueError, TypeError):
                self._points = {}

    async def save(self) -> None:
        async with self._lock:
            self._ensure_dir()
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._points, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)

    async def get(self, user_id: int) -> int:
        async with self._lock:
            key = str(user_id)
            return int(self._points.get(key, 0))

    async def ensure_initial(self, user_id: int, initial: int) -> None:
        async with self._lock:
            key = str(user_id)
            if key not in self._points:
                self._points[key] = int(initial)

    async def add(self, user_id: int, delta: int) -> int:
        async with self._lock:
            key = str(user_id)
            cur = int(self._points.get(key, 0))
            cur += int(delta)
            if cur < 0:
                cur = 0
            self._points[key] = cur
            return cur

    async def reset_all(self, initial: int) -> int:
        async with self._lock:
            keys = list(self._points.keys())
            for k in keys:
                self._points[k] = int(initial)
            return len(keys)


class OmikujiView(discord.ui.View):
    def __init__(self, cog: "OmikujiGachaCog"):
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(
        label="🎴 おみくじを引く（50pt）",
        style=discord.ButtonStyle.primary,
        custom_id="omikuji:draw_2026",
    )
    async def draw_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.handle_draw(interaction)

    @discord.ui.button(
        label="💰 ポイント確認",
        style=discord.ButtonStyle.secondary,
        custom_id="omikuji:points_2026",
    )
    async def points_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.handle_points(interaction)


class OmikujiGachaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.env = _load_env()
        self.store = OmikujiStore(self.env.points_path)
        self._task: Optional[asyncio.Task] = None
        self._view = OmikujiView(self)

    async def cog_load(self) -> None:
        await self.store.load()
        self.bot.add_view(self._view)
        if self._task is None:
            self._task = asyncio.create_task(self._vc_tick_loop())

    async def cog_unload(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _is_countable_vc(self, channel: Optional[discord.VoiceChannel]) -> bool:
        if channel is None:
            return False
        if self.env.rest_vc_id and channel.id == self.env.rest_vc_id:
            return False
        return True

    async def _vc_tick_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._tick_vc_points()
            except Exception:
                pass
            await asyncio.sleep(60)

    async def _tick_vc_points(self) -> None:
        guilds = list(self.bot.guilds)
        for g in guilds:
            for vc in getattr(g, "voice_channels", []):
                if not self._is_countable_vc(vc):
                    continue
                for m in vc.members:
                    if m.bot:
                        continue
                    await self.store.ensure_initial(m.id, 500)
                    await self.store.add(m.id, 1)
        await self.store.save()

    def _draw_omikuji(self) -> str:
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
        for name, w in table:
            pool.extend([name] * w)
        return random.choice(pool)

    async def handle_points(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        await self.store.ensure_initial(interaction.user.id, 500)
        pts = await self.store.get(interaction.user.id)
        await self.store.save()
        await interaction.response.send_message(
            f"あなたのポイント：**{pts}pt**",
            ephemeral=True,
        )

    async def handle_draw(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        await self.store.ensure_initial(interaction.user.id, 500)
        pts = await self.store.get(interaction.user.id)
        if pts < 50:
            await interaction.response.send_message(
                f"ポイント不足です（必要：50pt / 現在：{pts}pt）",
                ephemeral=True,
            )
            return
        remain = await self.store.add(interaction.user.id, -50)
        result = self._draw_omikuji()
        await self.store.save()

        embed = discord.Embed(
            title="🎍 初春おみくじ（2026）",
            description=f"結果：**{result}**",
        )
        embed.add_field(name="残りポイント", value=f"{remain}pt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _is_resetter(self, user: discord.abc.User) -> bool:
        if self.env.resetter_user_id == 0:
            return False
        return user.id == self.env.resetter_user_id

    @app_commands.command(
        name="omikuji_panel",
        description="初春おみくじガチャのパネルを指定チャンネルに投稿します",
    )
    async def omikuji_panel(self, interaction: discord.Interaction) -> None:
        ch_id = self.env.panel_channel_id
        if ch_id == 0:
            await interaction.response.send_message(
                "OMIKUJI_PANEL_CHANNEL_ID が未設定です。",
                ephemeral=True,
            )
            return
        ch = self.bot.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(
                "パネル投稿先チャンネルが見つかりません。",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🎴 初春おみくじガチャ（2026）",
            description="ボタンから引けます（1回 50pt）\nVCに1分いると+1pt。",
        )
        await ch.send(embed=embed, view=self._view)
        await interaction.response.send_message(
            f"パネルを投稿しました：{ch.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="omikuji_reset_points",
        description="全員のポイントを初期値（500pt）にリセットします（指定ユーザーのみ）",
    )
    async def omikuji_reset_points(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or not self._is_resetter(interaction.user):
            await interaction.response.send_message(
                "このコマンドを実行する権限がありません。",
                ephemeral=True,
            )
            return
        n = await self.store.reset_all(500)
        await self.store.save()
        await interaction.response.send_message(
            f"ポイントをリセットしました（対象：{n}人 / 500pt）。",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OmikujiGachaCog(bot))