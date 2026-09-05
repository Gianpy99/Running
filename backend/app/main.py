"""ASGI entry point: `uvicorn app.main:app --app-dir backend`."""

from .api import create_app

app = create_app()
