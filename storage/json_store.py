"""UTF-8 JSON persistence with atomic file replacement."""

from __future__ import annotations

import copy
import json
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
PathLike = str | os.PathLike[str]


def load_json(path: PathLike) -> Any:
    """Load and decode a UTF-8 JSON file.

    Missing files and invalid JSON are intentionally distinct: both are raised,
    while invalid JSON is also logged without including file contents.
    """

    target = Path(path)
    try:
        with target.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError:
        logger.exception("Invalid JSON file: %s", target)
        raise
    except OSError:
        logger.exception("Unable to read JSON file: %s", target)
        raise


def load_json_or_default(path: PathLike, default: T) -> Any | T:
    """Load JSON, returning an independent copy of default only when absent."""

    try:
        return load_json(path)
    except FileNotFoundError:
        return copy.deepcopy(default)


def save_json_atomic(path: PathLike, data: Any) -> None:
    """Serialize data as UTF-8 JSON and atomically replace the destination."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())

        if target.exists():
            temporary_path.chmod(stat.S_IMODE(target.stat().st_mode))
        os.replace(temporary_path, target)
        temporary_path = None
    except (OSError, TypeError, ValueError):
        logger.exception("Unable to save JSON file: %s", target)
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
