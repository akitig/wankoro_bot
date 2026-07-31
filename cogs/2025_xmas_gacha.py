import asyncio
import csv
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from storage.json_store import load_json_or_default, save_json_atomic

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

STATE_NONE = "__NONE__"


config = get_config()
CSV_PATH = config.xmas_gacha_csv_path
STATE_PATH = config.xmas_gacha_state_path
CHANNEL_ID = config.xmas_gacha_channel_id
CUTOFF_RAW = config.xmas_gacha_cutoff

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


def _parse_cutoff() -> datetime:
    try:
        dt = datetime.fromisoformat(CUTOFF_RAW)
        if dt.tzinfo is not None:
            return dt
    except ValueError:
        pass
    if ZoneInfo is not None:
        return datetime(2025, 12, 26, 7, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    return datetime(2025, 12, 26, 7, 0, 0)


def _now_jst() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Tokyo"))
    return datetime.now()


def _is_closed() -> bool:
    cutoff = _parse_cutoff()
    now = _now_jst()
    if cutoff.tzinfo is None or now.tzinfo is None:
        return now >= cutoff
    return now >= cutoff


def _rarity_color(rarity: str) -> int:
    if rarity == "UR":
        return 0xFFD700
    if rarity == "SR":
        return 0xC77DFF
    if rarity == "R":
        return 0x4D96FF
    return 0x9AA0A6


def _panel_embed() -> discord.Embed:
    cutoff = _parse_cutoff()
    cutoff_str = cutoff.strftime("%m/%d %H:%M")
    e = discord.Embed(
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
    e.set_footer(text="元に戻せるよ")
    return e


def _read_csv_rewards() -> List[t_reward]:
    if not CSV_PATH.exists():
        return []
    rewards: List[t_reward] = []
    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                w = int(str(row.get("weight", "")).strip())
            except ValueError:
                continue
            rarity = str(row.get("rarity", "")).strip()
            icon = str(row.get("icon", "")).strip()
            title = str(row.get("title", "")).strip()
            name = str(row.get("name", "")).strip()
            desc = str(row.get("desc", "")).strip()
            if w <= 0 or not rarity or not title or not name:
                continue
            rewards.append(t_reward(w, rarity, icon, title, name, desc))
    return rewards


def _pick_reward(rewards: List[t_reward]) -> Optional[t_reward]:
    if not rewards:
        return None
    weights = [r.weight for r in rewards]
    return random.choices(rewards, weights=weights, k=1)[0]


def _state_read() -> Dict:
    data = load_json_or_default(
        STATE_PATH,
        {"orig_nick": {}, "panel_message_id": 0},
    )
    if "orig_nick" not in data or not isinstance(data["orig_nick"], dict):
        data["orig_nick"] = {}
    if "panel_message_id" not in data:
        data["panel_message_id"] = 0
    return data


def _state_write(data: Dict) -> None:
    save_json_atomic(STATE_PATH, data)


def _orig_get(data: Dict, gid: int, uid: int) -> Optional[str]:
    g = data.get("orig_nick", {}).get(str(gid), {})
    v = g.get(str(uid))
    if v is None:
        return None
    if v == STATE_NONE:
        return STATE_NONE
    if isinstance(v, str):
        return v
    return None


def _orig_set(data: Dict, gid: int, uid: int, nick: Optional[str]) -> None:
    data.setdefault("orig_nick", {})
    data["orig_nick"].setdefault(str(gid), {})
    if nick is None:
        data["orig_nick"][str(gid)][str(uid)] = STATE_NONE
        return
    data["orig_nick"][str(gid)][str(uid)] = nick


def _orig_clear(data: Dict, gid: int, uid: int) -> None:
    data.setdefault("orig_nick", {})
    data["orig_nick"].setdefault(str(gid), {})
    data["orig_nick"][str(gid)].pop(str(uid), None)


def _base_name(name: str) -> str:
    s = name.strip()
    if "＠" in s:
        s = s.split("＠", 1)[0].strip()
    if "@" in s:
        s = s.split("@", 1)[0].strip()
    if not s:
        return "unknown"
    return s


def _make_gacha_nick(display_name: str, alias: str) -> str:
    base = _base_name(display_name)
    aka = alias.strip() if alias else "無名"
    nick = f"{base}＠{aka}"
    return nick[:32]


def _save_orig_once(state: Dict, gid: int, uid: int, member: discord.Member) -> None:
    if _orig_get(state, gid, uid) is not None:
        return
    if member.nick is None:
        _orig_set(state, gid, uid, None)
        return
    _orig_set(state, gid, uid, _base_name(member.nick))


async def _try_set_nick(member: discord.Member, nick: Optional[str]) -> bool:
    try:
        await member.edit(nick=nick, reason="Xmas gacha nickname")
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Failed to update an Xmas nickname")
        return False


def _closed_embed() -> discord.Embed:
    if random.random() < 0.1:
        msg = random.choice(CLOSED_MESSAGES_NEXT_YEAR)
    else:
        msg = random.choice(CLOSED_MESSAGES_MAIN)
    e = discord.Embed(
        title="🎄 クリスマスは終わった",
        description=msg,
        color=0x2B2B2B,
    )
    e.set_footer(text="また来年")
    return e


class t_xmas_gacha_result_view(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(
        label="↩️ 名前を戻す",
        style=discord.ButtonStyle.secondary,
        custom_id="xmas_gacha:revert",
    )
    async def revert(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return

        data = _state_read()
        gid = interaction.guild.id
        uid = interaction.user.id
        orig = _orig_get(data, gid, uid)

        if orig is None:
            # 救済：今のニックから＠前を取って戻す
            cur = interaction.user.nick or ""
            base = _base_name(cur) if cur else ""
            if "＠" in cur or "@" in cur:
                ok = await _try_set_nick(interaction.user, base or None)
                if ok:
                    await interaction.response.send_message(
                        "🎄まほうはおしまい🎄（復元で戻した）",
                        ephemeral=True,
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

        target = None if orig == STATE_NONE else orig
        ok = await _try_set_nick(interaction.user, target)
        if ok:
            _orig_clear(data, gid, uid)
            _state_write(data)
            await interaction.response.send_message("🎄まほうはおしまい🎄", ephemeral=True)
        else:
            await interaction.response.send_message(
                "権限の都合で戻せなかった…！", ephemeral=True
            )


class t_xmas_gacha_view(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎁 ガチャを引く",
        style=discord.ButtonStyle.success,
        custom_id="xmas_gacha:pull",
    )
    async def pull(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return

        if _is_closed():
            await interaction.response.send_message(
                embed=_closed_embed(),
                ephemeral=True,
            )
            return

        rewards = _read_csv_rewards()
        r = _pick_reward(rewards)
        if r is None:
            await interaction.response.send_message(
                "ガチャ表が読めない！\n"
                "CSVのヘッダが weight,rarity,icon,title,name,desc "
                "になってるか確認してね。",
                ephemeral=True,
            )
            return

        state = _state_read()
        gid = interaction.guild.id
        uid = interaction.user.id
        _save_orig_once(state, gid, uid, interaction.user)
        _state_write(state)

        new_nick = _make_gacha_nick(interaction.user.display_name, r.name)
        changed = await _try_set_nick(interaction.user, new_nick)

        icon = r.icon if r.icon else "🎁"
        title = f"{icon} {r.title} 〔{r.rarity}〕"
        e = discord.Embed(
            title=title,
            description=r.desc,
            color=_rarity_color(r.rarity),
        )
        e.add_field(name="", value=f"`{new_nick}`", inline=False)
        e.set_author(
            name=f"{interaction.user.display_name} に届いた贈り物",
            icon_url=interaction.user.display_avatar.url,
        )
        note = "世界が少しだけ変わった気がする" if changed else "名前は変えられなかった"
        e.set_footer(text=note)

        await interaction.response.send_message(
            embed=e,
            view=t_xmas_gacha_result_view(),
            ephemeral=True,
        )


def _restore_target_from_state_or_nick(
    state: Dict, guild_id: int, member: discord.Member
) -> Tuple[Optional[str], bool]:
    """
    Returns (target_nick, should_clear_state).
    target_nick: None means set nick to None.
    """
    orig = _orig_get(state, guild_id, member.id)
    if orig is not None:
        if orig == STATE_NONE:
            return (None, True)
        return (orig, True)

    # no record -> salvage from current nick (strip alias)
    cur = member.nick or ""
    if "＠" in cur or "@" in cur:
        base = _base_name(cur)
        if base == "unknown":
            return (None, False)
        return (base, False)
    return (None, False)


class t_xmas_gacha(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(t_xmas_gacha_view())

    async def _ensure_panel(self) -> None:
        if CHANNEL_ID == 0:
            return
        await self.bot.wait_until_ready()
        ch = self.bot.get_channel(CHANNEL_ID)
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return
        data = _state_read()
        msg_id = int(data.get("panel_message_id", 0) or 0)
        if msg_id:
            try:
                await ch.fetch_message(msg_id)
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
            msg = await ch.send(embed=_panel_embed(), view=t_xmas_gacha_view())
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to create the Xmas panel")
            return
        data["panel_message_id"] = msg.id
        _state_write(data)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._ensure_panel()

    @app_commands.command(
        name="xmas_gacha_panel",
        description="クリスマスガチャのパネルを送信（手動）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def xmas_gacha_panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=_panel_embed(),
            view=t_xmas_gacha_view(),
            ephemeral=True,
        )

    @app_commands.command(
        name="xmas_gacha_revert_all",
        description="ガチャで変わった名前を、可能な限り全員戻す",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def xmas_gacha_revert_all(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        state = _state_read()
        gid = interaction.guild.id
        gmap = state.get("orig_nick", {}).get(str(gid), {})
        targets = set()

        # stateにいる人
        for uid_str in list(gmap.keys()):
            try:
                targets.add(int(uid_str))
            except ValueError:
                continue

        # stateにいなくても「＠が付いてる」人は救済対象にしたい
        # ただし全メンバーfetchは重いので、キャッシュにいる範囲 + ロール管理で十分
        # (必要なら members intent + chunk)
        if interaction.guild.chunked is False:
            try:
                await interaction.guild.chunk()
            except Exception:
                logger.exception("Failed to refresh members for Xmas nickname restore")

        salvage_members: List[discord.Member] = []
        for m in interaction.guild.members:
            if not isinstance(m, discord.Member):
                continue
            if m.nick and ("＠" in m.nick or "@" in m.nick):
                salvage_members.append(m)

        for m in salvage_members:
            targets.add(m.id)

        ok_count = 0
        fail_count = 0
        skip_count = 0
        cleared = 0

        for uid in list(targets):
            member = interaction.guild.get_member(uid)
            if member is None:
                skip_count += 1
                continue

            target_nick, should_clear = _restore_target_from_state_or_nick(
                state, gid, member
            )

            # target_nick が None で、nick自体も None の場合は何もしない
            if target_nick is None and member.nick is None:
                if should_clear:
                    _orig_clear(state, gid, uid)
                    cleared += 1
                skip_count += 1
                continue

            ok = await _try_set_nick(member, target_nick)
            if ok:
                ok_count += 1
                if should_clear:
                    _orig_clear(state, gid, uid)
                    cleared += 1
            else:
                fail_count += 1

            await asyncio.sleep(0.8)

        _state_write(state)

        msg = (
            "🎄 全員戻し：結果\n"
            f"✅ 成功：{ok_count}\n"
            f"❌ 失敗：{fail_count}（だいたい権限/ロール階層）\n"
            f"⏭️ 変更なし/対象外：{skip_count}\n"
            f"🧾 state消去：{cleared}\n\n"
            "失敗が残る場合は、Botロールを対象より上にして、"
            "`Manage Nicknames` を確認してね。"
        )
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(t_xmas_gacha(bot))
