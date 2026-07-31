import ast
import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import main


def test_all_cogs_import_and_expose_setup() -> None:
    for module_name in main.COGS:
        module = importlib.import_module(module_name)
        assert callable(getattr(module, "setup", None)), module_name


def test_all_services_import_without_importing_cogs() -> None:
    for path in sorted(Path("services").glob("*.py")):
        importlib.import_module(f"services.{path.stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name == "cogs" or name.startswith("cogs.") for name in imported)


def test_command_sync_is_centralized_outside_on_ready() -> None:
    for path in Path("cogs").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == "on_ready":
                    ready_source = ast.get_source_segment(source, node) or ""
                    assert ".tree.sync(" not in ready_source, path
                    assert ".tree.add_command(" not in ready_source, path


def test_startup_rejects_missing_discord_token_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def start(token: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(main, "config", SimpleNamespace(discord_token=None))
    monkeypatch.setattr(main.bot, "start", start)

    with pytest.raises(
        RuntimeError,
        match="Missing environment variable: DISCORD_TOKEN",
    ):
        asyncio.run(main.main())

    assert called is False
