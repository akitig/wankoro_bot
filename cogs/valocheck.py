import os
import json
import random
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


def _get_opt_id_env(key: str):
    v = os.getenv(key)
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _get_opt_channel_id_env(key: str):
    return _get_opt_id_env(key)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_intro(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title")
        text = data.get("text")
        if not isinstance(title, str) or not isinstance(text, str):
            return None
        return title, text
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


class ChoiceButton(discord.ui.Button):
    def __init__(self, label: str, score: int, row: int = 0):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.score = int(score)
        self.choice_label = label

    async def callback(self, interaction: discord.Interaction):
        view = self.view  # type: ignore
        if view is None:
            return
        await view.disable_all(interaction)  # 連打対策
        await view.cog.on_answer(interaction, self.score, self.choice_label)


class QuizView(discord.ui.View):
    def __init__(self, cog: "ValoCheckCog", user_id: int, timeout_sec: int):
        super().__init__(timeout=timeout_sec)
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
        await self.cog.expire_session(self.user_id, origin="QuizView.on_timeout")

    def set_buttons(self, choices):
        self.clear_items()
        for idx, (label, score) in enumerate(choices):
            self.add_item(ChoiceButton(label=label, score=score, row=idx // 2))

    async def disable_all(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            try:
                await interaction.edit_original_response(view=self)
            except Exception:
                pass


class StartView(discord.ui.View):
    def __init__(self, cog: "ValoCheckCog", user_id: int, timeout_sec: int):
        super().__init__(timeout=timeout_sec)
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
        await self.cog.expire_session(self.user_id, origin="StartView.on_timeout")

    @discord.ui.button(label="開始", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog.start_questions(interaction.user)


class ValoCheckCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.guild_id = _get_int_env("GUILD_ID")
        self.role_enjoy_id = _get_int_env("ROLE_ENJOY_ID")
        self.role_gachi_id = _get_int_env("ROLE_GACHI_ID")

        self.log_channel_id = _get_opt_channel_id_env("VALO_ROLE_LOG_CHANNEL_ID")
        self.admin_dm_user_id = _get_opt_id_env("DM_FORWARD_USER_ID")
        self.view_timeout_sec = _get_opt_int_env("VALO_CHECK_VIEW_TIMEOUT_SEC", 1800)

        self.data_path = _get_str_env(
            "VALO_CHECK_DATA_PATH", "data/valo_check_completed.json"
        )
        self.questions_path = _get_str_env(
            "VALO_CHECK_QUESTIONS_PATH", "data/valo_questions.json"
        )
        self.intro_path = _get_str_env("VALO_CHECK_INTRO_PATH", "data/valo_intro.json")

        intro = _load_intro(self.intro_path)
        if intro is None:
            self.intro_title = DEFAULT_INTRO_TITLE
            self.intro_text = DEFAULT_INTRO_TEXT
        else:
            self.intro_title, self.intro_text = intro

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
        except Exception:
            self.completed = {}

    def _save_completed(self):
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        tmp = self.data_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.completed, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.data_path)

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

    def _make_embed(self, idx: int) -> discord.Embed:
        q = self.questions[idx]
        e = discord.Embed(
            title=f"VALORANT ロール診断（{idx + 1}/{len(self.questions)}）",
            description=q["q"],
            color=0xF4A261,
        )
        e.set_footer(text="回答すると次の問題に進みます。")
        return e

    def _build_summary_line(self, answers) -> str:
        parts = []
        for i, a in enumerate(answers or []):
            pts = 0
            if isinstance(a, dict):
                pts = int(a.get("score", 0))
            parts.append(f"Q{i + 1}={pts}点")
        return " / ".join(parts) if parts else "(no answers)"

    def _build_recent_answers(self, answers, n: int = 3) -> str:
        if not isinstance(answers, list) or len(answers) == 0:
            return "(no answers)"
        start = max(0, len(answers) - n)
        lines = []
        for i in range(start, len(answers)):
            a = answers[i]
            if not isinstance(a, dict):
                continue
            pts = int(a.get("score", 0))
            choice = str(a.get("choice", ""))
            lines.append(f"Q{i + 1}={pts}点: {choice}")
        return "\n".join(lines) if lines else "(no answers)"

    async def _notify_admin(self, title: str, body: str):
        if not self.admin_dm_user_id:
            return
        admin = self.bot.get_user(self.admin_dm_user_id)
        if admin is None:
            try:
                admin = await self.bot.fetch_user(self.admin_dm_user_id)
            except Exception:
                admin = None
        if admin is None:
            return
        try:
            await admin.send(f"**{title}**\n{body}")
        except Exception:
            pass

    async def _notify_admin_session(self, title: str, user_id: int, s: dict, origin: str):
        idx = int(s.get("idx", -1))
        score = int(s.get("score", 0))
        invoked_by = s.get("invoked_by_name", "unknown")
        invoked_by_id = s.get("invoked_by")
        answers = s.get("answers", [])
        summary = self._build_summary_line(answers)
        recent = self._build_recent_answers(answers, 3)

        body = (
            f"Origin: `{origin}`\n"
            f"Target: <@{user_id}> (`{user_id}`)\n"
            f"InvokedBy: **{invoked_by}**"
        )
        if invoked_by_id is not None:
            body += f" (`{invoked_by_id}`)"
        body += (
            "\n"
            f"Session: idx={idx} score={score}/{self.max_score}\n"
            f"Summary: {summary}\n"
            f"Recent:\n{recent}\n"
        )
        await self._notify_admin(title, body)

    async def expire_session(self, user_id: int, origin: str = "expire_session"):
        s = self.sessions.pop(user_id, None)
        if not isinstance(s, dict):
            return

        expired = discord.Embed(
            title="VALORANT ロール診断",
            description=(
                "⏰ 一定時間操作がなかったため **期限切れ** になりました。\n"
                "もう一度受けたい場合は、管理者に診断を送ってもらってください。"
            ),
            color=0xE76F51,
        )
        msg = s.get("dm_message")
        try:
            if isinstance(msg, discord.Message):
                await msg.edit(embed=expired, view=None)
        except Exception:
            pass

        await self._notify_admin_session(
            "⏰ VALO診断: セッション期限切れ",
            user_id,
            s,
            origin,
        )

    def _shuffle_questions_for_session(self):
        qs = []
        for q in self.questions:
            choices = list(q["choices"])
            random.shuffle(choices)
            qs.append({"q": q["q"], "choices": choices})
        return qs

    async def _send_intro(self, user: discord.User):
        embed = discord.Embed(
            title=self.intro_title,
            description=self.intro_text,
            color=0xF4A261,
        )
        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text="灯麗会 Discord サーバー｜VALORANT ロール診断 🐶")

        view = StartView(self, user.id, self.view_timeout_sec)
        msg = await user.send(embed=embed, view=view)
        self.sessions[user.id]["dm_message"] = msg

    async def start_questions(self, user: discord.User):
        s = self.sessions.get(user.id)
        if not s:
            await self._notify_admin(
                "⚠️ VALO診断: start_questionsでセッション無し",
                f"Target: <@{user.id}> (`{user.id}`)\nOrigin: `start_questions`",
            )
            return
        s["idx"] = 0
        await self._send_question(user, 0)

    async def _send_question(self, user: discord.User, idx: int):
        s = self.sessions.get(user.id)
        if not s:
            await self._notify_admin(
                "⚠️ VALO診断: _send_questionでセッション無し",
                f"Target: <@{user.id}> (`{user.id}`)\nidx={idx}",
            )
            return

        sess_qs = s.get("questions")
        if not isinstance(sess_qs, list) or len(sess_qs) == 0:
            await self._notify_admin_session(
                "⚠️ VALO診断: セッション質問が無い",
                user.id,
                s,
                origin="_send_question",
            )
            return

        if idx < 0 or idx >= len(sess_qs):
            await self._notify_admin_session(
                "⚠️ VALO診断: idx範囲外",
                user.id,
                s,
                origin=f"_send_question idx={idx}",
            )
            return

        view = QuizView(self, user.id, self.view_timeout_sec)
        view.set_buttons(sess_qs[idx]["choices"])
        embed = discord.Embed(
            title=f"VALORANT ロール診断（{idx + 1}/{len(sess_qs)}）",
            description=sess_qs[idx]["q"],
            color=0xF4A261,
        )
        embed.set_footer(text="回答すると次の問題に進みます。")

        msg: discord.Message = s["dm_message"]
        await msg.edit(embed=embed, view=view)

    async def _cancel_session(self, uid: int, reason: str, invoker: discord.abc.User):
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
                color=0xE76F51,
            )
            try:
                await msg.edit(embed=e, view=None)
            except Exception:
                pass

        await self._notify_admin_session(
            "🛑 VALO診断: 管理者中断",
            uid,
            s,
            origin=f"cancel reason={reason}",
        )
        return True

    async def on_answer(
        self, interaction: discord.Interaction, add_score: int, choice_label: str
    ):
        uid = interaction.user.id
        s = self.sessions.get(uid)
        if not s:
            await interaction.followup.send(
                "セッションが見つかりません。管理者に連絡してね。",
                ephemeral=True,
            )
            await self._notify_admin(
                "⚠️ VALO診断: on_answerでセッション無し",
                f"Target: <@{uid}> (`{uid}`)\nChoice: {choice_label} ({add_score}点)",
            )
            return

        sess_qs = s.get("questions", [])
        qlen = len(sess_qs) if isinstance(sess_qs, list) else 0

        current_idx = int(s.get("idx", 0))
        if current_idx < 0:
            current_idx = 0

        last_two = {qlen - 2, qlen - 1} if qlen >= 2 else set()
        if current_idx in last_two and int(add_score) == 0:
            s["force_enjoy"] = True

        s["score"] = int(s.get("score", 0)) + int(add_score)
        s.setdefault("answers", [])
        s["answers"].append({"choice": choice_label, "score": int(add_score)})
        s["idx"] = current_idx + 1

        if s["idx"] >= qlen:
            await self._finalize(interaction.user, s)
            self.sessions.pop(uid, None)
            return

        await self._send_question(interaction.user, s["idx"])

    async def _finalize(self, user: discord.User, s: dict):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(self.guild_id)
            except Exception:
                guild = None
        if guild is None:
            await self._notify_admin_session(
                "❌ VALO診断: guild取得失敗",
                user.id,
                s,
                origin="_finalize",
            )
            return

        try:
            member = guild.get_member(user.id)
            if member is None:
                member = await guild.fetch_member(user.id)
        except Exception:
            await self._notify_admin_session(
                "❌ VALO診断: member取得失敗",
                user.id,
                s,
                origin="_finalize",
            )
            return

        role_enjoy = guild.get_role(self.role_enjoy_id)
        role_gachi = guild.get_role(self.role_gachi_id)
        if role_enjoy is None or role_gachi is None:
            await self._notify_admin_session(
                "❌ VALO診断: ロールID不正",
                user.id,
                s,
                origin="_finalize",
            )
            try:
                await user.send("ロールID設定が正しくないみたい。運営に連絡してね。")
            except Exception:
                pass
            return

        score = int(s.get("score", 0))
        if s.get("force_enjoy"):
            is_gachi, is_enjoy, label = False, True, self.label_enjoy
        else:
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
            await self._notify_admin_session(
                "❌ VALO診断: ロール付与権限不足",
                user.id,
                s,
                origin="_finalize",
            )
            try:
                await user.send(
                    "ロール付与に失敗しました（権限不足）。Botの権限/ロール位置を確認してね。"
                )
            except Exception:
                pass
            return
        except Exception:
            await self._notify_admin_session(
                "❌ VALO診断: ロール付与で例外",
                user.id,
                s,
                origin="_finalize",
            )
            try:
                await user.send("ロール付与に失敗しました。管理者に連絡してね。")
            except Exception:
                pass
            return

        e = discord.Embed(
            title="VALORANT ロール診断 完了 🐶",
            description=(f"✅ 判定：**{label}**\n" f"スコア：**{score}/{self.max_score}**"),
            color=0xF4A261,
        )

        msg = s.get("dm_message")
        if isinstance(msg, discord.Message):
            try:
                await msg.edit(embed=e, view=None)
            except Exception:
                try:
                    await user.send(embed=e)
                except Exception:
                    pass
        else:
            try:
                await user.send(embed=e)
            except Exception:
                pass

        uid = str(member.id)
        self.completed[uid] = {
            "completed_at": _utc_now(),
            "score": score,
            "max_score": self.max_score,
            "result": label,
            "answers": s.get("answers", []),
            "invoked_by": s.get("invoked_by"),
            "invoked_by_name": s.get("invoked_by_name"),
            "forced": bool(s.get("forced")),
            "force_enjoy": bool(s.get("force_enjoy")),
        }
        self._save_completed()
        await self._log_to_channel(guild, member, score, label, s)

    async def _log_to_channel(
        self,
        guild: discord.Guild,
        member: discord.Member,
        score: int,
        label: str,
        s: dict,
    ):
        ch = await self._get_log_channel(guild)
        if ch is None:
            return

        invoker = s.get("invoked_by_name", "unknown")
        forced = "YES" if s.get("forced") else "NO"
        force_enjoy = "YES" if s.get("force_enjoy") else "NO"

        answers = s.get("answers", [])
        summary_line = self._build_summary_line(answers)

        e = discord.Embed(
            title="VALO ロール診断ログ",
            description=(
                f"対象: {member.mention}\n"
                f"🧾 {summary_line}\n"
                f"結果: **{label}**\n"
                f"スコア: **{score}/{self.max_score}**\n"
                f"管理者: **{invoker}**\n"
                f"force: **{forced}**\n"
                f"force_enjoy(last2=0): **{force_enjoy}**"
            ),
            color=0x264653,
        )

        sess_qs = s.get("questions", [])
        for i, a in enumerate(answers):
            qtext = f"Q{i + 1}"
            if isinstance(sess_qs, list) and i < len(sess_qs):
                qtext = sess_qs[i].get("q", qtext)

            if isinstance(a, dict):
                choice = a.get("choice", "")
                pts = int(a.get("score", 0))
                e.add_field(name=qtext, value=f"{choice}\n**{pts}点**", inline=False)
            else:
                e.add_field(name=qtext, value=str(a), inline=False)

        try:
            await ch.send(embed=e)
        except Exception:
            pass

    @app_commands.command(
        name="valo_role",
        description="管理者が指定したメンバーにDMで診断を送ります",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role(
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
            await self._notify_admin(
                "❌ VALO診断: 質問0件",
                f"InvokedBy: {interaction.user} / Target: {member} ({member.id})",
            )
            return

        sess_questions = self._shuffle_questions_for_session()

        self.sessions[member.id] = {
            "idx": -1,
            "score": 0,
            "answers": [],
            "questions": sess_questions,
            "invoked_by": interaction.user.id,
            "invoked_by_name": str(interaction.user),
            "forced": force,
            "force_enjoy": False,
        }

        try:
            await self._send_intro(member)
        except discord.Forbidden:
            self.sessions.pop(member.id, None)
            await interaction.followup.send(
                "DMを送れませんでした。相手がサーバーDMを拒否しています。",
                ephemeral=True,
            )
            await self._notify_admin(
                "❌ VALO診断: DM送信Forbidden",
                f"InvokedBy: {interaction.user}\nTarget: {member} ({member.id})",
            )
            return
        except Exception:
            self.sessions.pop(member.id, None)
            await interaction.followup.send(
                "DM送信に失敗しました。管理者に連絡してね。",
                ephemeral=True,
            )
            await self._notify_admin(
                "❌ VALO診断: DM送信で例外",
                f"InvokedBy: {interaction.user}\nTarget: {member} ({member.id})",
            )
            return

        await interaction.followup.send(
            f"{member.mention} にDMで診断を送りました。", ephemeral=True
        )

    @app_commands.command(
        name="valo_role_reload",
        description="valo_questions.json を再読み込みします（管理者のみ）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_reload(self, interaction: discord.Interaction):
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
            await self._notify_admin(
                "❌ VALO診断: 質問再読み込み失敗",
                f"InvokedBy: {interaction.user}",
            )
            return

        await interaction.followup.send(
            f"質問を再読み込みしました。質問数={len(self.questions)} "
            f"/ max_score={self.max_score}",
            ephemeral=True,
        )

    @app_commands.command(
        name="valo_role_cancel",
        description="指定メンバーの診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_cancel(
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
        name="valo_role_cancel_all",
        description="進行中の全診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_cancel_all(
        self,
        interaction: discord.Interaction,
        reason: str = "admin cancel all",
    ):
        await interaction.response.defer(ephemeral=True)

        ids = list(self.sessions.keys())
        if len(ids) == 0:
            await interaction.followup.send(
                "診断中のユーザーはいません。", ephemeral=True
            )
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

    @valo_role.error
    async def valo_role_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        await self._notify_admin(
            "❌ VALO診断: valo_role コマンドエラー",
            f"InvokedBy: {interaction.user}\nError: {type(error).__name__}: {error}",
        )
        raise error

    @valo_role_reload.error
    async def valo_role_reload_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        await self._notify_admin(
            "❌ VALO診断: valo_role_reload コマンドエラー",
            f"InvokedBy: {interaction.user}\nError: {type(error).__name__}: {error}",
        )
        raise error

    @valo_role_cancel.error
    async def valo_role_cancel_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        await self._notify_admin(
            "❌ VALO診断: valo_role_cancel コマンドエラー",
            f"InvokedBy: {interaction.user}\nError: {type(error).__name__}: {error}",
        )
        raise error

    @valo_role_cancel_all.error
    async def valo_role_cancel_all_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。", ephemeral=True
            )
            return
        await self._notify_admin(
            "❌ VALO診断: valo_role_cancel_all コマンドエラー",
            f"InvokedBy: {interaction.user}\nError: {type(error).__name__}: {error}",
        )
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ValoCheckCog(bot))
