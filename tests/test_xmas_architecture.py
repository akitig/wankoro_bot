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


def test_xmas_service_does_not_import_cog() -> None:
    service_imports = _imports(ROOT / "services" / "xmas_service.py")
    assert "cogs" not in service_imports
    assert not any(name.startswith("cogs.") for name in service_imports)
