"""Load project-root ``.env`` before Django reads ``os.environ``."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(_ROOT / ".env")
