# bot_dm.py
import os
import random
import logging
import asyncio
from typing import Dict, Tuple, List, Optional

# ========== 依存（dotenv は未導入でもOKにする） ==========
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

import discord
from discord.ext import commands
from discord.ui import View

# ------------------------------------------------------
# ログ設定
# ------------------------------------------------------
logger = logging.getLogger("welcome-bot")
handler = logging.StreamHandler()
fmt = logging.Formatter("[%(asctime)s] [%(levelname)8s] %(name)s:%(message)s")
handler.setFormatter(fmt)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ------------------------------------------------------
# .env 読み込み（あれば）
# ------------------------------------------------------
if load_dotenv is not None:
    load_dotenv()

# ------------------------------------------------------
# 環境変数読み込み（数値は int に）
# ------------------------------------------------------
def _get_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        logger.warning(f"{name} は整数に変換できません: {v}")
        return default

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID = _get_int("GUILD_ID")
ADMIN_ID = _get_int("ADMIN_ID")

# スタッフ抽選用ロール
ROLE_A = _get_int("ROLE_A")
ROLE_B = _get_int("ROLE_B")
ROLE_C = _get_int("ROLE_C")

# 管理者判定ロール（カンマ区切り）
MANAGER_ROLE_IDS = {
    int(x) for x in os.getenv("MANAGER_ROLE_IDS", "").split(",") if x.strip().isdigit()
}

WELCOME_CATEGORY_NAME = os.getenv("WELCOME_CATEGORY_NAME", "welcome")
LOG_CATEGORY_NAME = os.getenv("LOG_CATEGORY_NAME", "log")

LEAVE_LOG_CHANNEL_ID = _get_int("LEAVE_LOG_CHANNEL_ID")

# Reaction Role（ゲームカテゴリー）
REACTION_ROLE_CHANNEL_ID = _get_int("REACTION_ROLE_CHANNEL_ID")
REACTION_ROLE_MESSAGE_ID = _get_int("REACTION_ROLE_MESSAGE_ID")

# Reaction Role（VALORANT ランク）
RR_RANK_CHANNEL_ID = _get_int("RR_RANK_CHANNEL_ID")
RR_RANK_MESSAGE_ID = _get_int("RR_RANK_MESSAGE_ID") or _get_int("RR_RANK_MESSAGE_ID")  # 互換

# ------------------------------------------------------
# Reaction Role: .env から "emoji_id:role_id" を読み込む
#   - ゲーム用 … 変数名が RR_ で始まり、末尾が v_ でないもの（RR_valo など）
#   - ランク用 … 変数名が RR_v_ で始まる（RR_v_Iron など）
# ------------------------------------------------------
def parse_reaction_pairs() -> Tuple[Dict[int, int], Dict[int, int]]:
    game_map: Dict[int, int] = {}
    rank_map: Dict[int, int] = {}

    for key, val in os.environ.items():
        if not key.startswith("RR_"):
            continue
        if key in {
            "REACTION_ROLE_MESSAGE_ID",
            "RR_RANK_MESSAGE_ID",
            "RR_RANK_CHANNEL_ID",
        }:
            continue

        if ":" not in val:
            continue
        parts = val.split(":")
        if len(parts) != 2:
            continue
        try:
            emoji_id = int(parts[0])
            role_id = int(parts[1])
        except ValueError:
            continue

        # ランクは "RR_v_" で始まる
        if key.startswith("RR_v_"):
            rank_map[emoji_id] = role_id
        else:
            game_map[emoji_id] = role_id

    return game_map, rank_map


GAME_REACTIONS, RANK_REACTIONS = parse_reaction_pairs()

# ------------------------------------------------------
# Discord Intents & Bot
# ------------------------------------------------------
intents = discord.Intents.none()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = False
intents.reactions = True
intents.presences = False
bot = commands.Bot(command_prefix="/", intents=intents)

# 起動後にボタンUIを使うので先に定義するためのグローバル
user_answers: Dict[int, Dict] = {}

# ------------------------------------------------------
# 管理者判定
# ------------------------------------------------------
def is_manager(ctx: commands.Context) -> bool:
    if ADMIN_ID and ctx.author.id == ADMIN_ID:
        return True
    return any(role.id in MANAGER_ROLE_IDS for role in getattr(ctx.author, "roles", []))

# ------------------------------------------------------
# 担当者抽選（ROLE_A/B/C のいずれか）
# ------------------------------------------------------
async def pick_staff(guild: discord.Guild) -> Optional[discord.Member]:
    roles = [x for x in [guild.get_role(ROLE_A), guild.get_role(ROLE_B), guild.get_role(ROLE_C)] if x]
    if not roles:
        return None

    candidates: List[discord.Member] = []
    for m in guild.members:
        if any(r in m.roles for r in roles):
            candidates.append(m)

    if not candidates:
        return None

    # VCにいる候補者がいれば優先
    vc_candidates: List[discord.Member] = []
    for vc in guild.voice_channels:
        for m in vc.members:
            if m in candidates:
                vc_candidates.append(m)
    if vc_candidates:
        return random.choice(vc_candidates)

    return random.choice(candidates)

# ------------------------------------------------------
# UI: 質問1〜3
# ------------------------------------------------------
class Question1(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="はい", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.member:
            return await interaction.response.send_message("This is your private flow.", ephemeral=True)
        user_answers[self.member.id] = {"age": "25歳以上"}
        await interaction.response.edit_message(content="🧩 **Q2. 性別は？**", view=Question2(self.member))

    @discord.ui.button(label="いいえ", style=discord.ButtonStyle.gray)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.member:
            return await interaction.response.send_message("This is your private flow.", ephemeral=True)
        user_answers[self.member.id] = {"age": "25歳未満"}
        await interaction.response.edit_message(content="🧩 **Q2. 性別は？**", view=Question2(self.member))


class Question2(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def _set_gender(self, interaction: discord.Interaction, gender: str):
        if interaction.user != self.member:
            return await interaction.response.send_message("This is your private flow.", ephemeral=True)
        user_answers[self.member.id]["gender"] = gender
        await interaction.response.edit_message(content="🧩 **Q3. 来れる時間帯は？**", view=Question3(self.member))

    @discord.ui.button(label="男", style=discord.ButtonStyle.blurple)
    async def male(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_gender(interaction, "男")

    @discord.ui.button(label="女", style=discord.ButtonStyle.blurple)
    async def female(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_gender(interaction, "女")

    @discord.ui.button(label="その他", style=discord.ButtonStyle.blurple)
    async def other(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_gender(interaction, "その他")


class Question3(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    async def _toggle(self, interaction: discord.Interaction, label: str, button: discord.ui.Button):
        if interaction.user != self.member:
            return await interaction.response.send_message("This is your private flow.", ephemeral=True)
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
        await self._toggle(interaction, "朝", button)

    @discord.ui.button(label="昼", style=discord.ButtonStyle.green)
    async def noon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "昼", button)

    @discord.ui.button(label="夜", style=discord.ButtonStyle.green)
    async def night(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "夜", button)

    @discord.ui.button(label="深夜", style=discord.ButtonStyle.green)
    async def midnight(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "深夜", button)

    @discord.ui.button(label="✅ 完了", style=discord.ButtonStyle.red)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.member:
            return await interaction.response.send_message("This is your private flow.", ephemeral=True)
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

# ------------------------------------------------------
# Welcome Embed
# ------------------------------------------------------
welcome_embed = discord.Embed(
    title="🌸 はじめまして！",
    description="灯麗会へようこそ！\nではさっそく質問に答えてください🐶",
    color=0xFFC0CB,
)

# ------------------------------------------------------
# Welcome部屋の作成
# ------------------------------------------------------
async def create_welcome_room(member: discord.Member) -> Optional[discord.TextChannel]:
    guild = member.guild
    staff = await pick_staff(guild)
    staff_mention = staff.mention if staff else (f"<@{ADMIN_ID}>" if ADMIN_ID else "@here")

    # カテゴリ準備
    welcome_cat = discord.utils.get(guild.categories, name=WELCOME_CATEGORY_NAME)
    if welcome_cat is None:
        try:
            welcome_cat = await guild.create_category(WELCOME_CATEGORY_NAME)
        except discord.Forbidden:
            logger.warning("カテゴリ作成権限がありません。")
            return None

    # 重複対策
    base = f"welcome-{member.name.lower()}"
    name = base
    i = 2
    while discord.utils.get(guild.channels, name=name):
        name = f"{base}-{i}"
        i += 1

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    if staff:
        overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    try:
        ch = await guild.create_text_channel(name, category=welcome_cat, overwrites=overwrites)
    except discord.Forbidden:
        logger.warning("チャンネル作成権限がありません。")
        return None

    await ch.send(f"🔥 ようこそ {member.mention} さん！\n案内担当 → {staff_mention}")
    await ch.send(embed=welcome_embed)
    await ch.send("🧩 **Q1. 25歳以上ですか？**", view=Question1(member))
    return ch

# ------------------------------------------------------
# 参加時：必ずWelcome部屋を作る（再参加・過去Kick問わず）
# ------------------------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    await create_welcome_room(member)

# ------------------------------------------------------
# 退出ログ
# ------------------------------------------------------
@bot.event
async def on_member_remove(member: discord.Member):
    if not LEAVE_LOG_CHANNEL_ID:
        return
    guild = member.guild
    channel = guild.get_channel(LEAVE_LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await guild.fetch_channel(LEAVE_LOG_CHANNEL_ID)
        except Exception:
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
        color=0xFF5555,
    )
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        logger.warning("退出ログを送信できません（権限不足）")

# ------------------------------------------------------
# /ok : 現在のチャンネルを log カテゴリへ移動
# ------------------------------------------------------
@bot.command()
async def ok(ctx: commands.Context):
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者のみ実行可")

    guild = ctx.guild
    if guild is None:
        return

    log_cat = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if log_cat is None:
        try:
            log_cat = await guild.create_category(LOG_CATEGORY_NAME)
        except discord.Forbidden:
            return await ctx.reply("⛔ カテゴリ作成権限がありません。")

    try:
        await ctx.channel.edit(category=log_cat, sync_permissions=True)
        await ctx.send("✅ log に移動しました。")
    except discord.Forbidden:
        await ctx.reply("⛔ チャンネル編集権限がありません。")

# ------------------------------------------------------
# /welcome <user_id> : 手動でWelcome部屋を作る
# ------------------------------------------------------
@bot.command()
async def welcome(ctx: commands.Context, user_id: int):
    if not is_manager(ctx):
        return await ctx.reply("⛔ 管理者専用です")

    guild = ctx.guild or bot.get_guild(GUILD_ID) if GUILD_ID else None
    if guild is None:
        return await ctx.reply("❌ ギルド取得に失敗しました。")

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            return await ctx.reply("❌ ユーザーが取得できません。")

    ch = await create_welcome_room(member)
    if ch:
        await ctx.reply(f"✅ {member.display_name} の部屋を作成 → {ch.mention}")
    else:
        await ctx.reply("❌ 部屋の作成に失敗しました。")

# ------------------------------------------------------
# 便利: メッセージを取得（cache→fetch フォールバック）
# ------------------------------------------------------
async def get_message_by_id(channel_id: int, message_id: int) -> Optional[discord.Message]:
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return None
    msg = discord.utils.get(getattr(ch, "messages", []), id=message_id)  # cache ほぼ使わない
    if msg:
        return msg
    try:
        return await ch.fetch_message(message_id)
    except discord.NotFound:
        logger.error("対象メッセージが見つかりません（Unknown Message）")
    except discord.Forbidden:
        logger.error("対象メッセージ取得に権限がありません（Missing Access）")
    except discord.HTTPException as e:
        logger.error(f"対象メッセージ取得に失敗: {e}")
    return None

# ------------------------------------------------------
# Bot が起動時に対象メッセージへ自動でリアクションする
# ------------------------------------------------------
async def ensure_reactions(guild: discord.Guild):
    # ゲーム用
    if REACTION_ROLE_CHANNEL_ID and REACTION_ROLE_MESSAGE_ID and GAME_REACTIONS:
        msg = await get_message_by_id(REACTION_ROLE_CHANNEL_ID, REACTION_ROLE_MESSAGE_ID)
        if msg:
            for emoji_id in GAME_REACTIONS.keys():
                emoji = guild.get_emoji(emoji_id)
                if emoji is None:
                    # ギルド外スタンプ・名前不明でもPartialEmojiで試す
                    emoji = discord.PartialEmoji(name="e", id=emoji_id, animated=False)
                try:
                    await msg.add_reaction(emoji)
                except discord.Forbidden:
                    logger.warning("ゲーム用リアクション追加権限がありません。")
                except discord.HTTPException:
                    # 既についている等は無視
                    pass

    # ランク用
    if RR_RANK_CHANNEL_ID and RR_RANK_MESSAGE_ID and RANK_REACTIONS:
        msg2 = await get_message_by_id(RR_RANK_CHANNEL_ID, RR_RANK_MESSAGE_ID)
        if msg2:
            for emoji_id in RANK_REACTIONS.keys():
                emoji = guild.get_emoji(emoji_id)
                if emoji is None:
                    emoji = discord.PartialEmoji(name="e", id=emoji_id, animated=False)
                try:
                    await msg2.add_reaction(emoji)
                except discord.Forbidden:
                    logger.warning("ランク用リアクション追加権限がありません。")
                except discord.HTTPException:
                    pass

# ------------------------------------------------------
# リアクション → 役職付与/剥奪
# ------------------------------------------------------
async def _apply_reaction_role(payload: discord.RawReactionActionEvent, give: bool):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is None:
        return

    # 対象メッセージ判定 & マップ選択
    mapping: Optional[Dict[int, int]] = None
    if REACTION_ROLE_MESSAGE_ID and payload.message_id == REACTION_ROLE_MESSAGE_ID:
        mapping = GAME_REACTIONS
    elif RR_RANK_MESSAGE_ID and payload.message_id == RR_RANK_MESSAGE_ID:
        mapping = RANK_REACTIONS
    else:
        return

    emoji_id = payload.emoji.id
    if emoji_id is None:
        # カスタム絵文字以外は今回は対象外（必要ならnameでの対応を追加）
        return

    role_id = mapping.get(emoji_id) if mapping else None
    if not role_id:
        return

    role = guild.get_role(role_id)
    if role is None:
        try:
            role = await guild.fetch_role(role_id)
        except Exception:
            return

    # bot 自身のリアクションはスルー
    if payload.user_id == bot.user.id:
        return

    # メンバー取得
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except Exception:
            return

    try:
        if give:
            if role not in member.roles:
                await member.add_roles(role, reason="Reaction Role (add)")
        else:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction Role (remove)")
    except discord.Forbidden:
        logger.warning("ロール変更権限がありません。")
    except discord.HTTPException:
        pass


# -------------------------------
# ✅ VALORANTランクロールは1つだけ
# -------------------------------
VALORANT_RANK_ROLES = {
    int(os.getenv("RR_v_Iron").split(":")[1]),
    int(os.getenv("RR_v_Bronze").split(":")[1]),
    int(os.getenv("RR_v_Silver").split(":")[1]),
    int(os.getenv("RR_v_Gold").split(":")[1]),
    int(os.getenv("RR_v_Platinum").split(":")[1]),
    int(os.getenv("RR_v_Diamond").split(":")[1]),
    int(os.getenv("RR_v_Ascendant").split(":")[1]),
    int(os.getenv("RR_v_Imortal").split(":")[1]),
    int(os.getenv("RR_v_Radiant").split(":")[1]),
}

async def assign_valorant_rank(member, new_role):
    # 既に持っているランクロールを全て外す
    for r in member.roles:
        if r.id in VALORANT_RANK_ROLES and r.id != new_role.id:
            await member.remove_roles(r)

    # 新しいロールを付ける
    await member.add_roles(new_role)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await _apply_reaction_role(payload, give=True)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await _apply_reaction_role(payload, give=False)

# ------------------------------------------------------
# on_ready: 情報表示 & 自動リアクション付与
# ------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

    if not GUILD_ID:
        logger.warning("GUILD_ID が未設定です。")
        return
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        try:
            guild = await bot.fetch_guild(GUILD_ID)
        except Exception:
            logger.error("ギルド取得に失敗しました。")
            return

    # .env の Reaction Role 定義の可視化
    if not GAME_REACTIONS and not RANK_REACTIONS:
        logger.warning("Reaction Role 設定が見つかりません（RR_* 未設定）")

    # Bot 自身が対象メッセージにリアクションを付ける
    await ensure_reactions(guild)

# ------------------------------------------------------
# 実行
# ------------------------------------------------------
if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN が未設定です。")
bot.run(DISCORD_TOKEN)
