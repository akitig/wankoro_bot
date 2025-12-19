import os
import time
import discord
from discord import app_commands
from discord.ext import commands


def _get_int_env(key: str) -> int:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Missing env: {key}")
    return int(v)


def _get_opt_int_env(key: str, default: int) -> int:
    v = os.getenv(key)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _has_forbidden_mentions(text: str) -> bool:
    t = (text or "").lower()
    if "@here" in t or "@everyone" in t:
        return True
    if "<@&" in t or "<@" in t:
        return True
    return False


def _cooldown_left(now: float, last: float, cd: int) -> int:
    left = int(cd - (now - last))
    if left < 0:
        return 0
    return left


class UnratedRecruitModal(discord.ui.Modal, title="VALO募集（アンレ）"):
    need = discord.ui.TextInput(
        label="何人募集？",
        placeholder="例: 3",
        required=True,
        max_length=2,
    )
    note = discord.ui.TextInput(
        label="一言（任意）",
        placeholder="例: VCあり / 初心者OK / ゆるく など",
        required=False,
        max_length=80,
    )

    def __init__(self, view: "ValoRecruitView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if _has_forbidden_mentions(self.note.value):
            await interaction.response.send_message(
                "@here/@everyone/メンションは禁止だよ。",
                ephemeral=True,
            )
            return
        ok, msg = self.view.check_and_touch_cooldown(interaction.user.id)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await self.view.send_unrated(interaction, self.need.value, self.note.value)


class CompRecruitModal(discord.ui.Modal, title="VALO募集（コンペ）"):
    need = discord.ui.TextInput(
        label="何人募集？",
        placeholder="例: 2",
        required=True,
        max_length=2,
    )
    note = discord.ui.TextInput(
        label="一言（任意）",
        placeholder="例: VCあり / 報告多め / 雰囲気よく など",
        required=False,
        max_length=80,
    )

    def __init__(self, view: "ValoRecruitView", mention_role_id: int,
                 role_label: str):
        super().__init__()
        self.view = view
        self.mention_role_id = mention_role_id
        self.role_label = role_label

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if _has_forbidden_mentions(self.note.value):
            await interaction.response.send_message(
                "@here/@everyone/メンションは禁止だよ。",
                ephemeral=True,
            )
            return
        ok, msg = self.view.check_and_touch_cooldown(interaction.user.id)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await self.view.send_comp(
            interaction,
            self.need.value,
            self.note.value,
            self.mention_role_id,
            self.role_label,
        )


class CompTypeSelect(discord.ui.Select):
    def __init__(self, view: "CompTypeSelectView"):
        options = [
            discord.SelectOption(label="ガチ勢", value=str(view.gachi_role_id)),
            discord.SelectOption(label="エンジョイ勢", value=str(view.enjoy_role_id)),
        ]
        super().__init__(
            placeholder="自分の所属（ガチ/エンジョイ）を選んでね",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._v = view

    async def callback(self, interaction: discord.Interaction) -> None:
        picked_role_id = int(self.values[0])
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "メンバー情報が取れなかったよ。",
                ephemeral=True,
            )
            return
        if not any(r.id == picked_role_id for r in member.roles):
            await interaction.response.send_message(
                "そのロールに所属してないから選べないよ。",
                ephemeral=True,
            )
            return
        label = "ガチ勢" if picked_role_id == self._v.gachi_role_id else "エンジョイ勢"
        modal = CompRecruitModal(self._v.main_view, picked_role_id, label)
        await interaction.response.send_modal(modal)


class CompTypeSelectView(discord.ui.View):
    def __init__(self, main_view: "ValoRecruitView"):
        super().__init__(timeout=120)
        self.main_view = main_view
        self.gachi_role_id = main_view.gachi_role_id
        self.enjoy_role_id = main_view.enjoy_role_id
        self.add_item(CompTypeSelect(self))


class ValoRecruitView(discord.ui.View):
    def __init__(self, channel_id: int, gachi_role_id: int, enjoy_role_id: int,
                 cooldown_seconds: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.gachi_role_id = gachi_role_id
        self.enjoy_role_id = enjoy_role_id
        self.cooldown_seconds = cooldown_seconds
        self._last_post_at: dict[int, float] = {}

    def check_and_touch_cooldown(self, user_id: int) -> tuple[bool, str]:
        now = time.time()
        last = self._last_post_at.get(user_id, 0.0)
        left = _cooldown_left(now, last, self.cooldown_seconds)
        if left > 0:
            return False, f"連投防止：あと **{left}秒** 待ってね。"
        self._last_post_at[user_id] = now
        return True, ""

    async def _get_channel(self, client: discord.Client):
        ch = client.get_channel(self.channel_id)
        if isinstance(ch, discord.TextChannel):
            return ch
        return None

    async def send_unrated(self, interaction: discord.Interaction, need: str,
                           note: str) -> None:
        channel = await self._get_channel(interaction.client)
        if not channel:
            await interaction.response.send_message(
                "募集チャンネルが見つからないよ。",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="VALORANT 募集（アンレ）",
            description=f"募集: **{need}人**",
            color=discord.Color.blurple(),
        )
        if note:
            embed.add_field(name="一言", value=note, inline=False)
        embed.set_footer(text=f"募集主: {interaction.user.display_name}")

        am = discord.AllowedMentions(everyone=False, roles=False, users=False)
        await channel.send(embed=embed, allowed_mentions=am)
        await interaction.response.send_message("アンレ募集を投下したよ。", ephemeral=True)

    async def send_comp(self, interaction: discord.Interaction, need: str,
                        note: str, mention_role_id: int, role_label: str) -> None:
        channel = await self._get_channel(interaction.client)
        if not channel:
            await interaction.response.send_message(
                "募集チャンネルが見つからないよ。",
                ephemeral=True,
            )
            return
        mention = f"<@&{mention_role_id}>"
        embed = discord.Embed(
            title="VALORANT 募集（コンペ）",
            description=f"タイプ: **{role_label}**\n募集: **{need}人**",
            color=discord.Color.gold(),
        )
        if note:
            embed.add_field(name="一言", value=note, inline=False)
        embed.set_footer(text=f"募集主: {interaction.user.display_name}")

        am = discord.AllowedMentions(everyone=False, roles=True, users=False)
        await channel.send(content=mention, embed=embed, allowed_mentions=am)
        await interaction.response.send_message("コンペ募集を投下したよ。", ephemeral=True)

    @discord.ui.button(
        label="アンレ募集",
        style=discord.ButtonStyle.primary,
        custom_id="valo_recruit:unrated",
    )
    async def unrated(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(UnratedRecruitModal(self))

    @discord.ui.button(
        label="コンペ募集",
        style=discord.ButtonStyle.success,
        custom_id="valo_recruit:comp",
    )
    async def competitive(self, interaction: discord.Interaction,
                          _: discord.ui.Button):
        view = CompTypeSelectView(self)
        await interaction.response.send_message(
            "コンペの募集タイプを選んでね（ガチ/エンジョイ）",
            view=view,
            ephemeral=True,
        )


class ValoRecruitCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        channel_id = _get_int_env("VALO_RECRUIT_CHANNEL_ID")
        gachi_id = _get_int_env("VALO_ROLE_GACHI_ID")
        enjoy_id = _get_int_env("VALO_ROLE_ENJOY_ID")
        cooldown = _get_opt_int_env("VALO_RECRUIT_COOLDOWN_SECONDS", 300)
        self.view = ValoRecruitView(channel_id, gachi_id, enjoy_id, cooldown)
        bot.add_view(self.view)

    @app_commands.command(name="valo_panel", description="VALO募集パネルを設置します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def valo_panel(self, interaction: discord.Interaction) -> None:
        channel_id = _get_int_env("VALO_RECRUIT_CHANNEL_ID")
        channel = interaction.client.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "募集チャンネルが見つからないよ。",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="VALORANT 募集",
            description=(
                "ボタンを押して募集を投下してね。\n"
                "・アンレ：人数だけでOK\n"
                "・コンペ：所属のみ選択可→該当ロールへメンション\n"
                "・here/everyone/本文メンションは禁止\n"
                "・連投制限あり"
            ),
            color=discord.Color.green(),
        )
        await channel.send(embed=embed, view=self.view)
        await interaction.response.send_message("募集パネルを設置したよ。", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ValoRecruitCog(bot))
