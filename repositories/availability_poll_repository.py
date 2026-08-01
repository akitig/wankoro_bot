"""JSON persistence for anonymous availability polls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from storage.json_store import load_json_or_default, save_json_atomic

ANSWERS = ("valorant", "other_game", "work_vc")
INITIAL_STATE: dict[str, Any] = {
    "active_poll": None,
    "next_run_at": None,
    "is_paused": False,
    "skip_next_run": False,
}


def _aware_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 string or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} contains an invalid datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True)
class ActivePoll:
    poll_id: str
    message_id: int
    channel_id: int
    opened_at: datetime
    closed_at: datetime | None
    answers: Mapping[str, str]


class AvailabilityPollRepository:
    """Own poll generations, anonymous answer state, and scheduler controls."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._state: dict[str, Any] = dict(INITIAL_STATE)

    def load(self) -> None:
        state = load_json_or_default(self._path, INITIAL_STATE)
        if not isinstance(state, dict):
            raise ValueError("availability poll state must be an object")
        paused = state.get("is_paused", False)
        skip = state.get("skip_next_run", False)
        if not isinstance(paused, bool) or not isinstance(skip, bool):
            raise ValueError("scheduler control fields must be booleans")
        next_run = _aware_datetime(state.get("next_run_at"), "next_run_at")
        active = self._validate_active_poll(state.get("active_poll"))
        self._state = {
            "active_poll": active,
            "next_run_at": next_run.isoformat() if next_run else None,
            "is_paused": paused,
            "skip_next_run": skip,
        }

    @staticmethod
    def _validate_active_poll(value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("active_poll must be an object or null")
        poll_id = value.get("poll_id")
        message_id = value.get("message_id")
        channel_id = value.get("channel_id")
        answers = value.get("answers")
        if not isinstance(poll_id, str) or not poll_id:
            raise ValueError("active_poll.poll_id must be a non-empty string")
        for field, item in (("message_id", message_id), ("channel_id", channel_id)):
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError(f"active_poll.{field} must be a positive integer")
        opened = _aware_datetime(value.get("opened_at"), "active_poll.opened_at")
        closed = _aware_datetime(value.get("closed_at"), "active_poll.closed_at")
        if opened is None:
            raise ValueError("active_poll.opened_at is required")
        if not isinstance(answers, dict):
            raise ValueError("active_poll.answers must be an object")
        clean_answers: dict[str, str] = {}
        for user_id, answer in answers.items():
            if not isinstance(user_id, str) or not user_id.isdigit():
                raise ValueError("active_poll answer keys must be Discord ID strings")
            if answer not in ANSWERS:
                raise ValueError("active_poll contains an unsupported answer")
            clean_answers[user_id] = answer
        return {
            "poll_id": poll_id,
            "message_id": message_id,
            "channel_id": channel_id,
            "opened_at": opened.isoformat(),
            "closed_at": closed.isoformat() if closed else None,
            "answers": clean_answers,
        }

    def save(self) -> None:
        save_json_atomic(self._path, self._state)

    def get_active_poll(self) -> ActivePoll | None:
        active = self._state["active_poll"]
        if active is None:
            return None
        opened = _aware_datetime(active["opened_at"], "active_poll.opened_at")
        if opened is None:
            raise ValueError("active_poll.opened_at is required")
        return ActivePoll(
            poll_id=active["poll_id"],
            message_id=active["message_id"],
            channel_id=active["channel_id"],
            opened_at=opened,
            closed_at=_aware_datetime(active["closed_at"], "active_poll.closed_at"),
            answers=MappingProxyType(dict(active["answers"])),
        )

    def create_poll(
        self,
        *,
        poll_id: str,
        message_id: int,
        channel_id: int,
        opened_at: datetime,
    ) -> None:
        _require_aware(opened_at, "opened_at")
        self._state["active_poll"] = self._validate_active_poll(
            {
                "poll_id": poll_id,
                "message_id": message_id,
                "channel_id": channel_id,
                "opened_at": opened_at.isoformat(),
                "closed_at": None,
                "answers": {},
            }
        )

    def restore_active_poll(self, active: ActivePoll | None) -> None:
        """Restore an immutable snapshot after a failed persistence attempt."""

        if active is None:
            self._state["active_poll"] = None
            return
        self._state["active_poll"] = self._validate_active_poll(
            {
                "poll_id": active.poll_id,
                "message_id": active.message_id,
                "channel_id": active.channel_id,
                "opened_at": active.opened_at.isoformat(),
                "closed_at": (
                    active.closed_at.isoformat() if active.closed_at is not None else None
                ),
                "answers": dict(active.answers),
            }
        )

    def close_active_poll(self, closed_at: datetime) -> None:
        _require_aware(closed_at, "closed_at")
        active = self._state["active_poll"]
        if active is not None:
            active["closed_at"] = closed_at.isoformat()

    def get_answer(self, user_id: int) -> str | None:
        active = self._state["active_poll"]
        return None if active is None else active["answers"].get(str(user_id))

    def set_answer(self, user_id: int, answer: str) -> str | None:
        if answer not in ANSWERS:
            raise ValueError("unsupported availability answer")
        active = self._state["active_poll"]
        if active is None:
            raise RuntimeError("there is no active poll")
        previous = active["answers"].get(str(user_id))
        active["answers"][str(user_id)] = answer
        return previous

    def remove_answer(self, user_id: int) -> str | None:
        active = self._state["active_poll"]
        if active is None:
            return None
        return active["answers"].pop(str(user_id), None)

    def get_counts(self) -> dict[str, int]:
        counts = {answer: 0 for answer in ANSWERS}
        active = self._state["active_poll"]
        if active is not None:
            for answer in active["answers"].values():
                counts[answer] += 1
        return counts

    def get_next_run_at(self) -> datetime | None:
        return _aware_datetime(self._state["next_run_at"], "next_run_at")

    def set_next_run_at(self, value: datetime | None) -> None:
        if value is not None:
            _require_aware(value, "next_run_at")
        self._state["next_run_at"] = value.isoformat() if value else None

    def is_paused(self) -> bool:
        return bool(self._state["is_paused"])

    def set_paused(self, paused: bool) -> None:
        self._state["is_paused"] = paused

    def should_skip_next_run(self) -> bool:
        return bool(self._state["skip_next_run"])

    def set_skip_next_run(self, skip: bool) -> None:
        self._state["skip_next_run"] = skip
