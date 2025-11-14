import os
import random
import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import app_commands


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_answers = {}
        self.processing_users = set()

        # --- 環境変数設定 ---
        self.GUILD_ID = int(os.getenv("GUILD_ID"))
        self.ADMIN_ID = int(os.getenv("ADMIN_ID"))
        self.ROLE_A = int(os.getenv("ROLE_A"))
        self.ROLE_B = int(os.getenv("ROLE_B"))
        self.ROLE_C = int(os.getenv("ROLE_C"))
        self.LEAVE_LOG_CHANNEL_ID = int(os.getenv("LEAVE_LOG_CHANNEL_ID"))
        self.WELCOME_CATEGORY_NAME = "welcome"
        self.LOG_CATEGORY_NAME = "log"

        self.MANAGER_ROLE_IDS = {
            int(r) for r in os.getenv("MANAGER_ROLE_IDS", "").split(",") if r.strip().isdigit()
        }

    # ------------------------------------------------------
    # ✅ 管理者判定
    # ------------------------------------------------------
    def is_manager(self, member: discord.Member):
        if member.id == self.ADMIN_ID:
            return True
        return any(role.id in self.MANAGER_ROLE_IDS for role in member.roles)

    # ------------------------------------------------------
    # ✅ 担当者ランダム選出
    # ------------------------------------------------------
    async def pick_staff(self, guild: discord.Guild):
        roleA = guild.get_role(self.ROLE_A)
        roleB = guild.get_role(self.ROLE_B)
        roleC = guild.get_role(self.ROLE_C)

        candidates = [
            m for m in guild.members
            if (roleA in m.roles) or (roleB in m.roles) or (roleC in m.roles)
        ]
        if not candidates:
            return None

        vc_members = []
        for vc in guild.voice_channels:
            for m in vc.members:
                if m in candidates:
                    vc_members.append(m)

        return random.choice(vc_members) if vc_members else random.choice(candidates)

    # ------------------------------------------------------
    # ✅ Welcome Embed
    # ------------------------------------------------------
    def welcome_embed(self):
        return discord.Embed(
            title="🌸 はじめまして！",
            description=(
                "灯麗会（とうれいかい）の犬、本部長のわんころです🐶✨\n\n"
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
            self.cog.user_answers[self.member.id]["age"] = "25歳以上"
            await i.response.edit_message(
                content="🧩 **Q2. 性別は？**",
                view=self.cog.Question2(self.cog, self.member)
            )

        @discord.ui.button(label="いいえ", style=discord.ButtonStyle.gray)
        async def no(self, i, b):
            if i.user != self.member:
                return await i.response.send_message("あなた専用です！", ephemeral=True)
            self.cog.user_answers[self.member.id]["age"] = "25歳未満"
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
            self.cog.user_answers[self.member.id]["gender"] = gender
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
            ans = self.cog.user_answers[self.member.id]
            ans.setdefault("time", [])
            if label in ans["time"]:
                ans["time"].remove(label)
                b.label = label
                b.style = discord.ButtonStyle.green
            else:
                ans["time"].append(label)
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
            ans = self.cog.user_answers[self.member.id]
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
    # ✅ チャンネル作成処理
    # ------------------------------------------------------
    async def create_welcome_room(self, member):
        guild = self.bot.get_guild(self.GUILD_ID)

        if member.id in self.processing_users:
            print(f"⚠️ Skipped duplicate welcome for {member}")
            return None
        self.processing_users.add(member.id)

        try:
            staff = await self.pick_staff(guild)
            staff_id = staff.id if staff else self.ADMIN_ID
            staff_mention = staff.mention if staff else f"<@{self.ADMIN_ID}>"
            self.user_answers[member.id] = {"staff_id": staff_id}

            category = discord.utils.get(guild.categories, name=self.WELCOME_CATEGORY_NAME)
            if category is None:
                category = await guild.create_category(self.WELCOME_CATEGORY_NAME)

            base = f"welcome-{member.name.lower()}"
            name = base
            i = 2
            while discord.utils.get(guild.channels, name=name):
                name = f"{base}-{i}"
                i += 1

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    embed_links=True,
                    attach_files=True,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    use_external_stickers=True,
                ),
            }
            if staff:
                overwrites[staff] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

            ch = await guild.create_text_channel(name, category=category, overwrites=overwrites)

            try:
                await ch.send(f"🔥 ようこそ {member.mention} さん！\n案内担当 → {staff_mention}")
                await ch.send(embed=self.welcome_embed())
                await ch.send("🧩 **Q1. 25歳以上ですか？**", view=self.Question1(self, member))
            except discord.Forbidden:
                print(f"❌ Bot cannot send messages to {ch.name}. Check channel permissions!")
                perms = ch.permissions_for(guild.me)
                print("  view_channel:", perms.view_channel)
                print("  send_messages:", perms.send_messages)
                print("  embed_links:", perms.embed_links)
                print("  manage_messages:", perms.manage_messages)
                return None

            return ch

        except discord.Forbidden as e:
            print(f"❌ Missing permission when creating channel for {member}: {e}")
            return None

        finally:
            self.processing_users.discard(member.id)

    # ------------------------------------------------------
    # ✅ on_member_join（競合防止）
    # ------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.id in self.processing_users:
            print(f"⚠️ Skipped auto-create for {member} (manual welcome running)")
            return
        await self.create_welcome_room(member)

    # ------------------------------------------------------
    # ✅ /welcome コマンド
    # ------------------------------------------------------
    @app_commands.command(name="welcome", description="指定したユーザーのwelcome部屋を作成します")
    async def welcome_slash(self, interaction: discord.Interaction, user: discord.Member):
        if not self.is_manager(interaction.user):
            return await interaction.response.send_message("⛔ 管理者のみ実行可", ephemeral=True)

        ch = await self.create_welcome_room(user)
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

    # ------------------------------------------------------
    # ✅ 起動後同期
    # ------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.Object(id=self.GUILD_ID)
        try:
            self.bot.tree.add_command(self.welcome_slash, guild=guild)
            self.bot.tree.add_command(self.ok_slash, guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            print(f"✅ Slash commands synced to guild {self.GUILD_ID}: {[cmd.name for cmd in synced]}")
        except Exception as e:
            print(f"⚠️ Failed to sync slash commands: {e}")


async def setup(bot):
    await bot.add_cog(Welcome(bot))
