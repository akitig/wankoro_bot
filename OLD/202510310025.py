# bot_dm.py
import os
import re
import asyncio
import random
import logging
from typing import Dict, Optional, Tuple, List

import discord
from discord.ext import commands
from discord.ui import View

# ======================================================
# 🔧 ログ設定
# ======================================================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("welcome-bot")

# ======================================================
# 🔐 環境変数
# ======================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))            # 必須
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))            # 代替メンション用

ROLE_A = int(os.getenv("ROLE_A", "0"))                # 担当者候補ロール
ROLE_B = int(os.getenv("ROLE_B", "0"))
ROLE_C = int(os.getenv("ROLE_C", "0"))

MANAGER_ROLE_IDS = {
    int(r) for r in os.getenv("MANAGER_ROLE_IDS", "").split(",") if r.strip().isdigit()
}

WELCOME_CATEGORY_NAME = os.getenv("WELCOME_CATEGORY_NAME", "welcome")
LOG_CATEGORY_NAME = os.getenv("LOG_CATEGORY_NAME", "log")

LEAVE_LOG_CHANNEL_ID = int(os.getenv("LEAVE_LOG_CHANNEL_ID", "0"))

# --- Reaction Role ---
REACTION_ROLE_MESSAGE_ID = int(os.getenv("REACTION_ROLE_MESSAGE_ID", "0"))
REACTION_ROLE_CHANNEL_ID = int(os.getenv("REACTION_ROLE_CHANNEL_ID", "0"))  # 省略可

# 例: RR_valo=1356763218412249089:943473677553516565
#     （左がemoji_id、右がrole_id）
def load_rr_mapping_from_env() -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    for k, v in os.environ.items():
        if not k.startswith("RR_"):
            continue
        if ":" not in v:
            log.warning(f"環境変数 {k} の形式が不正です（emoji_id:role_id）: {v}")
            continue
        left, right = v.split(":", 1)
        if left.isdigit() and right.isdigit():
            mapping[int(left)] = int(right)
        else:
            log.warning(f"環境変数 {k} の数値化に失敗: {v}")
    return mapping

RR_MAP: Dict[int, int] = load_rr_mapping_from_env()  # {emoji_id: role_id}

# 参加者の回答メモリ
user_answers: Dict[int, dict] = {}

# ======================================================
# ✅ Intents（members / message_content / reactions 必須）
# ======================================================
intents = discord.Intents.none()
intents.guilds = True
intents.members = True
intents.emojis_and_stickers = True
intents.message_content = True
intents.reactions = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="/", intents=intents)


# ======================================================
# 🔐 権限ヘルパ
# ======================================================
def is_manager(ctx: commands.Context) -> bool:
    if ctx.author.id == ADMIN_ID:
        return True
    if hasattr(ctx.author, "roles"):
        return any(r.id in MANAGER_ROLE_IDS for r in ctx.author.roles)
    return False


# ======================================================
# 👥 担当者自動選出（3ロールのうちいずれか所持で候補）
# ======================================================
async def pick_staff(guild: discord.Guild) -> Optional[discord.Member]:
    role_ids = [ROLE_A, ROLE_B, ROLE_C]
    roles = [guild.get_role(rid) for rid in role_ids if rid]
    roles = [r for r in roles if r is not None]

    candidates: List[discord.Member] = []
    for m in guild.members:
        if any(r in m.roles for r in roles):
            candidates.append(m)

    if not candidates:
        return None

    # VC参加者を優先
    vc_candidates = []
    for vc in guild.voice_channels:
        for m in vc.members:
            if m in candidates:
                vc_candidates.append(m)
    if vc_candidates:
        return random.choice(vc_candidates)

    return random.choice(candidates)


# ======================================================
# 🧩 UI：質問1〜3
# ======================================================
class Question1(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="はい", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("これはあなた専用です！", ephemeral=True)
        user_answers[self.member.id] = {"age": "25歳以上"}
        await interaction.response.edit_message(content="🧩 **Q2. 性別は？**", view=Question2(self.member))

    @discord.ui.button(label="いいえ", style=discord.ButtonStyle.gray)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("これはあなた専用です！", ephemeral=True)
        user_answers[self.member.id] = {"age": "25歳未満"}
        await interaction.response.edit_message(content="🧩 **Q2. 性別は？**", view=Question2(self.member))


class Question2(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def set_gender(self, interaction: discord.Interaction, gender: str):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("これはあなた専用です！", ephemeral=True)
        user_answers[self.member.id]["gender"] = gender
        await interaction.response.edit_message(content="🧩 **Q3. 来れる時間帯は？（複数可）**", view=Question3(self.member))

    @discord.ui.button(label="男", style=discord.ButtonStyle.blurple)
    async def male(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_gender(interaction, "男")

    @discord.ui.button(label="女", style=discord.ButtonStyle.blurple)
    async def female(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_gender(interaction, "女")

    @discord.ui.button(label="その他", style=discord.ButtonStyle.blurple)
    async def other(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_gender(interaction, "その他")


class Question3(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def toggle(self, interaction: discord.Interaction, label: str, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("これはあなた専用です！", ephemeral=True)

        await interaction.response.defer()
        ans = user_answers[self.member.id]
        ans.setdefault("time", [])

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
    async def morning(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "朝", button)

    @discord.ui.button(label="昼", style=discord.ButtonStyle.green)
    async def noon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "昼", button)

    @discord.ui.button(label="夜", style=discord.ButtonStyle.green)
    async def night(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "夜", button)

    @discord.ui.button(label="深夜", style=discord.ButtonStyle.green)
    async def midnight(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "深夜", button)

    @discord.ui.button(label="✅ 完了", style=discord.ButtonStyle.red)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("これはあなた専用です！", ephemeral=True)

        ans = user_answers[self.member.id]
        times = ", ".join(ans.get("time", [])) or "未回答"

        summary = (
            f"🎉 **回答ありがとうございます！**\n\n"
            f"📌 年齢 → {ans['age']}\n"
            f"📌 性別 → {ans['gender']}\n"
            f"📌 時間帯 → {times}\n\n"
            f"<@{ADMIN_ID}> が確認します！"
        )
        await interaction.response.edit_message(content=summary, view=None)


# ======================================================
# 📨 Welcome Embed
# ======================================================
welcome_embed = discord.Embed(
    title="🌸 はじめまして！",
    description=(
        "灯麗会へようこそ！\n"
        "ではさっそく質問に答えてください🐶"
    ),
    color=0xFFC0CB
)


# ======================================================
# 🏠 welcome部屋作成
# ======================================================
async def create_welcome_room(member: discord.Member) -> discord.TextChannel:
    guild = member.guild
    staff = await pick_staff(guild)
    staff_mention = staff.mention if staff else f"<@{ADMIN_ID}>"

    # カテゴリ確保
    welcome_cat = discord.utils.get(guild.categories, name=WELCOME_CATEGORY_NAME)
    if welcome_cat is None:
        welcome_cat = await guild.create_category(WELCOME_CATEGORY_NAME)
        # Botが発言できるように（カテゴリ既定）
        await welcome_cat.set_permissions(guild.me, view_channel=True, send_messages=True, manage_channels=True)

    # 名前重複回避
    base = f"welcome-{member.name.lower()}"
    name = base
    i = 2
    while discord.utils.get(guild.channels, name=name):
        name = f"{base}-{i}"
        i += 1

    # 権限
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if staff:
        overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    ch = await guild.create_text_channel(name, category=welcome_cat, overwrites=overwrites)

    # 同じ案内担当を全てで統一
    await ch.send(f"🔥 ようこそ {member.mention} さん！\n案内担当 → {staff_mention}")
    await ch.send(embed=welcome_embed)
    await ch.send("🧩 **Q1. 25歳以上ですか？**", view=Question1(member))
    return ch


# ======================================================
# 📒 参加・退出イベント
# ======================================================
@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != GUILD_ID:
        return
    try:
        await create_welcome_room(member)
    except Exception as e:
        log.exception(f"welcome部屋作成に失敗: {e}")

@bot.event
async def on_member_remove(member: discord.Member):
    if member.guild.id != GUILD_ID:
        return
    if not LEAVE_LOG_CHANNEL_ID:
        return
    channel = member.guild.get_channel(LEAVE_LOG_CHANNEL_ID)
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
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        log.warning("退出ログ送信に失敗（権限不足）")
    except Exception:
        log.exception("退出ログ送信に失敗")


# ======================================================
# 🧰 コマンド
# ======================================================
@bot.command()
async def ok(ctx: commands.Context):
    """現在のチャンネルを log カテゴリへ移動"""
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者のみ実行可")

    guild = ctx.guild
    if guild is None:
        return

    log_cat = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if log_cat is None:
        log_cat = await guild.create_category(LOG_CATEGORY_NAME)
        await log_cat.set_permissions(guild.me, view_channel=True, send_messages=True, manage_channels=True)

    # 先にリアクションを返してから移動（移動後に権限を失ってもフィードバックできる）
    try:
        await ctx.message.add_reaction("✅")
    except Exception:
        pass

    try:
        await ctx.channel.edit(category=log_cat, sync_permissions=True)
        # 移動後、送れない可能性があるので try
        try:
            await ctx.send("✅ log に移動しました。")
        except discord.Forbidden:
            pass
    except discord.Forbidden:
        return await ctx.reply("❌ カテゴリ移動の権限がありません（Manage Channels 必要）")
    except Exception:
        log.exception("カテゴリ移動失敗")
        return await ctx.reply("❌ 何かの理由で移動に失敗しました。")


@bot.command()
async def welcome(ctx: commands.Context, user_id: int):
    """手動で指定ユーザーの welcome 部屋を作成"""
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者専用です")

    guild = ctx.guild or bot.get_guild(GUILD_ID)
    if guild is None:
        return await ctx.reply("❌ GUILD が見つかりません")

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except:
            return await ctx.reply("❌ ユーザーが取得できません（kick後の再参加直後など）")

    ch = await create_welcome_room(member)
    await ctx.reply(f"✅ {member.display_name} の部屋を作成 → {ch.mention}")


# ======================================================
# 🎭 リアクションロール（自動リアクション + 付与/剥奪）
# ======================================================
async def ensure_reaction_roles_ready():
    """起動時に対象メッセージへBot自身がリアクションを付与"""
    if not REACTION_ROLE_MESSAGE_ID or not RR_MAP:
        log.info("リアクションロール設定が未完了（REACTION_ROLE_MESSAGE_ID / RR_*）")
        return

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        log.warning("GUILD 未取得")
        return

    msg = None
    # チャンネルIDがあればそれを使う
    if REACTION_ROLE_CHANNEL_ID:
        ch = guild.get_channel(REACTION_ROLE_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(REACTION_ROLE_MESSAGE_ID)
            except Exception as e:
                log.warning(f"指定チャンネルでメッセージ取得失敗: {e}")

    # 無ければ全テキストチャンネルから探索（負荷を抑えて早期終了）
    if msg is None:
        for ch in guild.text_channels:
            try:
                msg = await ch.fetch_message(REACTION_ROLE_MESSAGE_ID)
                if msg:
                    break
            except discord.NotFound:
                continue
            except discord.Forbidden:
                continue
            except Exception:
                continue

    if msg is None:
        log.warning("REACTION_ROLE_MESSAGE_ID のメッセージが見つかりませんでした")
        return

    # 既存リアクションを確認し、足りないものだけ追加
    existing_emoji_ids = set()
    for r in msg.reactions:
        if isinstance(r.emoji, discord.Emoji):
            existing_emoji_ids.add(r.emoji.id)
        elif isinstance(r.emoji, discord.PartialEmoji) and r.emoji.id:
            existing_emoji_ids.add(r.emoji.id)

    for emoji_id in RR_MAP.keys():
        if emoji_id in existing_emoji_ids:
            continue
        emoji_obj = guild.get_emoji(emoji_id)
        if emoji_obj is None:
            # 同一ギルド外のカスタム絵文字は追加できない可能性
            log.warning(f"emoji_id={emoji_id} がギルドで見つかりません")
            continue
        try:
            await msg.add_reaction(emoji_obj)
            await asyncio.sleep(0.3)  # スパム防止
        except discord.Forbidden:
            log.warning("リアクション追加に失敗（権限不足: Add Reactions / Read Message History）")
            break
        except Exception:
            log.exception("リアクション追加に失敗")
            break


def role_for_payload(guild: discord.Guild, payload: discord.RawReactionActionEvent) -> Optional[discord.Role]:
    """payload の emoji から付与すべき Role を取得"""
    emoji = payload.emoji
    emoji_id = getattr(emoji, "id", None)
    if not emoji_id:
        # Unicode絵文字は今回は対象外
        return None
    role_id = RR_MAP.get(emoji_id)
    if not role_id:
        return None
    return guild.get_role(role_id)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    if payload.user_id == bot.user.id:
        return
    if REACTION_ROLE_MESSAGE_ID and payload.message_id != REACTION_ROLE_MESSAGE_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    role = role_for_payload(guild, payload)
    if role is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except:
            return

    if role in member.roles:
        return
    try:
        await member.add_roles(role, reason="Reaction Role: add")
    except discord.Forbidden:
        log.warning("ロール付与に失敗（権限不足: Manage Roles / 役職の序列）")
    except Exception:
        log.exception("ロール付与に失敗")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    if REACTION_ROLE_MESSAGE_ID and payload.message_id != REACTION_ROLE_MESSAGE_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    role = role_for_payload(guild, payload)
    if role is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except:
            return

    if role not in member.roles:
        return
    try:
        await member.remove_roles(role, reason="Reaction Role: remove")
    except discord.Forbidden:
        log.warning("ロール剥奪に失敗（権限不足）")
    except Exception:
        log.exception("ロール剥奪に失敗")


# ======================================================
# 🚀 起動時
# ======================================================
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    # リアクションロールの初期化
    try:
        await ensure_reaction_roles_ready()
    except Exception:
        log.exception("ensure_reaction_roles_ready で例外")


# ======================================================
# ▶ RUN
# ======================================================
if not DISCORD_TOKEN or not GUILD_ID:
    raise RuntimeError("DISCORD_TOKEN / GUILD_ID の環境変数が未設定です。")
bot.run(DISCORD_TOKEN)
