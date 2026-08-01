"""Cross-cutting dependency rules for persistence repositories."""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPOSITORY_PATHS = tuple(
    ROOT / "repositories" / name
    for name in (
        "joya_repository.py",
        "omikuji_repository.py",
        "xmas_repository.py",
        "valomap_repository.py",
        "valocheck_repository.py",
        "bump_panel_repository.py",
    )
)
SERVICE_PATHS = tuple(sorted((ROOT / "services").glob("*.py")))
COG_PATHS = tuple(sorted((ROOT / "cogs").glob("*.py")))
APPLICATION_PATHS = (
    *tuple(sorted(ROOT.glob("*.py"))),
    *REPOSITORY_PATHS,
    *SERVICE_PATHS,
    *COG_PATHS,
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
                if node.level:
                    imported.add(f"{path.parent.name}.{node.module}")
            elif node.level:
                imported.update(
                    f"{path.parent.name}.{alias.name}" for alias in node.names
                )
    return imported


def _imports_package(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def _dependency_graph(paths: tuple[Path, ...], package: str) -> dict[str, set[str]]:
    modules = {path.stem for path in paths}
    graph = {module: set() for module in modules}
    for path in paths:
        for imported in _imports(path):
            if imported.startswith(f"{package}."):
                dependency = imported.split(".", 1)[1].split(".", 1)[0]
                if dependency in modules:
                    graph[path.stem].add(dependency)
    return graph


def _assert_acyclic(graph: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str, route: tuple[str, ...]) -> None:
        if module in visiting:
            cycle = " -> ".join((*route, module))
            raise AssertionError(f"circular dependency: {cycle}")
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency, (*route, module))
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module, ())


def test_all_repositories_are_importable() -> None:
    for path in REPOSITORY_PATHS:
        importlib.import_module(f"repositories.{path.stem}")


def test_repository_import_boundaries() -> None:
    forbidden_packages = {
        "cogs",
        "services",
        "discord",
        "config",
        "aiohttp",
        "repositories",
    }
    for path in REPOSITORY_PATHS:
        imports = _imports(path)
        violations = {
            imported
            for imported in imports
            if any(
                _imports_package(imported, package)
                for package in forbidden_packages
            )
        }
        assert not violations, f"{path.name}: forbidden imports {violations}"
        assert "storage.json_store" in imports, path.name
        assert not {
            imported
            for imported in imports
            if _imports_package(imported, "storage")
            and imported != "storage.json_store"
        }, path.name

    storage_importers = {
        path
        for path in APPLICATION_PATHS
        if any(
            _imports_package(imported, "storage")
            for imported in _imports(path)
        )
    }
    assert storage_importers == set(REPOSITORY_PATHS)


def test_service_and_cog_import_boundaries() -> None:
    for path in SERVICE_PATHS:
        imports = _imports(path)
        assert not any(
            _imports_package(imported, "cogs") for imported in imports
        ), path.name
        assert not any(
            _imports_package(imported, "storage") for imported in imports
        ), path.name
    for path in COG_PATHS:
        assert not any(
            _imports_package(imported, "storage")
            for imported in _imports(path)
        ), path.name


def test_layer_internal_dependencies_are_acyclic() -> None:
    _assert_acyclic(_dependency_graph(REPOSITORY_PATHS, "repositories"))
    _assert_acyclic(_dependency_graph(SERVICE_PATHS, "services"))
    _assert_acyclic(_dependency_graph(COG_PATHS, "cogs"))


def test_repository_file_and_class_names_correspond() -> None:
    for path in REPOSITORY_PATHS:
        expected = "".join(
            part.capitalize() for part in path.stem.removesuffix("_repository").split("_")
        ) + "Repository"
        classes = {
            node.name
            for node in _tree(path).body
            if isinstance(node, ast.ClassDef)
        }
        assert expected in classes, f"{path.name}: expected {expected}"


def test_repositories_contain_no_discord_boundary_types() -> None:
    forbidden_names = {"discord", "Interaction", "Embed", "Role"}
    for path in REPOSITORY_PATHS:
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
        assert not re.search(
            r"\b(?:discord|Interaction|Embed|Role)\b",
            path.read_text(encoding="utf-8"),
        ), path.name


def test_repositories_do_not_read_environment_or_config() -> None:
    for path in REPOSITORY_PATHS:
        tree = _tree(path)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        os_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        }
        assert "get_config" not in calls, path.name
        assert not {"getenv", "environ"} & calls, path.name
        assert not {"getenv", "environ"} & os_attributes, path.name
