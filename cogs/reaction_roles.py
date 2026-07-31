import re
import discord
from discord.ext import commands
from discord import app_commands

from config import get_config

ENV_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Discord上のロール名とは分離した、systemd EnvironmentFile互換の設定名。
GAME_REACTION_ROLES = {
    "valo": ("VALO民", "RR_GAME_VALO"),
    "tarkov": ("EFT民", "RR_GAME_EFT"),
    "st6": ("SF6民", "RR_GAME_SF6"),
    "mh": ("モンハン民", "RR_GAME_MONSTER_HUNTER"),
    "ow2": ("OW民", "RR_GAME_OW2"),
    "apex": ("APEX民", "RR_GAME_APEX"),
}


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        config = get_config()
        self.GUILD_ID = config.guild_id

        # カンマ区切りで複数のメッセージに対応
        self.REACTION_ROLE_MESSAGE_IDS = set(config.reaction_role_message_ids)
        self._reaction_role_values = config.reaction_role_values

        self.reaction_role_map = {}
        self.load_reaction_roles()

    # ======================================================
    # ✅ .env 読み込み
    # ======================================================
    def load_reaction_roles(self):
        self.reaction_role_map.clear()
        for key, value in self._reaction_role_values.items():
            if key.startswith("RR_"):
                try:
                    emoji_id, role_id = value.split(":")
                    self.reaction_role_map[int(emoji_id)] = int(role_id)
                except ValueError:
                    print(f"⚠️ Invalid RR_ format: {key}")
                if not ENV_KEY_PATTERN.fullmatch(key):
                    print(
                        "⚠️ Non-ASCII Reaction Role environment key detected. "
                        "Migrate it to an RR_GAME_* key for systemd compatibility."
                    )
        print(f"✅ Reaction roles loaded: {len(self.reaction_role_map)} entries")

    # ======================================================
    # ✅ ロール操作共通処理
    # ======================================================
    async def handle_reaction(self, payload, add=True):
        if payload.message_id not in self.REACTION_ROLE_MESSAGE_IDS:
            return
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(self.GUILD_ID)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        emoji_id = payload.emoji.id if payload.emoji.is_custom_emoji() else None
        role_id = self.reaction_role_map.get(emoji_id)
        if not role_id:
            return

        role = guild.get_role(role_id)
        if not role:
            return

        if add:
            await member.add_roles(role)
            print(f"✅ Added {role.name} → {member.display_name}")
        else:
            await member.remove_roles(role)
            print(f"🗑 Removed {role.name} → {member.display_name}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.handle_reaction(payload, add=False)

    # ======================================================
    # ✅ ゲームリアクションの作成
    # ======================================================
    @app_commands.command(name="rrcreate", description="よく遊ぶゲームを選ぶリアクションメッセージを作成します")
    async def rrcreate(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ 管理者のみ実行可", ephemeral=True)

        guild = interaction.guild
        embed = discord.Embed(
            title="🎮 よく遊ぶゲームを選択してね",
            description="リアクションを付けると自動でロールが付きます！",
            color=0xFFB6C1
        )

        msg = await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ ゲーム選択メッセージを作成しました！", ephemeral=True)

        for emoji_name in GAME_REACTION_ROLES:
            emoji = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji:
                await msg.add_reaction(emoji)
                print(f"✅ Added :{emoji_name}:")
            else:
                print(f"⚠️ Emoji :{emoji_name}: not found")

        # ======== .env 出力（改善版） ========
        print("\n📝 以下を .env に必ず追記してください。")
        print("（他の ID がある場合はカンマ区切りで追加）\n")

        all_ids = list(self.REACTION_ROLE_MESSAGE_IDS | {msg.id})
        print("# Reaction Role 対象メッセージID")
        print(f"REACTION_ROLE_MESSAGE_IDS={','.join(str(x) for x in all_ids)}\n")

        print("# Reaction Role 対応表（emoji_id:role_id）")
        for emoji_name, (role_name, env_key) in GAME_REACTION_ROLES.items():
            emoji = discord.utils.get(guild.emojis, name=emoji_name)
            role = discord.utils.get(guild.roles, name=role_name)
            if emoji and role:
                print(f"{env_key}={emoji.id}:{role.id}")
        print()

    # ======================================================
    # ✅ VALORANT ランク版
    # ======================================================
    @app_commands.command(name="rrcreate_valorank", description="VALORANTランク選択用のリアクションメッセージを作成します")
    async def rrcreate_valorank(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ 管理者のみ実行可", ephemeral=True)

        guild = interaction.guild
        embed = discord.Embed(
            title="🎯 Valorantの現在のランクを選択してね",
            description="（ランクが変わった場合、付け直してください）",
            color=0xFF4655
        )

        msg = await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ ランク選択メッセージを作成しました！", ephemeral=True)

        rank_map = {
            "v_iron_1": "v_Iron",
            "v_bronze_1": "v_Bronze",
            "v_silver_1": "v_Silver",
            "v_gold_1": "v_Gold",
            "v_platinum_1": "v_Platinum",
            "v_diamond_1": "v_Diamond",
            "v_ascendant_1": "v_Ascendant",
            "v_immortal_1": "v_Immortal",
            "v_radiant": "v_Radiant",
        }

        for emoji_name in rank_map:
            emoji = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji:
                await msg.add_reaction(emoji)
                print(f"✅ Added :{emoji_name}:")
            else:
                print(f"⚠️ Emoji :{emoji_name}: not found")

        # ======== .env 出力（改善版） ========
        print("\n📝 以下を .env に必ず追記してください。")
        print("（他の ID がある場合はカンマ区切りで追加）\n")

        all_ids = list(self.REACTION_ROLE_MESSAGE_IDS | {msg.id})
        print("# Reaction Role 対象メッセージID")
        print(f"REACTION_ROLE_MESSAGE_IDS={','.join(str(x) for x in all_ids)}\n")

        print("# Reaction Role 対応表（emoji_id:role_id）")
        for emoji_name, role_name in rank_map.items():
            emoji = discord.utils.get(guild.emojis, name=emoji_name)
            role = discord.utils.get(guild.roles, name=role_name)
            if emoji and role:
                print(f"RR_{role_name.upper()}={emoji.id}:{role.id}")
        print()

    # ======================================================
    # ❗ /rrreload 設定再読み込み
    # ======================================================
    @app_commands.command(name="rrreload", description="リアクションロール設定を再読み込みします")
    async def rrreload(self, interaction: discord.Interaction):
        self.load_reaction_roles()
        await interaction.response.send_message("🔄 設定を再読み込みしました！", ephemeral=True)

    # ======================================================
    # ❗ /rrstatus 状態確認
    # ======================================================
    @app_commands.command(name="rrstatus", description="現在のリアクションロール設定を確認します")
    async def rrstatus(self, interaction: discord.Interaction):
        guild = self.bot.get_guild(self.GUILD_ID)

        embed = discord.Embed(
            title="Reaction Role Status",
            description=f"対象メッセージID: `{','.join(str(x) for x in self.REACTION_ROLE_MESSAGE_IDS)}`",
            color=0x00BFFF
        )

        lines = []
        for emoji_id, role_id in self.reaction_role_map.items():
            role = guild.get_role(role_id)
            lines.append(f"<:{emoji_id}> → {role.mention if role else '❌ Not Found'}")

        embed.add_field(name="カスタム絵文字 → ロール", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ======================================================
    # 起動時同期
    # ======================================================
    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.Object(id=self.GUILD_ID)
        try:
            self.bot.tree.add_command(self.rrcreate, guild=guild)
            self.bot.tree.add_command(self.rrcreate_valorank, guild=guild)
            self.bot.tree.add_command(self.rrreload, guild=guild)
            self.bot.tree.add_command(self.rrstatus, guild=guild)
            await self.bot.tree.sync(guild=guild)
            print("✅ ReactionRole commands synced successfully.")
        except Exception as e:
            print(f"⚠️ Failed to sync ReactionRole commands: {e}")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
