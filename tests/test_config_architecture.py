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
