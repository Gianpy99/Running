"""Persistence layer (PRD §6). SQLite (local/tests) or PostgreSQL (production)."""

from .store import PostgresStore, SqliteStore, Store, open_store

__all__ = ["Store", "SqliteStore", "PostgresStore", "open_store"]
