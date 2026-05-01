"""Load project-root ``.env`` before Django reads ``os.environ``."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    # Ensure project-root `.env` is the single source of truth across machines.
    # - override=True prevents stale shell exports from silently winning.
    # - interpolate=False keeps raw values (safer for passwords with `$` etc.).
    load_dotenv(_ROOT / ".env", override=True, interpolate=False)
