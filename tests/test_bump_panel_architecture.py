import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
COG = ROOT / "cogs" / "bump_panel.py"
SERVICE = ROOT / "services" / "bump_panel_service.py"
REPOSITORY = ROOT / "repositories" / "bump_panel_repository.py"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_bump_panel_dependency_direction() -> None:
    assert "services.bump_panel_service" in imports(COG)
    assert "repositories.bump_panel_repository" in imports(SERVICE)
    assert "storage.json_store" in imports(REPOSITORY)
    assert not any(name.startswith("cogs") for name in imports(SERVICE))
    forbidden = {"config", "discord", "aiohttp", "services", "cogs"}
    assert not {
        name
        for name in imports(REPOSITORY)
        if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    }


def test_only_repository_imports_json_storage() -> None:
    assert "storage.json_store" not in imports(COG)
    assert "storage.json_store" not in imports(SERVICE)
    assert "storage.json_store" in imports(REPOSITORY)


def test_service_and_repository_do_not_read_environment() -> None:
    for path in (SERVICE, REPOSITORY):
        source = path.read_text(encoding="utf-8")
        assert "get_config" not in source
        assert "os.getenv" not in source
        assert "os.environ" not in source
        assert "load_dotenv" not in source


def test_persistent_view_is_not_registered_in_on_ready() -> None:
    source = COG.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(COG))
    on_ready = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_ready"
    )
    ready_source = ast.get_source_segment(source, on_ready) or ""
    assert "add_view" not in ready_source
    assert "tree.sync" not in ready_source
