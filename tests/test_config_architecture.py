import ast
from pathlib import Path


def _imports(tree: ast.AST) -> set[str]:
    names = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    names.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return names


def _application_modules(*directories: str) -> list[Path]:
    return [
        path
        for directory in directories
        for path in sorted(Path(directory).glob("*.py"))
    ]


def test_repositories_do_not_import_config() -> None:
    for path in _application_modules("repositories"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert "config" not in _imports(tree), path


def test_repositories_and_services_do_not_read_environment() -> None:
    forbidden_calls = {"getenv", "load_dotenv"}
    for path in _application_modules("repositories", "services"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                assert name not in forbidden_calls, path

            if isinstance(node, ast.Attribute):
                assert not (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "os"
                    and node.attr == "environ"
                ), path


def test_environment_loading_is_confined_to_config() -> None:
    for path in _application_modules("cogs", "repositories", "services"):
        source = path.read_text(encoding="utf-8")
        assert "load_dotenv" not in source, path
        assert "os.getenv" not in source, path
        assert "os.environ" not in source, path

"""Static dependency rules for application configuration."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
COG_PATHS = tuple(sorted((ROOT / "cogs").glob("*.py")))
SERVICE_PATHS = tuple(sorted((ROOT / "services").glob("*.py")))
REPOSITORY_PATHS = tuple(sorted((ROOT / "repositories").glob("*_repository.py")))
APPLICATION_PATHS = (
    ROOT / "main.py",
    *COG_PATHS,
    *SERVICE_PATHS,
    *REPOSITORY_PATHS,
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _calls(path: Path, function_name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
        for node in ast.walk(_tree(path))
    )


def test_services_and_repositories_do_not_import_config() -> None:
    for path in (*SERVICE_PATHS, *REPOSITORY_PATHS):
        imports = _imports(path)
        assert not any(
            imported == "config" or imported.startswith("config.")
            for imported in imports
        ), path.name
        assert not _calls(path, "get_config"), path.name


def test_get_config_is_limited_to_cogs_and_process_bootstrap() -> None:
    callers = {path for path in APPLICATION_PATHS if _calls(path, "get_config")}
    assert callers == {ROOT / "main.py", *COG_PATHS}


def test_only_config_module_reads_environment() -> None:
    forbidden_names = {"getenv", "environ", "load_dotenv"}
    for path in APPLICATION_PATHS:
        tree = _tree(path)
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert not forbidden_names & (names | attributes), path.name
