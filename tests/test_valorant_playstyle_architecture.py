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


def test_playstyle_core_is_discord_independent_and_layered() -> None:
    repository_imports = _imports(
        ROOT / "repositories" / "valorant_playstyle_repository.py"
    )
    service_imports = _imports(ROOT / "services" / "valorant_playstyle_service.py")

    assert "storage.json_store" in repository_imports
    assert "repositories.valorant_playstyle_repository" in service_imports
    for imports in (repository_imports, service_imports):
        assert not {"discord", "config", "cogs", "aiohttp"} & imports
    assert "storage.json_store" not in service_imports


def test_playstyle_cog_does_not_change_roles_or_depend_on_recruitment() -> None:
    source = (ROOT / "cogs" / "valorant_playstyle.py").read_text(encoding="utf-8")

    assert ".add_roles(" not in source
    assert ".remove_roles(" not in source
    assert "VALO_ROLE_GACHI_ID" not in source
    assert "VALO_ROLE_ENJOY_ID" not in source
    assert "valorecruit" not in source
