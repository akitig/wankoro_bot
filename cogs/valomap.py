import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import random
import os
import json

VALO_API_URL = "https://valorant-api.com/v1/maps"
BAN_FILE = "valomap_bans.json"


class ValorantMap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cached_maps = []
        self.banned_maps = set()
        self.load_bans()

    # -------------------------------
    # 🔹 BANファイルの読み書き
    # -------------------------------
    def load_bans(self):
        if os.path.exists(BAN_FILE):
            try:
                with open(BAN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.banned_maps = set(data.get("bans", []))
                print(f"🚫 Loaded banned maps: {self.banned_maps}")
            except Exception as e:
                print(f"⚠️ Failed to load ban file: {e}")

    def save_bans(self):
        try:
            with open(BAN_FILE, "w", encoding="utf-8") as f:
                json.dump({"bans": list(self.banned_maps)}, f, ensure_ascii=False, indent=2)
            print(f"💾 Saved banned maps: {self.banned_maps}")
        except Exception as e:
            print(f"⚠️ Failed to save ban file: {e}")

    # -------------------------------
    # 🔹 マップデータ取得
    # -------------------------------
    async def fetch_maps(self):
        headers = {
            "User-Agent": "WankoroBot/1.3 (+https://discord.gg/)",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(VALO_API_URL) as resp:
                if resp.status != 200:
                    print(f"⚠️ Failed to fetch maps: {resp.status}")
                    return []
                data = await resp.json()
                return data.get("data", [])

    # -------------------------------
    # 🔹 コンペマップのみ抽出
    # -------------------------------
    async def get_comp_maps(self):
        if not self.cached_maps:
            maps = await self.fetch_maps()
            self.cached_maps = [
                m for m in maps
                if (
                    m.get("isPlayableInCompetitive", False)
                    or (m.get("tacticalDescription") and not m["displayName"].startswith("Range"))
                )
            ]
            print(f"🗺️ Cached {len(self.cached_maps)} maps.")
        return self.cached_maps

    # -------------------------------
    # 🔹 /valomap（全マップ表示）
    # -------------------------------
    @app_commands.command(name="valomap", description="VALORANTの全コンペマップを表示します（BAN済みは❌）")
    async def valomap_all(self, interaction: discord.Interaction):
        maps = await self.get_comp_maps()
        map_names = [m["displayName"] for m in maps]

        desc = "\n".join(
            [f"✅ {m}" if m not in self.banned_maps else f"❌ ~~{m}~~" for m in map_names]
        )

        embed = discord.Embed(
            title="🎯 VALORANT コンペマップ一覧",
            description=desc,
            color=0xFF4655
        )
        await interaction.response.send_message(embed=embed)

    # -------------------------------
    # 🔹 /valomappool（BANされていないマップのみ）
    # -------------------------------
    @app_commands.command(name="valomappool", description="BANされていないVALORANTマップを表示します")
    async def valomap_pool(self, interaction: discord.Interaction):
        maps = await self.get_comp_maps()
        available = [m for m in maps if m["displayName"] not in self.banned_maps]

        if not available:
            await interaction.response.send_message("❌ 現在、利用可能なマップはありません。", ephemeral=True)
            return

        desc = "\n".join(f"✅ {m['displayName']}" for m in available)
        embed = discord.Embed(
            title="🎯 現在のVALORANTコンペマッププール（BAN除外）",
            description=desc,
            color=0x00BFFF
        )
        await interaction.response.send_message(embed=embed)

    # -------------------------------
    # 🔹 /valomapselect
    # -------------------------------
    @app_commands.command(name="valomapselect", description="BANされていないマップからランダムに選びます")
    async def valomap_select(self, interaction: discord.Interaction):
        maps = await self.get_comp_maps()
        available = [m for m in maps if m["displayName"] not in self.banned_maps]

        if not available:
            await interaction.response.send_message("❌ 利用可能なマップがありません。BANを解除してください。")
            return

        selected = random.choice(available)
        name = selected["displayName"]
        image = selected.get("splash")

        embed = discord.Embed(
            title="🎲 ランダム選出マップ",
            description=f"**{name}** が選ばれました！",
            color=0xFF4655
        )
        if image:
            embed.set_image(url=image)
        await interaction.response.send_message(embed=embed)

    # ==================================================
    # 🔹 BANドロップダウンUI
    # ==================================================
    class MapBanDropdown(discord.ui.Select):
        def __init__(self, cog, maps):
            self.cog = cog
            options = [
                discord.SelectOption(label=m["displayName"], description="BANするマップを選択")
                for m in maps
                if m["displayName"] not in cog.banned_maps
            ]
            super().__init__(placeholder="BANするマップを選んでください", options=options, min_values=1, max_values=1)

        async def callback(self, interaction: discord.Interaction):
            selected = self.values[0]
            self.cog.banned_maps.add(selected)
            self.cog.save_bans()
            await interaction.response.edit_message(
                content=f"🚫 `{selected}` をBANしました。",
                view=None
            )

    class MapBanView(discord.ui.View):
        def __init__(self, cog, maps):
            super().__init__(timeout=60)
            self.add_item(ValorantMap.MapBanDropdown(cog, maps))

    # -------------------------------
    # 🔹 /valomapban（UI式BAN）
    # -------------------------------
    @app_commands.command(name="valomapban", description="ドロップダウンでBANするマップを選びます")
    async def valomap_ban_ui(self, interaction: discord.Interaction):
        maps = await self.get_comp_maps()
        available = [m for m in maps if m["displayName"] not in self.banned_maps]

        if not available:
            await interaction.response.send_message("❌ すべてのマップがBAN済みです。", ephemeral=True)
            return

        view = ValorantMap.MapBanView(self, available)
        await interaction.response.send_message("BANするマップを選んでください：", view=view, ephemeral=True)

    # -------------------------------
    # 🔹 /valomapclear
    # -------------------------------
    @app_commands.command(name="valomapclear", description="すべてのBANを解除します")
    async def valomap_clear(self, interaction: discord.Interaction):
        self.banned_maps.clear()
        self.save_bans()
        await interaction.response.send_message("✅ すべてのマップBANを解除しました。")

    # -------------------------------
    # 🔹 /valocustom（コマンド一覧ヘルプ）
    # -------------------------------
    @app_commands.command(name="valocustom", description="VALORANTマップ関連コマンド一覧を表示します")
    async def valomap_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎮 VALORANT マップ管理コマンド一覧",
            description="わんころBot🐶 のVALORANT用マップ管理コマンドです。",
            color=0xFFD700
        )

        commands_info = [
            ("/valomap", "全マップ一覧を表示（BAN済みは❌打消し線付き）"),
            ("/valomappool", "BANされていないマップのみを表示"),
            ("/valomapselect", "BANされていないマップからランダムに選出"),
            ("/valomapban", "ドロップダウンUIでBAN設定"),
            ("/valomapclear", "全てのBANを解除"),
            ("/valocustom", "このコマンド一覧を表示します"),
        ]

        for name, desc in commands_info:
            embed.add_field(name=name, value=desc, inline=False)

        embed.set_footer(text="Powered by わんころBot🐶")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------------
    # 🔹 起動時同期
    # -------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.Object(id=int(os.getenv("GUILD_ID")))
        try:
            self.bot.tree.add_command(self.valomap_all, guild=guild)
            self.bot.tree.add_command(self.valomap_pool, guild=guild)
            self.bot.tree.add_command(self.valomap_select, guild=guild)
            self.bot.tree.add_command(self.valomap_ban_ui, guild=guild)
            self.bot.tree.add_command(self.valomap_clear, guild=guild)
            self.bot.tree.add_command(self.valomap_help, guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            print(f"✅ Slash commands synced (valomap): {[cmd.name for cmd in synced]}")
        except Exception as e:
            print(f"⚠️ Failed to sync valomap commands: {e}")

        if not self.cached_maps:
            await self.get_comp_maps()


# -------------------------------
# 🔹 Cog登録
# -------------------------------
async def setup(bot):
    await bot.add_cog(ValorantMap(bot))
    print("✅ Loaded: cogs.valomap (Full version with /valocustom)")
