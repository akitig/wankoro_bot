import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_valomap_dependency_and_state_boundaries() -> None:
    cog_path = ROOT / "cogs" / "valomap.py"
    service_path = ROOT / "services" / "valomap_service.py"
    repository_path = ROOT / "repositories" / "valomap_repository.py"
    cog_imports = _imports(cog_path)
    service_imports = _imports(service_path)
    repository_imports = _imports(repository_path)
    cog_source = cog_path.read_text(encoding="utf-8")

    assert "cogs" not in service_imports
    assert not any(name.startswith("cogs.") for name in service_imports)
    assert not any(name.startswith("services.") for name in service_imports)
    assert "storage.json_store" not in cog_imports
    assert "storage.json_store" not in service_imports
    assert "storage.json_store" in repository_imports
    assert not {
        "services",
        "cogs",
        "discord",
        "config",
        "aiohttp",
    } & repository_imports
    assert "cached_maps" not in cog_source
    assert "banned_maps" not in cog_source


def test_on_ready_contains_no_command_registration_or_sync() -> None:
    tree = ast.parse((ROOT / "cogs" / "valomap.py").read_text(encoding="utf-8"))
    on_ready = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_ready"
    )
    attributes = {
        node.attr for node in ast.walk(on_ready) if isinstance(node, ast.Attribute)
    }
    assert "sync" not in attributes
    assert "add_command" not in attributes
