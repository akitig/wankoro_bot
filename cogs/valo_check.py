import os
import json
from datetime import datetime, timezone

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


def _get_str_env(key: str, default: str) -> str:
    v = os.getenv(key)
    if not v:
        return default
    return v


def _get_opt_channel_id_env(key: str):
    v = os.getenv(key)
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize_questions(qs):
    if not isinstance(qs, list) or len(qs) == 0:
        return None
    out = []
    for item in qs:
        if not isinstance(item, dict):
            continue
        q = item.get("q")
        ch = item.get("choices")
        if not isinstance(q, str) or not isinstance(ch, list) or len(ch) < 2:
            continue
        choices = []
        for c in ch:
            if (
                isinstance(c, list)
                and len(c) == 2
                and isinstance(c[0], str)
                and isinstance(c[1], int)
            ):
                choices.append((c[0], c[1]))
        if len(choices) < 2:
            continue
        out.append({"q": q, "choices": choices})
    if len(out) == 0:
        return None
    return out


def _calc_max_score(questions):
    total = 0
    for q in questions:
        total += max(score for _, score in q["choices"])
    return total


DEFAULT_INTRO_TITLE = "VALORANT ロール診断（Gachi/Enjoy）"
DEFAULT_INTRO_TEXT = (
    "この診断は、コンペにおけるプレイスタイルのズレを減らすためのものです。\n\n"
    "・Gachi：勝利のためにチームワーク/改善/戦略に寄せる\n"
    "・Enjoy：勝敗よりも雰囲気や気軽さを重視する\n\n"
    "※どちらでもコール/報告は前提です。\n"
    "※マップ名称が分からない等の初心者要素は、改善しつつ大目に見てください。\n\n"
    "準備ができたら「開始」を押してね。"
)

DEFAULT_QUESTIONS = [
    {
        "q": "Q1. 今日のコンペの目的に一番近いのは？",
        "choices": [
            ("ランクを上げたい。勝つために合わせたい", 3),
            ("勝ちたいけど、雰囲気も大事。両立したい", 2),
            ("できれば勝ちたいけど、気楽にやりたい", 1),
            ("勝敗は二の次。みんなで遊べればOK", 0),
        ],
    }
]


class QuizView(discord.ui.View):
    def __init__(self, cog: "ValoCheckCog", user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このクイズはあなた用ではありません。", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.cog.sessions.pop(self.user_id, None)

    def set_buttons(self, choices):
        self.clear_items()
        for idx, (label, score) in enumerate(choices):
            self.add_item(ChoiceButton(label=label, score=score, row=idx // 2))


class ChoiceButton(discord.ui.Button):
    def __init__(self, label: str, score: int, row: int = 0):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.score = score
        self.choice_label = label

    async def callback(self, interaction: discord.Interaction):
        view: QuizView = self.view  # type: ignore
        await view.cog.on_answer(interaction, self.score, self.choice_label)


class StartView(discord.ui.View):
    def __init__(self, cog: "ValoCheckCog", user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この操作はあなた用ではありません。", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.cog.sessions.pop(self.user_id, None)

    @discord.ui.button(label="開始", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.start_questions(interaction.user)


class ValoCheckCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_id = _get_int_env("GUILD_ID")
        self.role_enjoy_id = _get_int_env("ROLE_ENJOY_ID")
        self.role_gachi_id = _get_int_env("ROLE_GACHI_ID")

        self.log_channel_id = _get_opt_channel_id_env("VALO_ROLE_LOG_CHANNEL_ID")
        self.data_path = _get_str_env(
            "VALO_CHECK_DATA_PATH", "data/valo_check_completed.json"
        )

        self.questions_path = _get_str_env(
            "VALO_CHECK_QUESTIONS_PATH", "data/valo_questions.json"
        )
        self.intro_title = _get_str_env("VALO_CHECK_INTRO_TITLE", DEFAULT_INTRO_TITLE)
        self.intro_text = _get_str_env("VALO_CHECK_INTRO_TEXT", DEFAULT_INTRO_TEXT)

        self.thresh_enjoy_only = _get_opt_int_env("VALO_CHECK_THRESH_ENJOY_ONLY", 6)
        self.thresh_gachi_only = _get_opt_int_env("VALO_CHECK_THRESH_GACHI_ONLY", 12)

        self.label_enjoy = _get_str_env("VALO_CHECK_LABEL_ENJOY", "ENJOYのみ")
        self.label_gachi = _get_str_env("VALO_CHECK_LABEL_GACHI", "GACHIのみ")
        self.label_both = _get_str_env("VALO_CHECK_LABEL_BOTH", "GACHI+ENJOY")

        self.questions = []
        self.max_score = 0
        self._reload_questions(use_default=True)

        self.sessions: dict[int, dict] = {}
        self.completed: dict[str, dict] = {}
        self._load_completed()

    def _reload_questions(self, use_default: bool = False) -> bool:
        raw = _load_json_file(self.questions_path)
        norm = _normalize_questions(raw)
        if norm is None and use_default:
            self.questions = DEFAULT_QUESTIONS
            self.max_score = _calc_max_score(self.questions)
            return True
        if norm is None:
            return False
        self.questions = norm
        self.max_score = _calc_max_score(self.questions)
        return True

    def _load_completed(self):
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.completed = json.load(f)
        except FileNotFoundError:
            self.completed = {}
        except Exception:
            self.completed = {}

    def _save_completed(self):
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        tmp = self.data_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.completed, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.data_path)

    def _make_embed(self, idx: int) -> discord.Embed:
        q = self.questions[idx]
        e = discord.Embed(
            title=f"VALORANT ロール診断（{idx + 1}/{len(self.questions)}）",
            description=q["q"],
        )
        e.set_footer(text="回答すると次の問題に進みます。")
        return e

    def _calc_roles(self, score: int) -> tuple[bool, bool, str]:
        if score >= self.thresh_gachi_only:
            return True, False, self.label_gachi
        if score <= self.thresh_enjoy_only:
            return False, True, self.label_enjoy
        return True, True, self.label_both

    async def _get_log_channel(self, guild: discord.Guild):
        if not self.log_channel_id:
            return None
        ch = guild.get_channel(self.log_channel_id)
        if ch is not None:
            return ch
        try:
            return await guild.fetch_channel(self.log_channel_id)
        except Exception:
            return None

    async def _send_intro(self, user: discord.User):
        e = discord.Embed(title=self.intro_title, description=self.intro_text)
        view = StartView(self, user.id)
        msg = await user.send(embed=e, view=view)
        self.sessions[user.id]["dm_message"] = msg

    async def start_questions(self, user: discord.User):
        s = self.sessions.get(user.id)
        if not s:
            return
        s["idx"] = 0
        await self._send_question(user, 0)

    async def _send_question(self, user: discord.User, idx: int):
        view = QuizView(self, user.id)
        view.set_buttons(self.questions[idx]["choices"])
        embed = self._make_embed(idx)
        msg: discord.Message = self.sessions[user.id]["dm_message"]
        await msg.edit(embed=embed, view=view)

    async def _cancel_session(self, uid: int, reason: str,
                              invoker: discord.abc.User):
        s = self.sessions.pop(uid, None)
        if not s:
            return False

        msg = s.get("dm_message")
        if isinstance(msg, discord.Message):
            e = discord.Embed(
                title="VALORANT ロール診断 中断",
                description=(
                    "この診断は管理者によって中断されました。\n"
                    "判定・ロール付与は行われません。\n\n"
                    f"理由: {reason}"
                ),
            )
            try:
                await msg.edit(embed=e, view=None)
            except Exception:
                pass

        try:
            user = self.bot.get_user(uid)
            if user is None:
                user = await self.bot.fetch_user(uid)
            await user.send(
                "VALORANT ロール診断は中断されました（判定なし・ロール付与なし）。"
            )
        except Exception:
            pass

        ch = None
        guild = self.bot.get_guild(self.guild_id)
        if guild is not None:
            ch = await self._get_log_channel(guild)
        if ch is not None:
            e = discord.Embed(
                title="VALO ロール診断 中断ログ",
                description=(
                    f"対象: <@{uid}>\n"
                    f"管理者: **{invoker}**\n"
                    f"理由: **{reason}**"
                ),
            )
            try:
                await ch.send(embed=e)
            except Exception:
                pass
        return True

    async def on_answer(self, interaction: discord.Interaction,
                        add_score: int, choice_label: str):
        uid = interaction.user.id
        s = self.sessions.get(uid)
        if not s:
            await interaction.response.send_message(
                "セッションが見つかりません。管理者に連絡してね。",
                ephemeral=True,
            )
            return
        s["score"] += add_score
        s["answers"].append(choice_label)
        s["idx"] += 1
        await interaction.response.defer()
        if s["idx"] >= len(self.questions):
            await self._finalize(interaction.user, s)
            self.sessions.pop(uid, None)
            return
        await self._send_question(interaction.user, s["idx"])

    async def _finalize(self, user: discord.User, s: dict):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            guild = await self.bot.fetch_guild(self.guild_id)
        member = guild.get_member(user.id)
        if member is None:
            member = await guild.fetch_member(user.id)

        role_enjoy = guild.get_role(self.role_enjoy_id)
        role_gachi = guild.get_role(self.role_gachi_id)
        if role_enjoy is None or role_gachi is None:
            await user.send("ロールID設定が正しくないみたい。運営に連絡してね。")
            return

        score = int(s["score"])
        is_gachi, is_enjoy, label = self._calc_roles(score)

        remove_roles = []
        if role_enjoy in member.roles:
            remove_roles.append(role_enjoy)
        if role_gachi in member.roles:
            remove_roles.append(role_gachi)

        add_roles = []
        if is_enjoy:
            add_roles.append(role_enjoy)
        if is_gachi:
            add_roles.append(role_gachi)

        try:
            if remove_roles:
                await member.remove_roles(*remove_roles, reason="VALO role check reset")
            if add_roles:
                await member.add_roles(*add_roles, reason="VALO role check result")
        except discord.Forbidden:
            await user.send(
                "ロール付与に失敗しました（権限不足）。Botの権限/ロール位置を確認してね。"
            )
            return

        e = discord.Embed(
            title="VALORANT ロール診断 完了",
            description=(
                f"✅ 判定：**{label}**\n"
                f"スコア：**{score}/{self.max_score}**"
            ),
        )
        await user.send(embed=e)

        uid = str(member.id)
        self.completed[uid] = {
            "completed_at": _utc_now(),
            "score": score,
            "max_score": self.max_score,
            "result": label,
            "answers": s["answers"],
            "invoked_by": s.get("invoked_by"),
            "invoked_by_name": s.get("invoked_by_name"),
            "forced": bool(s.get("forced")),
        }
        self._save_completed()
        await self._log_to_channel(guild, member, score, label, s)

    async def _log_to_channel(self, guild: discord.Guild,
                              member: discord.Member, score: int,
                              label: str, s: dict):
        ch = await self._get_log_channel(guild)
        if ch is None:
            return

        invoker = s.get("invoked_by_name", "unknown")
        forced = "YES" if s.get("forced") else "NO"

        e = discord.Embed(
            title="VALO ロール診断ログ",
            description=(
                f"対象: {member.mention}\n"
                f"結果: **{label}**\n"
                f"スコア: **{score}/{self.max_score}**\n"
                f"管理者: **{invoker}**\n"
                f"force: **{forced}**"
            ),
        )
        for i, ans in enumerate(s.get("answers", [])):
            q = self.questions[i]["q"]
            e.add_field(name=q, value=ans, inline=False)
        await ch.send(embed=e)

    @app_commands.command(
        name="check_valo",
        description="管理者が指定したメンバーにDMで診断を送ります",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def check_valo(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        force: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        if member.bot:
            await interaction.followup.send("Botは対象にできません。", ephemeral=True)
            return

        uid = str(member.id)
        if uid in self.completed and not force:
            await interaction.followup.send(
                "このメンバーは既に診断済みです。",
                ephemeral=True,
            )
            return

        if member.id in self.sessions:
            await interaction.followup.send(
                "このメンバーは現在診断中です。", ephemeral=True
            )
            return

        if len(self.questions) == 0:
            await interaction.followup.send(
                "質問が読み込めていません。運営に連絡してね。",
                ephemeral=True,
            )
            return

        self.sessions[member.id] = {
            "idx": -1,
            "score": 0,
            "answers": [],
            "invoked_by": interaction.user.id,
            "invoked_by_name": str(interaction.user),
            "forced": force,
        }

        try:
            await self._send_intro(member)
        except discord.Forbidden:
            self.sessions.pop(member.id, None)
            await interaction.followup.send(
                "DMを送れませんでした。相手がサーバーDMを拒否しています。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{member.mention} にDMで診断を送りました。", ephemeral=True
        )

    @app_commands.command(
        name="reload_valo_questions",
        description="valo_questions.json を再読み込みします（管理者のみ）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_valo_questions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if len(self.sessions) > 0:
            await interaction.followup.send(
                "現在診断中のユーザーがいるため、リロードできません。",
                ephemeral=True,
            )
            return

        ok = self._reload_questions(use_default=False)
        if not ok:
            await interaction.followup.send(
                "質問の再読み込みに失敗しました。JSON形式/パスを確認してね。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"質問を再読み込みしました。質問数={len(self.questions)} "
            f"/ max_score={self.max_score}",
            ephemeral=True,
        )

    @app_commands.command(
        name="cancel_valo",
        description="指定メンバーの診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cancel_valo(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "admin cancel",
    ):
        await interaction.response.defer(ephemeral=True)
        ok = await self._cancel_session(member.id, reason, interaction.user)
        if not ok:
            await interaction.followup.send(
                "このメンバーは現在診断中ではありません。", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{member.mention} の診断を中断しました（判定なし）。", ephemeral=True
        )

    @app_commands.command(
        name="cancel_valo_all",
        description="進行中の全診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cancel_valo_all(
        self,
        interaction: discord.Interaction,
        reason: str = "admin cancel all",
    ):
        await interaction.response.defer(ephemeral=True)

        ids = list(self.sessions.keys())
        if len(ids) == 0:
            await interaction.followup.send("診断中のユーザーはいません。", ephemeral=True)
            return

        cnt = 0
        for uid in ids:
            ok = await self._cancel_session(uid, reason, interaction.user)
            if ok:
                cnt += 1
        await interaction.followup.send(
            f"診断中セッションを {cnt} 件中断しました（判定なし）。",
            ephemeral=True,
        )

    @check_valo.error
    async def check_valo_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        raise error

    @reload_valo_questions.error
    async def reload_valo_questions_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        raise error

    @cancel_valo.error
    async def cancel_valo_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        raise error

    @cancel_valo_all.error
    async def cancel_valo_all_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ValoCheckCog(bot))
