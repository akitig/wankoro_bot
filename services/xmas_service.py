"""Business logic and state for the Xmas gacha feature."""

from __future__ import annotations

import asyncio
import csv
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import discord

from repositories.xmas_repository import STATE_NONE, XmasRepository

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

CLOSED_MESSAGES_MAIN = [
    "まだクリスマスの気分かい？\n街はもう、いつもの顔に戻ってる。",
    "ベルの音は、もう聞こえない。\n静かな朝だよ。",
    "その灯は、昨日までのもの。\n今はしまわれている。",
    "プレゼントの時間は終わった。\n残ってるのは、記憶だけ。",
    "雪は溶けて、名前も元に戻る頃。",
    "少し遅かったみたいだね。\nクリスマスは昨日まで。",
    "もう引けない。\nでも、引こうとした気持ちは残る。",
]

CLOSED_MESSAGES_NEXT_YEAR = [
    "来年、また会おう。\n灯はその時まで取っておく。",
    "今年はここまで。\n続きは、来年のクリスマスに。",
    "ベルはまた鳴る。\n一年後、同じ場所で。",
]


@dataclass(frozen=True)
class t_reward:
    weight: int
    rarity: str
    icon: str
    title: str
    name: str
    desc: str


class XmasService:
    """Own Xmas state and execute the Discord-facing business workflow."""

    def __init__(
        self,
        bot: Any,
        *,
        csv_path: Path,
        state_path: Path,
        channel_id: int,
        cutoff: str,
        panel_view_factory: Callable[[], discord.ui.View],
        result_view_factory: Callable[[], discord.ui.View],
    ) -> None:
        self.bot = bot
        self._csv_path = csv_path
        self._channel_id = channel_id
        self._cutoff_raw = cutoff
        self._panel_view_factory = panel_view_factory
        self._result_view_factory = result_view_factory
        self._repository = XmasRepository(state_path)
        self._repository.load()
        self._rewards: list[t_reward] = []

    def read_csv_rewards(self) -> list[t_reward]:
        if not self._csv_path.exists():
            self._rewards = []
            return self._rewards
        rewards: list[t_reward] = []
        with self._csv_path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    weight = int(str(row.get("weight", "")).strip())
                except ValueError:
                    continue
                rarity = str(row.get("rarity", "")).strip()
                icon = str(row.get("icon", "")).strip()
                title = str(row.get("title", "")).strip()
                name = str(row.get("name", "")).strip()
                description = str(row.get("desc", "")).strip()
                if weight <= 0 or not rarity or not title or not name:
                    continue
                rewards.append(
                    t_reward(weight, rarity, icon, title, name, description)
                )
        self._rewards = rewards
        return self._rewards

    @staticmethod
    def pick_reward(rewards: list[t_reward]) -> t_reward | None:
        if not rewards:
            return None
        weights = [reward.weight for reward in rewards]
        return random.choices(rewards, weights=weights, k=1)[0]

    def _parse_cutoff(self) -> datetime:
        try:
            cutoff = datetime.fromisoformat(self._cutoff_raw)
            if cutoff.tzinfo is not None:
                return cutoff
        except ValueError:
            pass
        if ZoneInfo is not None:
            return datetime(2025, 12, 26, 7, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        return datetime(2025, 12, 26, 7, 0, 0)

    @staticmethod
    def _now_jst() -> datetime:
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo("Asia/Tokyo"))
        return datetime.now()

    def is_closed(self) -> bool:
        cutoff = self._parse_cutoff()
        now = self._now_jst()
        if cutoff.tzinfo is None or now.tzinfo is None:
            return now >= cutoff
        return now >= cutoff

    @staticmethod
    def _rarity_color(rarity: str) -> int:
        if rarity == "UR":
            return 0xFFD700
        if rarity == "SR":
            return 0xC77DFF
        if rarity == "R":
            return 0x4D96FF
        return 0x9AA0A6

    def panel_embed(self) -> discord.Embed:
        cutoff_str = self._parse_cutoff().strftime("%m/%d %H:%M")
        embed = discord.Embed(
            title="🎄 灯麗会｜クリスマス贈り物ガチャ 🎄",
            description=(
                "12/24 と 12/25。\n"
                "なんか街がやたら光ってて、みんなちょっとだけ浮つく日。\n"
                "こういう日は「贈り物」も勝手に増えるらしい。\n\n"
                "というわけで灯麗会にも、こっそり **クリスマス贈り物ガチャ** 置いときました。\n\n"
                "ボタンを押すだけで、\n"
                "あったかい一言 / 季節のちいさなラッキー / "
                "サンタの落とし物みたいな謎アイテム…\n"
                "“クリスマスっぽい何か”が1つあなたに届きます。\n\n"
                "たま〜に **UR（やばいやつ）** も出る。\n"
                "1回だけでも、連打でも、気分でどうぞ。\n\n"
                "▼ レアリティ\n\n"
                "UR：とびきり特別なクリスマスギフト\n"
                "SR：季節がくれたご褒美\n"
                "R：ちょい嬉しい小物\n"
                "N：日常に小さく灯るやつ\n\n"
                f"⏳ **締切：{cutoff_str}（JST）以降は引けません**\n"
                "結果は **本人にだけ** 見えます。\n\n"
                "では、良いクリスマスを。🎁"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text="元に戻せるよ")
        return embed

    @staticmethod
    def _base_name(name: str) -> str:
        base = name.strip()
        if "＠" in base:
            base = base.split("＠", 1)[0].strip()
        if "@" in base:
            base = base.split("@", 1)[0].strip()
        if not base:
            return "unknown"
        return base

    @classmethod
    def _make_gacha_nick(cls, display_name: str, alias: str) -> str:
        base = cls._base_name(display_name)
        aka = alias.strip() if alias else "無名"
        return f"{base}＠{aka}"[:32]

    def _save_orig_once(
        self,
        guild_id: int,
        user_id: int,
        member: discord.Member,
    ) -> None:
        if member.nick is None:
            self._repository.save_original_nickname(guild_id, user_id, None)
            return
        self._repository.save_original_nickname(
            guild_id,
            user_id,
            self._base_name(member.nick),
        )

    @staticmethod
    async def _try_set_nick(member: discord.Member, nick: str | None) -> bool:
        try:
            await member.edit(nick=nick, reason="Xmas gacha nickname")
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to update an Xmas nickname")
            return False

    @staticmethod
    def closed_embed() -> discord.Embed:
        if random.random() < 0.1:
            message = random.choice(CLOSED_MESSAGES_NEXT_YEAR)
        else:
            message = random.choice(CLOSED_MESSAGES_MAIN)
        embed = discord.Embed(
            title="🎄 クリスマスは終わった",
            description=message,
            color=0x2B2B2B,
        )
        embed.set_footer(text="また来年")
        return embed

    async def revert(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        guild_id = interaction.guild.id
        user_id = interaction.user.id
        original = self._repository.get_original_nickname(guild_id, user_id)
        if original is None:
            current = interaction.user.nick or ""
            base = self._base_name(current) if current else ""
            if "＠" in current or "@" in current:
                changed = await self._try_set_nick(interaction.user, base or None)
                if changed:
                    await interaction.response.send_message(
                        "🎄まほうはおしまい🎄（復元で戻した）", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "権限の都合で戻せなかった…！", ephemeral=True
                    )
                return
            await interaction.response.send_message(
                "戻す元の名前が見つからなかった…！", ephemeral=True
            )
            return
        target = None if original == STATE_NONE else original
        changed = await self._try_set_nick(interaction.user, target)
        if changed:
            self._repository.delete_original_nickname(guild_id, user_id)
            self._repository.save()
            await interaction.response.send_message("🎄まほうはおしまい🎄", ephemeral=True)
        else:
            await interaction.response.send_message(
                "権限の都合で戻せなかった…！", ephemeral=True
            )

    async def pull(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        if self.is_closed():
            await interaction.response.send_message(
                embed=self.closed_embed(),
                ephemeral=True,
            )
            return
        reward = self.pick_reward(self.read_csv_rewards())
        if reward is None:
            await interaction.response.send_message(
                "ガチャ表が読めない！\n"
                "CSVのヘッダが weight,rarity,icon,title,name,desc "
                "になってるか確認してね。",
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        user_id = interaction.user.id
        self._save_orig_once(guild_id, user_id, interaction.user)
        self._repository.save()
        new_nick = self._make_gacha_nick(interaction.user.display_name, reward.name)
        changed = await self._try_set_nick(interaction.user, new_nick)
        icon = reward.icon if reward.icon else "🎁"
        title = f"{icon} {reward.title} 〔{reward.rarity}〕"
        embed = discord.Embed(
            title=title,
            description=reward.desc,
            color=self._rarity_color(reward.rarity),
        )
        embed.add_field(name="", value=f"`{new_nick}`", inline=False)
        embed.set_author(
            name=f"{interaction.user.display_name} に届いた贈り物",
            icon_url=interaction.user.display_avatar.url,
        )
        note = "世界が少しだけ変わった気がする" if changed else "名前は変えられなかった"
        embed.set_footer(text=note)
        await interaction.response.send_message(
            embed=embed,
            view=self._result_view_factory(),
            ephemeral=True,
        )

    def _restore_target_from_state_or_nick(
        self,
        guild_id: int,
        member: discord.Member,
    ) -> tuple[str | None, bool]:
        original = self._repository.get_original_nickname(guild_id, member.id)
        if original is not None:
            if original == STATE_NONE:
                return (None, True)
            return (original, True)
        current = member.nick or ""
        if "＠" in current or "@" in current:
            base = self._base_name(current)
            if base == "unknown":
                return (None, False)
            return (base, False)
        return (None, False)

    async def ensure_panel(self) -> None:
        if self._channel_id == 0:
            return
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self._channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            return
        message_id = self._repository.get_panel_message_id()
        if message_id:
            try:
                await channel.fetch_message(message_id)
                return
            except discord.NotFound:
                logger.warning("Stored Xmas panel message was not found")
            except discord.Forbidden:
                logger.exception("Missing permission to fetch the Xmas panel")
                return
            except discord.HTTPException:
                logger.exception("Discord API failed while fetching the Xmas panel")
                return
        try:
            message = await channel.send(
                embed=self.panel_embed(),
                view=self._panel_view_factory(),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to create the Xmas panel")
            return
        self._repository.set_panel_message_id(message.id)
        self._repository.save()

    async def send_panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=self.panel_embed(),
            view=self._panel_view_factory(),
            ephemeral=True,
        )

    async def revert_all(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = interaction.guild.id
        targets = set(self._repository.get_original_user_ids(guild_id))
        if interaction.guild.chunked is False:
            try:
                await interaction.guild.chunk()
            except Exception:
                logger.exception("Failed to refresh members for Xmas nickname restore")
        salvage_members: list[discord.Member] = []
        for member in interaction.guild.members:
            if not isinstance(member, discord.Member):
                continue
            if member.nick and ("＠" in member.nick or "@" in member.nick):
                salvage_members.append(member)
        for member in salvage_members:
            targets.add(member.id)
        ok_count = 0
        fail_count = 0
        skip_count = 0
        cleared = 0
        for user_id in list(targets):
            member = interaction.guild.get_member(user_id)
            if member is None:
                skip_count += 1
                continue
            target_nick, should_clear = self._restore_target_from_state_or_nick(
                guild_id, member
            )
            if target_nick is None and member.nick is None:
                if should_clear:
                    self._repository.delete_original_nickname(guild_id, user_id)
                    cleared += 1
                skip_count += 1
                continue
            changed = await self._try_set_nick(member, target_nick)
            if changed:
                ok_count += 1
                if should_clear:
                    self._repository.delete_original_nickname(guild_id, user_id)
                    cleared += 1
            else:
                fail_count += 1
            await asyncio.sleep(0.8)
        self._repository.save()
        message = (
            "🎄 全員戻し：結果\n"
            f"✅ 成功：{ok_count}\n"
            f"❌ 失敗：{fail_count}（だいたい権限/ロール階層）\n"
            f"⏭️ 変更なし/対象外：{skip_count}\n"
            f"🧾 state消去：{cleared}\n\n"
            "失敗が残る場合は、Botロールを対象より上にして、"
            "`Manage Nicknames` を確認してね。"
        )
        await interaction.followup.send(message, ephemeral=True)
