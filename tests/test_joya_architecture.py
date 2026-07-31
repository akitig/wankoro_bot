import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_joya_persistence_dependency_boundaries() -> None:
    service_imports = _imports(ROOT / "services" / "joya_service.py")
    cog_imports = _imports(ROOT / "cogs" / "2026_joya_gacha.py")
    repository_imports = _imports(ROOT / "repositories" / "joya_repository.py")

    assert "storage.json_store" not in service_imports
    assert "storage.json_store" not in cog_imports
    assert "storage.json_store" in repository_imports
    assert not {"services", "cogs", "discord", "config"} & repository_imports
    assert "cogs" not in service_imports
