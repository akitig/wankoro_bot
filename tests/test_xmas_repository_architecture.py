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


def test_xmas_persistence_dependency_boundaries() -> None:
    service_imports = _imports(ROOT / "services" / "xmas_service.py")
    cog_imports = _imports(ROOT / "cogs" / "2025_xmas_gacha.py")
    repository_imports = _imports(ROOT / "repositories" / "xmas_repository.py")

    assert "storage.json_store" not in service_imports
    assert "storage.json_store" not in cog_imports
    assert "storage.json_store" in repository_imports
    assert not {"services", "cogs", "discord", "config"} & repository_imports
    assert "cogs" not in service_imports
    assert not any(name.startswith("cogs.") for name in service_imports)
