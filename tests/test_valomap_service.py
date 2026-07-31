import asyncio
import json
import logging
from pathlib import Path

import pytest

import services.valomap_service as valomap
from services.valomap_service import ValomapService


def _service(tmp_path: Path, fetch_maps=None) -> ValomapService:
    async def empty_fetch():
        return []

    return ValomapService(
        bans_path=tmp_path / "bans.json",
        fetch_maps=fetch_maps or empty_fetch,
    )


def test_api_maps_are_extracted_in_api_order_and_exclusions_are_preserved(
    tmp_path: Path,
) -> None:
    payload = [
        {"displayName": "Ascent", "isPlayableInCompetitive": True},
        {
            "displayName": "Bind",
            "isPlayableInCompetitive": False,
            "tacticalDescription": "A/B Sites",
        },
        {
            "displayName": "Range Practice",
            "isPlayableInCompetitive": False,
            "tacticalDescription": "Practice",
        },
        {"displayName": "Unused", "isPlayableInCompetitive": False},
    ]
    calls = 0

    async def fetch_maps():
        nonlocal calls
        calls += 1
        return payload

    service = _service(tmp_path, fetch_maps)

    first = asyncio.run(service.get_comp_maps())
    second = asyncio.run(service.get_comp_maps())

    assert [item["displayName"] for item in first] == ["Ascent", "Bind"]
    assert second is first
    assert calls == 1


def test_empty_api_result_is_retried_and_remains_empty(tmp_path: Path) -> None:
    calls = 0

    async def fetch_maps():
        nonlocal calls
        calls += 1
        return []

    service = _service(tmp_path, fetch_maps)

    assert asyncio.run(service.get_comp_maps()) == []
    assert asyncio.run(service.get_comp_maps()) == []
    assert calls == 2


def test_fetch_exception_and_invalid_json_propagate_without_response_logging(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response_body = "private-api-response"

    async def failing_fetch():
        raise ValueError(response_body)

    service = _service(tmp_path, failing_fetch)
    with caplog.at_level(logging.WARNING, logger=valomap.__name__):
        with pytest.raises(ValueError, match=response_body):
            asyncio.run(service.get_comp_maps())

    assert response_body not in caplog.text


def test_api_transport_failure_propagates(tmp_path: Path) -> None:
    async def failing_fetch():
        raise RuntimeError("transport failed")

    service = _service(tmp_path, failing_fetch)
    with pytest.raises(RuntimeError, match="transport failed"):
        asyncio.run(service.get_comp_maps())


def test_success_status_with_invalid_json_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            raise ValueError("invalid json")

    class Session:
        def __init__(self, *, headers):
            self.headers = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, _url):
            return Response()

    monkeypatch.setattr(valomap.aiohttp, "ClientSession", Session)
    with pytest.raises(ValueError, match="invalid json"):
        asyncio.run(ValomapService._fetch_maps_from_api())


@pytest.mark.parametrize("status", [404, 500])
def test_non_200_response_returns_empty_fallback_and_logs_status(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    captured = {}

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            raise AssertionError("json must not be read for non-200")

    response = Response()
    response.status = status

    class Session:
        def __init__(self, *, headers):
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, url):
            captured["url"] = url
            return response

    monkeypatch.setattr(valomap.aiohttp, "ClientSession", Session)
    with caplog.at_level(logging.WARNING, logger=valomap.__name__):
        result = asyncio.run(ValomapService._fetch_maps_from_api())

    assert result == []
    assert captured == {
        "headers": valomap.VALO_API_HEADERS,
        "url": valomap.VALO_API_URL,
    }
    assert f"VALORANT map API returned non-success status: {status}" in caplog.text


def test_success_response_parses_existing_data_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maps = [{"displayName": "Ascent"}]

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {"data": maps}

    class Session:
        def __init__(self, *, headers):
            self.headers = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, _url):
            return Response()

    monkeypatch.setattr(valomap.aiohttp, "ClientSession", Session)
    assert asyncio.run(ValomapService._fetch_maps_from_api()) == maps


def test_ban_state_missing_load_add_duplicate_remove_clear_and_save(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bans.json"
    service = _service(tmp_path)
    assert service.is_banned("Ascent") is False

    service.ban_map("Ascent")
    service.ban_map("Ascent")
    assert service.is_banned("Ascent") is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"bans": ["Ascent"]}

    service.unban_map("Ascent")
    assert service.is_banned("Ascent") is False
    service.ban_map("Bind")
    service.clear_bans()
    assert json.loads(path.read_text(encoding="utf-8")) == {"bans": []}


def test_ban_state_normal_load_available_listing_and_random_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "bans.json").write_text('{"bans": ["Bind"]}', encoding="utf-8")

    async def fetch_maps():
        return [
            {"displayName": "Ascent", "isPlayableInCompetitive": True},
            {"displayName": "Bind", "isPlayableInCompetitive": True},
        ]

    service = _service(tmp_path, fetch_maps)
    monkeypatch.setattr(valomap.random, "choice", lambda maps: maps[0])

    assert asyncio.run(service.get_map_listing()) == [
        ("Ascent", False),
        ("Bind", True),
    ]
    assert asyncio.run(service.get_available_maps()) == [
        {"displayName": "Ascent", "isPlayableInCompetitive": True}
    ]
    assert asyncio.run(service.select_random_map())["displayName"] == "Ascent"
    service.ban_map("Ascent")
    assert asyncio.run(service.select_random_map()) is None


def test_save_failure_logs_existing_message_without_runtime_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-map-name"
    service = _service(tmp_path)
    service._repository.add_ban(secret)

    def fail_save():
        raise OSError("disk failed")

    monkeypatch.setattr(service._repository, "save", fail_save)
    with caplog.at_level(logging.ERROR, logger=valomap.__name__):
        service.save_bans()

    assert "Failed to save VALORANT map bans" in caplog.text
    assert secret not in caplog.text


def test_service_delegates_ban_state_and_preserves_save_attempts(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    class RepositoryStub:
        def __init__(self) -> None:
            self.bans = {"Bind"}
            self.calls = []

        def get_bans(self):
            self.calls.append(("get",))
            return set(self.bans)

        def add_ban(self, name):
            self.calls.append(("add", name))
            self.bans.add(name)
            return True

        def remove_ban(self, name):
            self.calls.append(("remove", name))
            self.bans.discard(name)
            return True

        def clear_bans(self):
            self.calls.append(("clear",))
            self.bans.clear()
            return True

        def save(self):
            self.calls.append(("save",))

    repository = RepositoryStub()
    service._repository = repository

    assert service.is_banned("Bind") is True
    service.ban_map("Ascent")
    service.unban_map("Missing")
    service.clear_bans()

    assert repository.calls == [
        ("get",),
        ("add", "Ascent"),
        ("save",),
        ("get",),
        ("remove", "Missing"),
        ("save",),
        ("get",),
        ("clear",),
        ("save",),
        ("get",),
    ]
