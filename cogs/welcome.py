import logging
import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import app_commands

from config import get_config
from services.welcome_service import WelcomeService

logger = logging.getLogger(__name__)

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # --- 環境変数設定 ---
        config = get_config()
        self.GUILD_ID = config.guild_id
        self.ADMIN_ID = config.require_id(config.admin_id, "ADMIN_ID")
        self.ROLE_A = config.require_id(config.welcome_role_a, "ROLE_A")
        self.ROLE_B = config.require_id(config.welcome_role_b, "ROLE_B")
        self.ROLE_C = config.require_id(config.welcome_role_c, "ROLE_C")
        self.LEAVE_LOG_CHANNEL_ID = config.require_id(
            config.leave_log_channel_id,
            "LEAVE_LOG_CHANNEL_ID",
        )
        self.WELCOME_CATEGORY_NAME = "welcome"
        self.LOG_CATEGORY_NAME = "log"

        self.MANAGER_ROLE_IDS = set(config.manager_role_ids)
        self.service = WelcomeService(
            bot,
            guild_id=self.GUILD_ID,
            admin_id=self.ADMIN_ID,
            staff_role_ids=(self.ROLE_A, self.ROLE_B, self.ROLE_C),
        )

    # ------------------------------------------------------
    # ✅ 管理者判定
    # ------------------------------------------------------
    def is_manager(self, member: discord.Member):
        if member.id == self.ADMIN_ID:
            return True
        return any(role.id in self.MANAGER_ROLE_IDS for role in member.roles)

    # ------------------------------------------------------
    # ✅ Welcome Embed
    # ------------------------------------------------------
    def welcome_embed(self):
        return discord.Embed(
            title="🌸 はじめまして！",
            description=(
                "灯麗会（とうれいかい）の犬、事務局長のわんころです🐶✨\n\n"
                "会長 hanna から、新しくお迎えする方へのお手紙を預かってきました！\n\n"
                "---\n\n"
                "## 🕯 ご参加ありがとうございます！\n"
                "ランクよりも “楽しむ心” を大切にしています🌙\n\n"
                "---\n\n"
                "## 📜 ご協力のお願い\n"
                "加入後 **1週間以内にVCへの** ご参加をお願いします！\n\n"
                "---\n\n"
                "では、さっそくクイズに答えてください🐶"
            ),
            color=0xFFC0CB
        )

    # ------------------------------------------------------
    # ✅ Q1〜Q3 の質問UI
    # ------------------------------------------------------
    class Question1(View):
        def __init__(self, cog, member):
            super().__init__(timeout=None)
            self.cog = cog
            self.member = member

        @discord.ui.button(label="はい", style=discord.ButtonStyle.green)
        async def yes(self, i, b):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            self.cog.service.set_answer(self.member.id, "age", "25歳以上")
            await i.response.edit_message(
                content="🧩 **Q2. 性別は？**",
                view=self.cog.Question2(self.cog, self.member)
            )

        @discord.ui.button(label="いいえ", style=discord.ButtonStyle.gray)
        async def no(self, i, b):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            self.cog.service.set_answer(self.member.id, "age", "25歳未満")
            await i.response.edit_message(
                content="🧩 **Q2. 性別は？**",
                view=self.cog.Question2(self.cog, self.member)
            )

    class Question2(View):
        def __init__(self, cog, member):
            super().__init__(timeout=None)
            self.cog = cog
            self.member = member

        async def set_gender(self, i, gender):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            self.cog.service.set_answer(self.member.id, "gender", gender)
            await i.response.edit_message(
                content="🧩 **Q3. 来れる時間帯は？（複数選択可）**",
                view=self.cog.Question3(self.cog, self.member)
            )

        @discord.ui.button(label="男", style=discord.ButtonStyle.blurple)
        async def male(self, i, b): await self.set_gender(i, "男")

        @discord.ui.button(label="女", style=discord.ButtonStyle.blurple)
        async def female(self, i, b): await self.set_gender(i, "女")

        @discord.ui.button(label="その他", style=discord.ButtonStyle.blurple)
        async def other(self, i, b): await self.set_gender(i, "その他")

    class Question3(View):
        def __init__(self, cog, member):
            super().__init__(timeout=None)
            self.cog = cog
            self.member = member

        async def toggle(self, i, label, b):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            await i.response.defer()
            times = self.cog.service.toggle_time(self.member.id, label)
            if label not in times:
                b.label = label
                b.style = discord.ButtonStyle.green
            else:
                b.label = f"✅ {label}"
                b.style = discord.ButtonStyle.blurple
            await i.message.edit(view=self)

        @discord.ui.button(label="朝", style=discord.ButtonStyle.green)
        async def morning(self, i, b): await self.toggle(i, "朝", b)
        @discord.ui.button(label="昼", style=discord.ButtonStyle.green)
        async def noon(self, i, b): await self.toggle(i, "昼", b)
        @discord.ui.button(label="夜", style=discord.ButtonStyle.green)
        async def night(self, i, b): await self.toggle(i, "夜", b)
        @discord.ui.button(label="深夜", style=discord.ButtonStyle.green)
        async def midnight(self, i, b): await self.toggle(i, "深夜", b)

        @discord.ui.button(label="✅ 完了", style=discord.ButtonStyle.red)
        async def done(self, i, b):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            ans = self.cog.service.get_answers(self.member.id)
            times = ", ".join(ans.get("time", [])) or "未回答"
            staff_id = ans.get("staff_id", self.cog.ADMIN_ID)
            summary = (
                "🎉 **回答ありがとうございます！**\n\n"
                f"📌 年齢 → {ans['age']}\n"
                f"📌 性別 → {ans['gender']}\n"
                f"📌 時間帯 → {times}\n\n"
                f"<@{staff_id}> が確認します！"
            )
            await i.response.edit_message(content=summary, view=None)

    # ------------------------------------------------------
    # ✅ on_member_join（競合防止）
    # ------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if self.service.is_processing(member.id):
            logger.warning("Skipped automatic welcome while manual workflow is active")
            return
        await self.service.create_welcome_room(
            member,
            welcome_embed=self.welcome_embed,
            question_view=lambda: self.Question1(self, member),
        )

    # ------------------------------------------------------
    # ✅ /welcome コマンド
    # ------------------------------------------------------
    @app_commands.command(name="welcome", description="指定したユーザーのwelcome部屋を作成します")
    async def welcome_slash(self, interaction: discord.Interaction, user: discord.Member):
        if not self.is_manager(interaction.user):
            return await interaction.response.send_message("⛔ 管理者のみ実行可", ephemeral=True)

        ch = await self.service.create_welcome_room(
            user,
            welcome_embed=self.welcome_embed,
            question_view=lambda: self.Question1(self, user),
        )
        if ch is None:
            return await interaction.response.send_message(
                "❌ チャンネル作成に失敗しました。Botの権限を確認してください。",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ {user.display_name} の部屋を作成しました → {ch.mention}",
            ephemeral=False
        )

    # ------------------------------------------------------
    # ✅ /ok コマンド
    # ------------------------------------------------------
    @app_commands.command(name="ok", description="現在のチャンネルをlogカテゴリへ移動します")
    async def ok_slash(self, interaction: discord.Interaction):
        if not self.is_manager(interaction.user):
            return await interaction.response.send_message("⛔ 管理者のみ実行可", ephemeral=True)

        guild = self.bot.get_guild(self.GUILD_ID)
        log_cat = discord.utils.get(guild.categories, name=self.LOG_CATEGORY_NAME)
        if log_cat is None:
            log_cat = await guild.create_category(self.LOG_CATEGORY_NAME)

        await interaction.channel.edit(category=log_cat, sync_permissions=True)
        await interaction.response.send_message(
            f"✅ {interaction.channel.mention} を {self.LOG_CATEGORY_NAME} に移動しました。",
            ephemeral=False
        )

async def setup(bot):
    await bot.add_cog(Welcome(bot))
