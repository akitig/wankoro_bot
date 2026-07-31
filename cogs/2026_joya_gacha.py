import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Callable

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from storage.json_store import load_json_or_default, save_json_atomic


def _now_ts() -> int:
    return int(time.time())


def _clamp(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _fmt_mmss(sec: int) -> str:
    m = sec // 60
    s = sec % 60
    if m <= 0:
        return f"{s}秒"
    if s == 0:
        return f"{m}分"
    return f"{m}分{s}秒"


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


def _only_user(user_id: int) -> Callable[[discord.Interaction], bool]:
    def _pred(interaction: discord.Interaction) -> bool:
        return bool(interaction.user and interaction.user.id == user_id)
    return _pred


@dataclass
class _GuildConfig:
    cd_min_sec: int
    cd_max_sec: int


class _JoyaStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: Dict[str, Any] = {"guilds": {}, "users": {}}
        self._load()

    def _load(self) -> None:
        self._data = load_json_or_default(
            self._path,
            {"guilds": {}, "users": {}},
        )

    def save(self) -> None:
        save_json_atomic(self._path, self._data)

    def get_guild(self, guild_id: int) -> Dict[str, Any]:
        g = self._data.setdefault("guilds", {})
        return g.setdefault(str(guild_id), {})

    def get_user(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        u = self._data.setdefault("users", {})
        key = f"{guild_id}:{user_id}"
        return u.setdefault(key, {})

    def reset_guild_all(self, guild_id: int) -> int:
        g = self._data.setdefault("guilds", {})
        g[str(guild_id)] = {}
        u = self._data.setdefault("users", {})
        prefix = f"{guild_id}:"
        keys = [k for k in u.keys() if k.startswith(prefix)]
        for k in keys:
            del u[k]
        self.save()
        return len(keys)


class JoyaView(discord.ui.View):
    def __init__(self, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="🔔 除夜の鐘を鳴らす",
        style=discord.ButtonStyle.primary,
        custom_id="joya:ring",
    )
    async def ring(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        cog = interaction.client.get_cog("JoyaGacha")
        if not isinstance(cog, JoyaGacha):
            await interaction.response.send_message(
                "Cogが見つからない。管理者に連絡して。",
                ephemeral=True,
            )
            return
        await cog.handle_joya(interaction)


class JoyaGacha(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self._min_env = config.joya_min_sec
        self._max_env = config.joya_max_sec
        self._role_id = config.joya_winner_role_id
        self._channel_id = config.joya_channel_id
        self._block_role_id = 1451758143636901960
        self._store = _JoyaStore(config.joya_data_path)
        self._locks: Dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        self.bot.add_view(JoyaView())

    def _lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    def _get_cfg(self, guild_id: int) -> _GuildConfig:
        g = self._store.get_guild(guild_id)
        mn = g.get("cd_min_sec")
        mx = g.get("cd_max_sec")
        if isinstance(mn, int) and isinstance(mx, int):
            return _GuildConfig(mn, mx)
        return _GuildConfig(self._min_env, self._max_env)

    def _set_cfg(self, guild_id: int, mn: int, mx: int) -> None:
        g = self._store.get_guild(guild_id)
        g["cd_min_sec"] = mn
        g["cd_max_sec"] = mx
        self._store.save()

    def _reset_cfg(self, guild_id: int) -> None:
        g = self._store.get_guild(guild_id)
        g.pop("cd_min_sec", None)
        g.pop("cd_max_sec", None)
        self._store.save()

    def _get_count_state(self, guild_id: int) -> Tuple[int, bool]:
        g = self._store.get_guild(guild_id)
        count = g.get("count", 0)
        finished = g.get("finished", False)
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
        winner_id: Optional[int] = None,
    ) -> None:
        g = self._store.get_guild(guild_id)
        g["count"] = count
        g["finished"] = finished
        if winner_id is not None:
            g["winner_user_id"] = winner_id
            g["finished_at"] = _now_ts()
        self._store.save()

    def _cooldown_left(self, guild_id: int, user_id: int) -> int:
        u = self._store.get_user(guild_id, user_id)
        nxt = u.get("next_ts", 0)
        if not isinstance(nxt, int):
            return 0
        left = nxt - _now_ts()
        if left < 0:
            return 0
        return left

    def _set_cooldown(self, guild_id: int, user_id: int, sec: int) -> None:
        u = self._store.get_user(guild_id, user_id)
        u["next_ts"] = _now_ts() + sec

    def _is_zorome(self, n: int) -> bool:
        s = str(n)
        return len(s) >= 2 and len(set(s)) == 1

    def _minor_fx(self, n: int) -> Optional[str]:
        if n in (1, 2, 3):
            return "（まだ鳴る。まだ戻れる。）"
        if n == 50:
            return "（半分、来た。）"
        if n == 100:
            return "（あと8回。空気が変わった。）"
        if n % 25 == 0:
            return "（区切り、ひとつ。）"
        if n % 10 == 0:
            return "（節目の響き。）"
        if self._is_zorome(n):
            return "（ぞろ目。妙に気持ちいい。）"
        return None

    def _normal_msg(self, n: int, cd: int) -> str:
        fx = self._minor_fx(n)
        line = f"**{n}回目！** ゴーン！ 🔔（次は {_fmt_mmss(cd)}）"
        if fx:
            return f"{line}\n{fx}"
        return line

    def _final_embed(self, member: discord.Member) -> discord.Embed:
        e = discord.Embed(
            title="🔔 108回目 —— 除夜の鐘、成就",
            description=(
                f"{member.mention} が最後の鐘を鳴らした。\n"
                "煩悩は、いったん散った。…たぶん。"
            ),
        )
        e.add_field(name="結果", value="**108 / 108**", inline=True)
        e.add_field(name="称号", value="**除夜の鐘奉行**", inline=True)
        e.set_footer(text="今年も生き延びたな。")
        return e

    async def _disable_panel_if_any(self, guild: discord.Guild) -> None:
        g = self._store.get_guild(guild.id)
        ch_id = g.get("panel_channel_id")
        msg_id = g.get("panel_message_id")
        if not isinstance(ch_id, int) or not isinstance(msg_id, int):
            return
        ch = guild.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            msg = await ch.fetch_message(msg_id)
        except Exception:
            return
        try:
            await msg.edit(
                content="🔔 **除夜の鐘（終了）**\n108回、鳴り切った。",
                view=JoyaView(disabled=True),
            )
        except Exception:
            return

    def _has_block_role(self, member: discord.Member) -> bool:
        for r in member.roles:
            if r.id == self._block_role_id:
                return True
        return False

    async def handle_joya(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not interaction.user:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "サーバー内で使ってね。", ephemeral=True
                )
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
                g = self._store.get_guild(guild_id)
                win = g.get("winner_user_id")
                msg = "もう108回、鳴り切った。"
                if isinstance(win, int):
                    msg += f" 最後は <@{win}>。"
                await interaction.followup.send(msg)
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

            left = self._cooldown_left(guild_id, user_id)
            if left > 0:
                await interaction.followup.send(
                    f"まだ早い。あと **{_fmt_mmss(left)}** 待て。⏳",
                    ephemeral=True,
                )
                return

            cfg = self._get_cfg(guild_id)
            cd = _choose_cooldown(cfg.cd_min_sec, cfg.cd_max_sec)
            self._set_cooldown(guild_id, user_id, cd)
            self._store.save()

            count, finished = _advance_count(count)
            if not finished:
                self._set_count_state(guild_id, count, False)
                await interaction.followup.send(self._normal_msg(count, cd))
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
                await interaction.followup.send(
                    embed=self._final_embed(member),
                    content=(
                        "※ロール付与権限がない。"
                        "Botロールを対象ロールより上に。"
                    ),
                )
                return

            await interaction.followup.send(embed=self._final_embed(member))

    @app_commands.command(name="joya", description="除夜の鐘を1回鳴らす")
    async def joya(self, interaction: discord.Interaction) -> None:
        await self.handle_joya(interaction)

    @app_commands.command(
        name="joya_panel",
        description="除夜の鐘ボタンを.env指定チャンネルに投稿",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def joya_panel(self, interaction: discord.Interaction) -> None:
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
        ch = interaction.guild.get_channel(self._channel_id)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(
                "指定チャンネルが見つからない。", ephemeral=True
            )
            return

        count, finished = self._get_count_state(interaction.guild.id)
        if finished:
            msg = await ch.send(
                "🔔 **除夜の鐘（終了）**\n108回、鳴り切った。",
                view=JoyaView(disabled=True),
            )
        else:
            msg = await ch.send("🔔 **除夜の鐘**", view=JoyaView())

        g = self._store.get_guild(interaction.guild.id)
        g["panel_channel_id"] = ch.id
        g["panel_message_id"] = msg.id
        self._store.save()

        await interaction.response.send_message("投稿した。", ephemeral=True)

    @app_commands.command(
        name="joya_status",
        description="現在の回数と設定を表示",
    )
    async def joya_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        guild_id = interaction.guild.id
        count, finished = self._get_count_state(guild_id)
        cfg = self._get_cfg(guild_id)

        g = self._store.get_guild(guild_id)
        pch = g.get("panel_channel_id")
        pmsg = g.get("panel_message_id")

        msg = (
            f"🔔 現在: **{count} / 108**\n"
            f"⏱ クールダウン: **{_fmt_mmss(cfg.cd_min_sec)}"
            f" 〜 {_fmt_mmss(cfg.cd_max_sec)}**\n"
            f"🏷 ロールID: **{self._role_id}**\n"
            f"🛑 ブロックロールID: **{self._block_role_id}**\n"
            f"📍 パネルch: **{pch if isinstance(pch, int) else '未'}**\n"
            f"🧷 パネルmsg: **{pmsg if isinstance(pmsg, int) else '未'}**"
        )
        if finished:
            win = g.get("winner_user_id")
            if isinstance(win, int):
                msg += f"\n✅ 終了：最後は <@{win}>"
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(
        name="joya_config",
        description="クールダウン最短/最長を設定（分）",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_config(
        self,
        interaction: discord.Interaction,
        min_minutes: app_commands.Range[int, 1, 120],
        max_minutes: app_commands.Range[int, 1, 120],
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        mn = int(min_minutes) * 60
        mx = int(max_minutes) * 60
        if mn > mx:
            mn, mx = mx, mn
        self._set_cfg(interaction.guild.id, mn, mx)
        await interaction.response.send_message(
            f"設定した。**{_fmt_mmss(mn)} 〜 {_fmt_mmss(mx)}**。",
            ephemeral=True,
        )

    @app_commands.command(
        name="joya_config_reset",
        description="クールダウン設定を.envの値に戻す",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_config_reset(self, interaction: discord.Interaction) -> None:
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

    @app_commands.command(
        name="joya_reset_all",
        description="除夜の鐘の状態を完全リセット（回数/勝者/CD/パネル情報）",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_reset_all(self, interaction: discord.Interaction) -> None:
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

    @joya_panel.error
    @joya_config.error
    @joya_config_reset.error
    @joya_reset_all.error
    async def _cmd_err(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "実行できない（許可ユーザーのみ）。",
                ephemeral=True,
            )
            return
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "権限が足りない。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "エラーが出た。ログを見てくれ。",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JoyaGacha(bot))
