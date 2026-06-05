"""Path utilities."""

from __future__ import annotations

import os
from pathlib import Path


def get_project_root() -> Path:
    return Path(os.environ.get("ROSCLAW_DARWIN_HOME", "/code/rosclaw-darwin")).resolve()


def get_data_root() -> Path:
    return Path(os.environ.get("ROSCLAW_DARWIN_DATA", str(get_project_root() / "data"))).resolve()


def ensure_writable_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    test_file = p / ".write_test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as exc:
        raise RuntimeError(
            f"Directory is not writable: {p}. "
            f"Please fix permissions or pass --out explicitly. Original error: {exc}"
        ) from exc
    return p


def ensure_dir(path: str | Path) -> Path:
    """Deprecated: use ensure_writable_dir for all production paths.

    This wrapper is kept for backward compatibility in tests.
    """
    return ensure_writable_dir(path)
