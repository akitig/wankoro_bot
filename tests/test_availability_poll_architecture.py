import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
COG = ROOT / "cogs" / "availability_poll.py"
SERVICE = ROOT / "services" / "availability_poll_service.py"
REPOSITORY = ROOT / "repositories" / "availability_poll_repository.py"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_dependency_direction_and_storage_boundary() -> None:
    assert "services.availability_poll_service" in imports(COG)
    assert "repositories.availability_poll_repository" in imports(SERVICE)
    assert "storage.json_store" in imports(REPOSITORY)
    assert "storage.json_store" not in imports(SERVICE)
    assert not any(name.startswith("cogs") for name in imports(SERVICE))
    forbidden = ("cogs", "services", "discord", "config", "aiohttp", "repositories")
    assert not {
        name
        for name in imports(REPOSITORY)
        if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    }


def test_no_environment_access_or_import_side_effect_calls() -> None:
    for path in (SERVICE, REPOSITORY):
        source = path.read_text(encoding="utf-8")
        assert "get_config" not in source
        assert "os.getenv" not in source
        assert "os.environ" not in source
        assert "load_dotenv" not in source


def test_cog_does_not_build_audit_embeds_or_sync_in_on_ready() -> None:
    source = COG.read_text(encoding="utf-8")
    assert "discord.Embed" not in source
    assert "tree.sync" not in source
    assert "tree.add_command" not in source
    assert "on_ready" not in source
