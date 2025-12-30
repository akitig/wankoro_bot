import csv
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def _get_env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _get_env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


DATA_DIR = "/home/akitig/Desktop/Bot/Toureikai/Wankorobot/data"
CSV_PATH = _get_env_str(
    "XMAS_GACHA_CSV",
    os.path.join(DATA_DIR, "2025_xmas_gacha.csv"),
)
STATE_PATH = _get_env_str(
    "XMAS_GACHA_STATE",
    os.path.join(DATA_DIR, "xmas_gacha_state.json"),
)
CHANNEL_ID = _get_env_int("XMAS_GACHA_CHANNEL_ID", 0)
CUTOFF_RAW = _get_env_str("XMAS_GACHA_CUTOFF", "2025-12-26T07:00:00+09:00")


@dataclass(frozen=True)
class t_reward:
    weight: int
    rarity: str
    icon: str
    title: str
    name: str
    desc: str


def _ensure_dir() -> None:
    base = os.path.dirname(STATE_PATH) or DATA_DIR
    if not os.path.isdir(base):
        os.makedirs(base, exist_ok=True)


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


def _read_csv_rewards() -> List[t_reward]:
    if not os.path.exists(CSV_PATH):
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
    _ensure_dir()
    if not os.path.exists(STATE_PATH):
        return {"orig_nick": {}, "panel_message_id": 0}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"orig_nick": {}, "panel_message_id": 0}


def _state_write(data: Dict) -> None:
    _ensure_dir()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def _orig_get(data: Dict, gid: int, uid: int) -> Optional[str]:
    g = data.get("orig_nick", {}).get(str(gid), {})
    return g.get(str(uid))


def _orig_set(data: Dict, gid: int, uid: int, nick: Optional[str]) -> None:
    data.setdefault("orig_nick", {})
    data["orig_nick"].setdefault(str(gid), {})
    if nick is None:
        data["orig_nick"][str(gid)].pop(str(uid), None)
        return
    data["orig_nick"][str(gid)][str(uid)] = nick


def _base_name(name: str) -> str:
    s = name.strip()
    if "＠" in s:
        s = s.split("＠", 1)[0].strip()
    if "@" in s:
        s = s.split("@", 1)[0].strip()
    if not s:
        return "unknown"
    return s


async def _try_set_nick(member: discord.Member,
                        nick: Optional[str]) -> bool:
    try:
        await member.edit(nick=nick, reason="Xmas gacha revert")
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


class t_xmas_gacha(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ===============================
    # ★ 追加機能：全員の名前を元に戻す
    # ===============================
    @app_commands.command(
        name="xmas_gacha_revert_all",
        description="クリスマスガチャで変更された全員の名前を元に戻す",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def xmas_gacha_revert_all(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        data = _state_read()
        gid = str(interaction.guild.id)
        users = data.get("orig_nick", {}).get(gid, {})

        success = 0
        failed = 0

        for uid_str, orig in list(users.items()):
            member = interaction.guild.get_member(int(uid_str))
            if member is None:
                failed += 1
                continue
            ok = await _try_set_nick(member, orig if orig else None)
            if ok:
                success += 1
                data["orig_nick"][gid].pop(uid_str, None)
            else:
                failed += 1

        _state_write(data)

        await interaction.response.send_message(
            f"🎄 **クリスマスの魔法を解除しました** 🎄\n\n"
            f"✅ 成功：{success} 人\n"
            f"⚠️ 失敗：{failed} 人",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(t_xmas_gacha(bot))