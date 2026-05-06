#!/usr/bin/env python
"""Django management entrypoint.

Usage:
    python manage.py rundaemon                     # run the daemon (interactive onboarding)
    python manage.py rundaemon --onboard config.json  # non-interactive onboarding
    python manage.py runserver                     # Django Admin at http://localhost:8000/admin/
    python manage.py migrate                       # run Django migrations
    python manage.py createsuperuser
"""
import os
import sys
import warnings

# langchain-openai stores a Pydantic model in a dict-typed field, triggering
# a harmless serialization warning on every structured-output call.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

from linkedin.env_bootstrap import load_project_dotenv

load_project_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin.django_settings")


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise SystemExit(
            "Python 3.10+ is required for this backend (Django>=5.2). "
            f"Current interpreter: {sys.version.split()[0]}.\n"
            "Recreate venv with a newer interpreter, e.g.:\n"
            "  python3.12 -m venv .venv && source .venv/bin/activate\n"
            "  python -m pip install -r requirements/local.txt"
        )
    try:
        from django.core.management import execute_from_command_line
    except ModuleNotFoundError as exc:
        if exc.name == "django":
            raise SystemExit(
                "Django is not installed in the active environment.\n"
                "Use interpreter-specific pip to avoid global/user pip mismatch:\n"
                "  python -m pip install --upgrade pip\n"
                "  python -m pip install -r requirements/local.txt"
            ) from exc
        raise

    # Bare `python manage.py` with no args → run the daemon (backward compat).
    if len(sys.argv) == 1:
        sys.argv = [sys.argv[0], "rundaemon"]

    execute_from_command_line(sys.argv)
