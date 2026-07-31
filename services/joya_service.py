"""Business logic and state for the Joya bell feature."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import discord

from storage.json_store import load_json_or_default, save_json_atomic

logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def _clamp(value: int, lower: int, upper: int) -> int:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _fmt_mmss(seconds: int) -> str:
    minutes = seconds // 60
    remainder = seconds % 60
    if minutes <= 0:
        return f"{remainder}秒"
    if remainder == 0:
        return f"{minutes}分"
    return f"{minutes}分{remainder}秒"


def _choose_cooldown(min_sec: int, max_sec: int) -> int:
    minimum = _clamp(min_sec, 5, 3600)
    maximum = _clamp(max_sec, 5, 3600)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return random.randint(minimum, maximum)


def _advance_count(count: int) -> tuple[int, bool]:
    next_count = count + 1
    if next_count >= 108:
        return 108, True
    return next_count, False


@dataclass
class _GuildConfig:
    cd_min_sec: int
    cd_max_sec: int


class _JoyaStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, Any] = {"guilds": {}, "users": {}}
        self._load()

    def _load(self) -> None:
        self._data = load_json_or_default(
            self._path,
            {"guilds": {}, "users": {}},
        )

    def save(self) -> None:
        save_json_atomic(self._path, self._data)

    def get_guild(self, guild_id: int) -> dict[str, Any]:
        guilds = self._data.setdefault("guilds", {})
        return guilds.setdefault(str(guild_id), {})

    def get_user(self, guild_id: int, user_id: int) -> dict[str, Any]:
        users = self._data.setdefault("users", {})
        key = f"{guild_id}:{user_id}"
        return users.setdefault(key, {})

    def reset_guild_all(self, guild_id: int) -> int:
        guilds = self._data.setdefault("guilds", {})
        guilds[str(guild_id)] = {}
        users = self._data.setdefault("users", {})
        prefix = f"{guild_id}:"
        keys = [key for key in users if key.startswith(prefix)]
        for key in keys:
            del users[key]
        self.save()
        return len(keys)


class JoyaService:
    """Own Joya state and execute its Discord-facing business workflow."""

    def __init__(
        self,
        bot: Any,
        *,
        data_path: str,
        min_sec: int,
        max_sec: int,
        winner_role_id: int,
        channel_id: int,
        view_factory: Callable[[bool], discord.ui.View],
    ) -> None:
        self.bot = bot
        self._min_env = min_sec
        self._max_env = max_sec
        self._role_id = winner_role_id
        self._channel_id = channel_id
        self._block_role_id = 1451758143636901960
        self._view_factory = view_factory
        self._store = _JoyaStore(data_path)
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    def _get_cfg(self, guild_id: int) -> _GuildConfig:
        guild_state = self._store.get_guild(guild_id)
        minimum = guild_state.get("cd_min_sec")
        maximum = guild_state.get("cd_max_sec")
        if isinstance(minimum, int) and isinstance(maximum, int):
            return _GuildConfig(minimum, maximum)
        return _GuildConfig(self._min_env, self._max_env)

    def _set_cfg(self, guild_id: int, minimum: int, maximum: int) -> None:
        guild_state = self._store.get_guild(guild_id)
        guild_state["cd_min_sec"] = minimum
        guild_state["cd_max_sec"] = maximum
        self._store.save()

    def _reset_cfg(self, guild_id: int) -> None:
        guild_state = self._store.get_guild(guild_id)
        guild_state.pop("cd_min_sec", None)
        guild_state.pop("cd_max_sec", None)
        self._store.save()

    def _get_count_state(self, guild_id: int) -> tuple[int, bool]:
        guild_state = self._store.get_guild(guild_id)
        count = guild_state.get("count", 0)
        finished = guild_state.get("finished", False)
        if not isinstance(count, int):
            count = 0
        if not isinstance(finished, bool):
            finished = False
        return count, finished

    def _set_count_state(
        self,
        guild_id: int,
        count: int,
        finished: bool,
        winner_id: int | None = None,
    ) -> None:
        guild_state = self._store.get_guild(guild_id)
        guild_state["count"] = count
        guild_state["finished"] = finished
        if winner_id is not None:
            guild_state["winner_user_id"] = winner_id
            guild_state["finished_at"] = _now_ts()
        self._store.save()

    def _cooldown_left(self, guild_id: int, user_id: int) -> int:
        user_state = self._store.get_user(guild_id, user_id)
        next_timestamp = user_state.get("next_ts", 0)
        if not isinstance(next_timestamp, int):
            return 0
        return max(0, next_timestamp - _now_ts())

    def _set_cooldown(self, guild_id: int, user_id: int, seconds: int) -> None:
        user_state = self._store.get_user(guild_id, user_id)
        user_state["next_ts"] = _now_ts() + seconds

    @staticmethod
    def _is_zorome(number: int) -> bool:
        text = str(number)
        return len(text) >= 2 and len(set(text)) == 1

    def _minor_fx(self, number: int) -> str | None:
        if number in (1, 2, 3):
            return "（まだ鳴る。まだ戻れる。）"
        if number == 50:
            return "（半分、来た。）"
        if number == 100:
            return "（あと8回。空気が変わった。）"
        if number % 25 == 0:
            return "（区切り、ひとつ。）"
        if number % 10 == 0:
            return "（節目の響き。）"
        if self._is_zorome(number):
            return "（ぞろ目。妙に気持ちいい。）"
        return None

    def _normal_msg(self, number: int, cooldown: int) -> str:
        effect = self._minor_fx(number)
        line = f"**{number}回目！** ゴーン！ 🔔（次は {_fmt_mmss(cooldown)}）"
        if effect:
            return f"{line}\n{effect}"
        return line

    @staticmethod
    def _final_embed(member: discord.Member) -> discord.Embed:
        embed = discord.Embed(
            title="🔔 108回目 —— 除夜の鐘、成就",
            description=(
                f"{member.mention} が最後の鐘を鳴らした。\n"
                "煩悩は、いったん散った。…たぶん。"
            ),
        )
        embed.add_field(name="結果", value="**108 / 108**", inline=True)
        embed.add_field(name="称号", value="**除夜の鐘奉行**", inline=True)
        embed.set_footer(text="今年も生き延びたな。")
        return embed

    async def _disable_panel_if_any(self, guild: discord.Guild) -> None:
        guild_state = self._store.get_guild(guild.id)
        channel_id = guild_state.get("panel_channel_id")
        message_id = guild_state.get("panel_message_id")
        if not isinstance(channel_id, int) or not isinstance(message_id, int):
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            logger.exception("Failed to fetch the Joya panel message")
            return
        try:
            await message.edit(
                content="🔔 **除夜の鐘（終了）**\n108回、鳴り切った。",
                view=self._view_factory(True),
            )
        except Exception:
            logger.exception("Failed to disable the Joya panel")

    def _has_block_role(self, member: discord.Member) -> bool:
        return any(role.id == self._block_role_id for role in member.roles)

    async def handle_joya(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not interaction.user:
            if interaction.response.is_done():
                await interaction.followup.send("サーバー内で使ってね。", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "サーバー内で使ってね。", ephemeral=True
                )
            return

        if not interaction.response.is_done():
            await interaction.response.defer()

        guild_id = interaction.guild.id
        user_id = interaction.user.id
        async with self._lock(guild_id):
            count, finished = self._get_count_state(guild_id)
            if finished:
                guild_state = self._store.get_guild(guild_id)
                winner = guild_state.get("winner_user_id")
                message = "もう108回、鳴り切った。"
                if isinstance(winner, int):
                    message += f" 最後は <@{winner}>。"
                await interaction.followup.send(message)
                return

            member = interaction.guild.get_member(user_id)
            if not isinstance(member, discord.Member):
                await interaction.followup.send(
                    "メンバー情報が取れない。もう一回押して。"
                )
                return

            if count == 107 and self._has_block_role(member):
                await interaction.followup.send(
                    f"{member.mention}\n"
                    "なぜだろう、不思議な力で阻まれて"
                    "鐘を鳴らせない……。"
                )
                return

            remaining = self._cooldown_left(guild_id, user_id)
            if remaining > 0:
                await interaction.followup.send(
                    f"まだ早い。あと **{_fmt_mmss(remaining)}** 待て。⏳",
                    ephemeral=True,
                )
                return

            config = self._get_cfg(guild_id)
            cooldown = _choose_cooldown(config.cd_min_sec, config.cd_max_sec)
            self._set_cooldown(guild_id, user_id, cooldown)
            self._store.save()

            count, finished = _advance_count(count)
            if not finished:
                self._set_count_state(guild_id, count, False)
                await interaction.followup.send(self._normal_msg(count, cooldown))
                return

            self._set_count_state(guild_id, 108, True, user_id)
            await self._disable_panel_if_any(interaction.guild)

            role = interaction.guild.get_role(self._role_id)
            if role is None:
                await interaction.followup.send(
                    embed=self._final_embed(member),
                    content="※ 指定されたロールIDが見つからない。",
                )
                return

            try:
                await member.add_roles(role, reason="Joya 108th winner")
            except discord.Forbidden:
                logger.exception("Failed to assign the Joya winner role")
                await interaction.followup.send(
                    embed=self._final_embed(member),
                    content=(
                        "※ロール付与権限がない。"
                        "Botロールを対象ロールより上に。"
                    ),
                )
                return

            await interaction.followup.send(embed=self._final_embed(member))

    async def post_panel(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        if self._channel_id <= 0:
            await interaction.response.send_message(
                "JOYA_CHANNEL_ID が未設定。", ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(self._channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "指定チャンネルが見つからない。", ephemeral=True
            )
            return

        _count, finished = self._get_count_state(interaction.guild.id)
        if finished:
            message = await channel.send(
                "🔔 **除夜の鐘（終了）**\n108回、鳴り切った。",
                view=self._view_factory(True),
            )
        else:
            message = await channel.send(
                "🔔 **除夜の鐘**",
                view=self._view_factory(False),
            )

        guild_state = self._store.get_guild(interaction.guild.id)
        guild_state["panel_channel_id"] = channel.id
        guild_state["panel_message_id"] = message.id
        self._store.save()
        await interaction.response.send_message("投稿した。", ephemeral=True)

    async def send_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        guild_id = interaction.guild.id
        count, finished = self._get_count_state(guild_id)
        config = self._get_cfg(guild_id)
        guild_state = self._store.get_guild(guild_id)
        panel_channel = guild_state.get("panel_channel_id")
        panel_message = guild_state.get("panel_message_id")
        message = (
            f"🔔 現在: **{count} / 108**\n"
            f"⏱ クールダウン: **{_fmt_mmss(config.cd_min_sec)}"
            f" 〜 {_fmt_mmss(config.cd_max_sec)}**\n"
            f"🏷 ロールID: **{self._role_id}**\n"
            f"🛑 ブロックロールID: **{self._block_role_id}**\n"
            f"📍 パネルch: **{panel_channel if isinstance(panel_channel, int) else '未'}**\n"
            f"🧷 パネルmsg: **{panel_message if isinstance(panel_message, int) else '未'}**"
        )
        if finished:
            winner = guild_state.get("winner_user_id")
            if isinstance(winner, int):
                message += f"\n✅ 終了：最後は <@{winner}>"
        await interaction.response.send_message(message, ephemeral=True)

    async def configure(
        self,
        interaction: discord.Interaction,
        min_minutes: int,
        max_minutes: int,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        minimum = int(min_minutes) * 60
        maximum = int(max_minutes) * 60
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        self._set_cfg(interaction.guild.id, minimum, maximum)
        await interaction.response.send_message(
            f"設定した。**{_fmt_mmss(minimum)} 〜 {_fmt_mmss(maximum)}**。",
            ephemeral=True,
        )

    async def reset_config(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        self._reset_cfg(interaction.guild.id)
        await interaction.response.send_message(
            f"戻した。**{_fmt_mmss(self._min_env)} 〜 "
            f"{_fmt_mmss(self._max_env)}**。",
            ephemeral=True,
        )

    async def reset_all(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        guild_id = interaction.guild.id
        async with self._lock(guild_id):
            removed = self._store.reset_guild_all(guild_id)
        await interaction.response.send_message(
            f"完全リセットした。クールダウン情報 {removed} 件を削除。",
            ephemeral=True,
        )
