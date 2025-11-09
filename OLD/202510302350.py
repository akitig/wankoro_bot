import os
import random
import discord
from discord.ext import commands
from discord.ui import View, Button

# ======================================================
# ✅ 環境変数
# ======================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

ROLE_A = int(os.getenv("ROLE_A"))
ROLE_B = int(os.getenv("ROLE_B"))
ROLE_C = int(os.getenv("ROLE_C"))

MANAGER_ROLE_IDS = {
    int(r) for r in os.getenv("MANAGER_ROLE_IDS", "").split(",") if r.strip().isdigit()
}

WELCOME_CATEGORY_NAME = "welcome"
LOG_CATEGORY_NAME = "log"

LEAVE_LOG_CHANNEL_ID = int(os.getenv("LEAVE_LOG_CHANNEL_ID"))

# ✅ 全ユーザー回答&担当記録
user_answers = {}

# ======================================================
# ✅ Intents（退出ログにも必要）
# ======================================================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)


# ======================================================
# ✅ 管理者判定
# ======================================================
def is_manager(ctx):
    if ctx.author.id == ADMIN_ID:
        return True
    return any(role.id in MANAGER_ROLE_IDS for role in ctx.author.roles)


# ======================================================
# ✅ 担当者選出（ロール3つのうちどれかを持っていればOK）
# ======================================================
async def pick_staff(guild: discord.Guild):
    roleA = guild.get_role(ROLE_A)
    roleB = guild.get_role(ROLE_B)
    roleC = guild.get_role(ROLE_C)

    candidates = [
        m for m in guild.members
        if (roleA in m.roles) or (roleB in m.roles) or (roleC in m.roles)
    ]

    if not candidates:
        return None

    # VCを優先
    vc_members = []
    for vc in guild.voice_channels:
        for m in vc.members:
            if m in candidates:
                vc_members.append(m)

    if vc_members:
        return random.choice(vc_members)

    return random.choice(candidates)


# ======================================================
# ✅ UI：質問1
# ======================================================
class Question1(View):
    def __init__(self, member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="はい", style=discord.ButtonStyle.green)
    async def yes(self, interaction, button):
        if interaction.user != self.member:
            return await interaction.response.send_message("あなた専用です！", ephemeral=True)

        user_answers[self.member.id]["age"] = "25歳以上"
        await interaction.response.edit_message(
            content="🧩 **Q2. 性別は？**",
            view=Question2(self.member)
        )

    @discord.ui.button(label="いいえ", style=discord.ButtonStyle.gray)
    async def no(self, interaction, button):
        if interaction.user != self.member:
            return await interaction.response.send_message("あなた専用です！", ephemeral=True)

        user_answers[self.member.id]["age"] = "25歳未満"
        await interaction.response.edit_message(
            content="🧩 **Q2. 性別は？**",
            view=Question2(self.member)
        )


# ======================================================
# ✅ UI：質問2
# ======================================================
class Question2(View):
    def __init__(self, member):
        super().__init__(timeout=None)
        self.member = member

    async def set_gender(self, interaction, gender):
        if interaction.user != self.member:
            return await interaction.response.send_message("あなた専用です！", ephemeral=True)

        user_answers[self.member.id]["gender"] = gender
        await interaction.response.edit_message(
            content="🧩 **Q3. 来れる時間帯は？（複数選択可）**",
            view=Question3(self.member)
        )

    @discord.ui.button(label="男", style=discord.ButtonStyle.blurple)
    async def male(self, interaction, button):
        await self.set_gender(interaction, "男")

    @discord.ui.button(label="女", style=discord.ButtonStyle.blurple)
    async def female(self, interaction, button):
        await self.set_gender(interaction, "女")

    @discord.ui.button(label="その他", style=discord.ButtonStyle.blurple)
    async def other(self, interaction, button):
        await self.set_gender(interaction, "その他")


# ======================================================
# ✅ UI：質問3
# ======================================================
class Question3(View):
    def __init__(self, member):
        super().__init__(timeout=None)
        self.member = member

    async def toggle(self, interaction, label, button):
        if interaction.user != self.member:
            return await interaction.response.send_message("あなた専用です！", ephemeral=True)

        await interaction.response.defer()

        ans = user_answers[self.member.id]
        ans.setdefault("time", [])

        # ✅ ON/OFF トグル
        if label in ans["time"]:
            ans["time"].remove(label)
            button.label = label
            button.style = discord.ButtonStyle.green
        else:
            ans["time"].append(label)
            button.label = f"✅ {label}"
            button.style = discord.ButtonStyle.blurple

        await interaction.message.edit(view=self)

    @discord.ui.button(label="朝", style=discord.ButtonStyle.green)
    async def morning(self, interaction, button):
        await self.toggle(interaction, "朝", button)

    @discord.ui.button(label="昼", style=discord.ButtonStyle.green)
    async def noon(self, interaction, button):
        await self.toggle(interaction, "昼", button)

    @discord.ui.button(label="夜", style=discord.ButtonStyle.green)
    async def night(self, interaction, button):
        await self.toggle(interaction, "夜", button)

    @discord.ui.button(label="深夜", style=discord.ButtonStyle.green)
    async def midnight(self, interaction, button):
        await self.toggle(interaction, "深夜", button)

    @discord.ui.button(label="✅ 完了", style=discord.ButtonStyle.red)
    async def done(self, interaction, button):

        if interaction.user != self.member:
            return await interaction.response.send_message("あなた専用です！", ephemeral=True)

        ans = user_answers[self.member.id]
        times = ", ".join(ans.get("time", [])) or "未回答"

        # ✅ 担当者（staff_id）でメンション
        staff_id = ans.get("staff_id", ADMIN_ID)

        summary = (
            "🎉 **回答ありがとうございます！**\n\n"
            f"📌 年齢 → {ans['age']}\n"
            f"📌 性別 → {ans['gender']}\n"
            f"📌 時間帯 → {times}\n\n"
            f"<@{staff_id}> が確認します！"
        )

        await interaction.response.edit_message(content=summary, view=None)


# ======================================================
# ✅ Welcome Embed
# ======================================================
welcome_embed = discord.Embed(
    title="🌸 はじめまして！",
    description=(
        "灯麗会（とうれいかい）の犬、本部長のわんころです🐶✨\n\n"
        "会長 hanna から、新しくお迎えする方へのお手紙を預かってきました！\n\n"
        "---\n\n"
        "## 🕯 ご参加ありがとうございます！\n"
        "ランクよりも “楽しむ心” を大切にしています🌙\n\n"
        "---\n\n"
        "## 📜 ご協力のお願い\n"
        "加入後 **1週間以内に一度** ご参加をお願いします！\n\n"
        "---\n\n"
        "では、さっそくクイズに答えてください🐶"
    ),
    color=0xFFC0CB
)


# ======================================================
# ✅ welcome部屋作成
# ======================================================
async def create_welcome_room(member):

    guild = bot.get_guild(GUILD_ID)

    # ✅ 担当者決定
    staff = await pick_staff(guild)
    staff_mention = staff.mention if staff else f"<@{ADMIN_ID}>"
    staff_id = staff.id if staff else ADMIN_ID

    # ✅ 個別回答領域生成
    user_answers[member.id] = {"staff_id": staff_id}

    # ✅ カテゴリ
    welcome_cat = discord.utils.get(guild.categories, name=WELCOME_CATEGORY_NAME)
    if welcome_cat is None:
        welcome_cat = await guild.create_category(WELCOME_CATEGORY_NAME)

    # ✅ 名前重複回避
    base = f"welcome-{member.name.lower()}"
    name = base
    i = 2
    while discord.utils.get(guild.channels, name=name):
        name = f"{base}-{i}"
        i += 1

    # ✅ 権限設定
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    # ✅ チャンネル作成
    ch = await guild.create_text_channel(name, category=welcome_cat, overwrites=overwrites)

    # ✅ メッセージ送信
    await ch.send(f"🔥 ようこそ {member.mention} さん！\n案内担当 → {staff_mention}")
    await ch.send(embed=welcome_embed)
    await ch.send("🧩 **Q1. 25歳以上ですか？**", view=Question1(member))

    return ch


# ======================================================
# ✅ on_member_join
# ======================================================
@bot.event
async def on_member_join(member):
    await create_welcome_room(member)


# ======================================================
# ✅ /ok → logカテゴリに移動
# ======================================================
@bot.command()
async def ok(ctx):
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者のみ実行可")

    guild = bot.get_guild(GUILD_ID)

    log_cat = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if log_cat is None:
        log_cat = await guild.create_category(LOG_CATEGORY_NAME)

    await ctx.channel.edit(category=log_cat, sync_permissions=True)
    await ctx.send("✅ log に移動しました。")


# ======================================================
# ✅ /welcome <user_id> 手動作成
# ======================================================
@bot.command()
async def welcome(ctx, user_id: int):
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者専用です")

    guild = bot.get_guild(GUILD_ID)

    # ✅ kick直後などは fetch_member が必要
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except:
            return await ctx.reply("❌ ユーザーが取得できません")

    ch = await create_welcome_room(member)
    await ctx.reply(f"✅ {member.display_name} の部屋を作成 → {ch.mention}")


# ======================================================
# ✅ 退出ログ
# ======================================================
@bot.event
async def on_member_remove(member):

    guild = member.guild
    channel = guild.get_channel(LEAVE_LOG_CHANNEL_ID)
    if channel is None:
        return

    roles = [r.name for r in member.roles if r.name != "@everyone"]
    role_text = "\n".join(f"- {name}" for name in roles) if roles else "なし"

    embed = discord.Embed(
        title="🚪 退出者が出ました",
        description=(
            f"👤 **ユーザー:** {member.mention}\n"
            f"🆔 **ID:** {member.id}\n\n"
            f"🎭 **退出時ロール:**\n{role_text}"
        ),
        color=0xFF5555
    )

    await channel.send(embed=embed)

# ======================================================
# ✅ Reaction Role 設定
# ======================================================
REACTION_ROLE_MESSAGE_ID = int(os.getenv("REACTION_ROLE_MESSAGE_ID", 0))

reaction_role_map = {}

def load_reaction_roles():
    """環境変数 RR_* から emoji_id → role_id を読み取る"""
    global reaction_role_map

    for key, value in os.environ.items():
        if key.startswith("RR_"):
            emoji_id, role_id = value.split(":")
            reaction_role_map[int(emoji_id)] = int(role_id)

load_reaction_roles()


# ======================================================
# ✅ リアクション追加時 → ロール付与
# ======================================================
@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != REACTION_ROLE_MESSAGE_ID:
        return
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(payload.user_id)

    if member is None:
        return

    emoji = payload.emoji

    if not emoji.is_custom_emoji():
        return

    role_id = reaction_role_map.get(emoji.id)
    if not role_id:
        return

    role = guild.get_role(role_id)
    if role:
        await member.add_roles(role, reason="Reaction Role Add")


# ======================================================
# ✅ リアクション削除時 → ロール剥奪
# ======================================================
@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id != REACTION_ROLE_MESSAGE_ID:
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(payload.user_id)

    if member is None:
        return

    emoji = payload.emoji

    if not emoji.is_custom_emoji():
        return

    role_id = reaction_role_map.get(emoji.id)
    if not role_id:
        return

    role = guild.get_role(role_id)
    if role:
        await member.remove_roles(role, reason="Reaction Role Remove")


# ======================================================
# ✅ RUN
# ======================================================
bot.run(DISCORD_TOKEN)
