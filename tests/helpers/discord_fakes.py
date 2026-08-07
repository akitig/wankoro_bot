from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass(eq=True, frozen=True)
class FakeRole:
    id: int
    name: str = "test-role"

    @property
    def mention(self) -> str:
        return f"<@&{self.id}>"


class FakeMember:
    def __init__(
        self,
        user_id: int,
        *,
        name: str = "test-member",
        roles: list[FakeRole] | None = None,
        bot: bool = False,
        administrator: bool = True,
        voice: Any | None = None,
    ) -> None:
        self.id = user_id
        self.name = name
        self.display_name = name
        self.mention = f"<@{user_id}>"
        self.roles = list(roles or [])
        self.bot = bot
        self.guild_permissions = SimpleNamespace(administrator=administrator)
        self.voice = voice
        self.guild: FakeGuild | None = None
        self.display_avatar = SimpleNamespace(url="https://invalid/avatar.png")
        self.added_roles: list[tuple[Any, ...]] = []
        self.removed_roles: list[tuple[Any, ...]] = []
        self.sent: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.role_error: Exception | None = None

    async def add_roles(self, *roles: Any, **kwargs: Any) -> None:
        if self.role_error:
            raise self.role_error
        self.added_roles.append(roles)

    async def remove_roles(self, *roles: Any, **kwargs: Any) -> None:
        if self.role_error:
            raise self.role_error
        self.removed_roles.append(roles)

    async def send(self, *args: Any, **kwargs: Any) -> FakeSentMessage:
        self.sent.append((args, kwargs))
        return FakeSentMessage()

    def __str__(self) -> str:
        return self.name


class FakeSentMessage:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)


class FakeChannel:
    def __init__(self, *, name: str = "test-channel", send_error: Exception | None = None):
        self.name = name
        self.mention = "#test-channel"
        self.send_error = send_error
        self.sent: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.edits: list[dict[str, Any]] = []

    async def send(self, *args: Any, **kwargs: Any) -> FakeSentMessage:
        if self.send_error:
            raise self.send_error
        self.sent.append((args, kwargs))
        return FakeSentMessage()

    def permissions_for(self, member: Any) -> SimpleNamespace:
        return SimpleNamespace(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            manage_messages=True,
        )

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)


class FakeGuild:
    def __init__(
        self,
        *,
        guild_id: int = 100,
        roles: list[FakeRole] | None = None,
        members: list[FakeMember] | None = None,
        channels: dict[int, FakeChannel] | None = None,
    ) -> None:
        self.id = guild_id
        self.roles = list(roles or [])
        self.members = list(members or [])
        self._channels = dict(channels or {})
        self.categories: list[Any] = []
        self.channels: list[Any] = []
        self.voice_channels: list[Any] = []
        self.default_role = FakeRole(0, "@everyone")
        self.me = FakeMember(999, name="test-bot", bot=True)
        self.created_categories: list[Any] = []
        self.created_text_channels: list[FakeChannel] = []
        self.create_error: Exception | None = None
        self.channel_send_error: Exception | None = None
        for member in self.members:
            member.guild = self
        for channel in self._channels.values():
            channel.guild = self

    def get_role(self, role_id: int) -> FakeRole | None:
        return next((role for role in self.roles if role.id == role_id), None)

    def get_member(self, user_id: int) -> FakeMember | None:
        return next((member for member in self.members if member.id == user_id), None)

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> FakeChannel:
        channel = self.get_channel(channel_id)
        if channel is None:
            raise LookupError(channel_id)
        return channel

    async def create_category(self, name: str) -> Any:
        if self.create_error:
            raise self.create_error
        category = SimpleNamespace(name=name)
        self.categories.append(category)
        self.created_categories.append(category)
        return category

    async def create_text_channel(self, name: str, **kwargs: Any) -> FakeChannel:
        if self.create_error:
            raise self.create_error
        channel = FakeChannel(name=name, send_error=self.channel_send_error)
        channel.create_kwargs = kwargs
        self.channels.append(channel)
        self.created_text_channels.append(channel)
        return channel


class FakeBot:
    def __init__(self, guild: FakeGuild | None = None) -> None:
        self.guild = guild
        self.user = SimpleNamespace(id=999, avatar=None)
        self.users: dict[int, Any] = {}
        self.fetch_error: Exception | None = None

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        if self.guild and self.guild.id == guild_id:
            return self.guild
        return None

    def get_user(self, user_id: int) -> Any | None:
        return self.users.get(user_id)

    async def fetch_user(self, user_id: int) -> Any:
        if self.fetch_error:
            raise self.fetch_error
        return self.users[user_id]


class FakeEmoji:
    def __init__(self, emoji_id: int | None) -> None:
        self.id = emoji_id

    def is_custom_emoji(self) -> bool:
        return self.id is not None


@dataclass
class FakePayload:
    message_id: int
    user_id: int
    emoji: FakeEmoji


class FakeResponse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def send_message(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("send_message", args, kwargs))

    async def defer(self, **kwargs: Any) -> None:
        self.calls.append(("defer", (), kwargs))

    async def edit_message(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("edit_message", args, kwargs))


class FakeFollowup:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


class FakeInteraction:
    def __init__(
        self,
        user: FakeMember,
        *,
        guild: FakeGuild | None = None,
        channel_id: int | None = None,
    ) -> None:
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild is not None else None
        self.channel_id = channel_id
        self.response = FakeResponse()
        self.followup = FakeFollowup()


@dataclass
class FakeAuthor:
    id: int
    name: str = "private-author"
    bot: bool = False

    def __str__(self) -> str:
        return self.name


@dataclass
class FakeMessage:
    author: FakeAuthor
    channel: Any
    content: str = ""
    attachments: list[Any] = field(default_factory=list)


class FakeDMChannel:
    pass
