import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_valocheck_persistence_dependency_boundaries() -> None:
    service_imports = _imports(ROOT / "services" / "valocheck_service.py")
    cog_imports = _imports(ROOT / "cogs" / "valocheck.py")
    repository_imports = _imports(
        ROOT / "repositories" / "valocheck_repository.py"
    )

    assert "storage.json_store" not in service_imports
    assert "storage.json_store" not in cog_imports
    assert "storage.json_store" in repository_imports
    assert not repository_imports.intersection(
        {"services", "cogs", "discord", "config", "aiohttp"}
    )
    assert "cogs" not in service_imports
