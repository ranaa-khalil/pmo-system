"""Alembic migration acceptance tests — R0 baseline integrity (ADR-04).

The baseline revision must recreate the FULL schema from the app's models on
a fresh database (a tmp DB FILE — not in-memory, so the migration actually
runs against a real database), and the stamp path must work for an existing
DB: stamp head records the baseline so `upgrade` only ever applies NEW
revisions and never re-runs the baseline DDL on a populated schema.
"""
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401 — register all models with Base.metadata
from alembic import command
from app.database import Base

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _alembic_config(db_url: str) -> Config:
    """Alembic Config pointed at the repo's env.py and a specific test DB."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


class TestAlembicBaseline:
    def test_upgrade_head_on_fresh_db_creates_every_model_table(self, tmp_path):
        """`alembic upgrade head` on a fresh empty DB creates every table the
        46 models register with Base.metadata — and nothing else."""
        db_url = f"sqlite:///{tmp_path / 'fresh.db'}"
        command.upgrade(_alembic_config(db_url), "head")

        inspector = inspect(create_engine(db_url))
        created = set(inspector.get_table_names()) - {"alembic_version"}
        assert created == set(Base.metadata.tables.keys())

    def test_stamp_head_on_existing_db_then_upgrade_is_safe(self, tmp_path):
        """Existing-DB path: a DB with one hand-made table (the app.migrate
        bootstrap state) has no alembic_version — stamp head records the
        baseline, and upgrade at head completes without erroring on the
        existing table or touching it."""
        db_url = f"sqlite:///{tmp_path / 'existing.db'}"
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE tenants ("
                " id INTEGER PRIMARY KEY,"
                " name VARCHAR(255) NOT NULL,"
                " slug VARCHAR(100) NOT NULL)"
            ))

        cfg = _alembic_config(db_url)
        command.stamp(cfg, "head")
        head = _head_revision(cfg)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head

        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head
            columns = {c["name"] for c in inspect(conn).get_columns("tenants")}
        assert {"id", "name", "slug"} <= columns

    def test_upgrade_without_stamp_on_populated_db_raises(self, tmp_path):
        """Documents WHY the stamp-if-needed step exists (run-migration.sh):
        the frozen baseline DDL would collide with a table the bootstrap
        already created — the stamp path is the guard, never a bare upgrade."""
        db_url = f"sqlite:///{tmp_path / 'partial.db'}"
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE tenants (id INTEGER PRIMARY KEY)"))

        with pytest.raises(Exception):
            command.upgrade(_alembic_config(db_url), "head")
