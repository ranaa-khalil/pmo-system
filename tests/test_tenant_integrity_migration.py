"""Tenant-integrity revision acceptance tests — Product Review §4 P0.

The live DB was built by app/migrate.py and has NO alembic_version — the
live-apply sequence is STAMP first (the 6 existing revisions, no DDL), then
upgrade. These tests exercise both paths on a scratch SQLite DB FILE (not
in-memory, so the revision actually runs against a real database):

- the stamp-then-upgrade path: a bootstrap schema (Base.metadata.create_all —
  what app.migrate's create_all builds, tenant_id nullable everywhere) with
  NULL-tenant rows backfills to the single tenant and applies NOT NULL;
- the fresh-deploy path: `upgrade head` creates every table with tenant
  integrity already locked;
- the writers that still omit tenant_id keep their column nullable (a NOT
  NULL there would 500 the live write paths — notifications, form seeds,
  the worker's beat_runs, the raw task_assignees inserts);
- the revision is idempotent and the backfill derives from project_id
  before the single-tenant fallback (multi-tenant safety).
"""
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 — register all models with Base.metadata
from alembic import command
from app.database import Base
from app.models.activity_log import ActivityLog
from app.models.client import Client
from app.models.notification import Notification
from app.models.project import Project
from app.models.tenant import Tenant

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
REVISION = "c9d4e8f2a6b1"
PREVIOUS_HEAD = "a7c2e9f41d05"


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _bootstrap_schema(db_url: str) -> object:
    """The app.migrate bootstrap state: full model schema, tenant_id nullable."""
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    return engine


class TestTenantIntegrityRevision:
    def test_stamp_then_upgrade_backfills_and_locks(self, tmp_path):
        """The live-apply sequence on a bootstrap schema with legacy NULL rows."""
        db_url = f"sqlite:///{tmp_path / 'live.db'}"
        engine = _bootstrap_schema(db_url)

        with Session(engine) as s:
            s.add(Tenant(name="OPEX", slug="opex"))
            s.commit()
            legacy_client = Client(name="OPEX Client")  # pre-tenancy row
            s.add(legacy_client)
            s.commit()
            s.add(Project(name="PNU Cloud", client_id=legacy_client.id))
            s.commit()

        cfg = _alembic_config(db_url)
        command.stamp(cfg, PREVIOUS_HEAD)
        command.upgrade(cfg, "head")
        assert _version(engine) == REVISION

        with Session(engine) as s:
            # Backfilled to the single tenant
            project = s.query(Project).first()
            assert project.tenant_id is not None
            tenant_id = project.tenant_id
            # NOT NULL is live: a tenant-less business row is refused
            with pytest.raises(IntegrityError):
                s.add(Project(name="No Tenant Row"))
                s.commit()
            s.rollback()
            # The writers that omit tenant_id keep writing (nullable kept)
            s.add(Notification(user_id=1, type="automation", title="legacy writer"))
            s.commit()

        with engine.connect() as conn:
            cols = {c["name"]: c for c in inspect(conn).get_columns("projects")}
            assert cols["tenant_id"]["nullable"] is False
            n_cols = {c["name"]: c for c in inspect(conn).get_columns("notifications")}
            assert n_cols["tenant_id"]["nullable"] is True
        engine.dispose()

    def test_upgrade_head_on_fresh_db_locks_tenant_integrity(self, tmp_path):
        """Fresh deploy: every safe table is NOT NULL, unsafe stay nullable,
        and the 3 model-declared self-ref FKs exist."""
        db_url = f"sqlite:///{tmp_path / 'fresh.db'}"
        cfg = _alembic_config(db_url)
        command.upgrade(cfg, "head")
        assert _version(create_engine(db_url)) == REVISION

        inspector = inspect(create_engine(db_url))
        for table in ("projects", "backlog_items", "releases", "approval_requests",
                      "activity_logs", "ai_interactions", "comments"):
            cols = {c["name"]: c for c in inspector.get_columns(table)}
            assert "tenant_id" in cols, f"{table} missing tenant_id"
            assert cols["tenant_id"]["nullable"] is False, f"{table} tenant_id still nullable"
        for table in ("notifications", "form_templates", "form_instances",
                      "notification_preferences", "beat_runs"):
            cols = {c["name"]: c for c in inspector.get_columns(table)}
            assert cols["tenant_id"]["nullable"] is True, f"{table} must stay nullable"
        # task_assignees' model never declared the column — on a fresh schema
        # it doesn't exist at all (legacy DBs get it via app/migrate.py only)
        assert "tenant_id" not in {c["name"] for c in inspector.get_columns("task_assignees")}
        fks = inspector.get_foreign_keys("backlog_items")
        assert any("parent_item_id" in fk["constrained_columns"]
                   and fk["referred_table"] == "backlog_items" for fk in fks)

    def test_upgrade_is_idempotent(self, tmp_path):
        """Running the revision twice changes nothing and errors nowhere."""
        db_url = f"sqlite:///{tmp_path / 'live.db'}"
        engine = _bootstrap_schema(db_url)
        with Session(engine) as s:
            s.add(Tenant(name="OPEX", slug="opex"))
            s.commit()
            client = Client(name="OPEX Client")
            s.add(client)
            s.commit()
            s.add(Project(name="PNU Cloud", client_id=client.id))
            s.commit()

        cfg = _alembic_config(db_url)
        command.stamp(cfg, PREVIOUS_HEAD)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # again — no-op

        assert _version(engine) == REVISION
        with Session(engine) as s:
            assert s.query(Project).first().tenant_id is not None
        engine.dispose()

    def test_backfill_derives_from_project_before_the_fallback(self, tmp_path):
        """With two tenants the single-tenant fallback never fires: rows with
        a project_id derive from THEIR project's tenant, ambiguous rows stay
        NULL and their table stays nullable."""
        db_url = f"sqlite:///{tmp_path / 'multi.db'}"
        engine = _bootstrap_schema(db_url)
        with Session(engine) as s:
            t1 = Tenant(name="One", slug="one")
            t2 = Tenant(name="Two", slug="two")
            s.add_all([t1, t2])
            s.commit()
            s.refresh(t1)
            s.refresh(t2)
            c2 = Client(name="Two Client", tenant_id=t2.id)
            s.add(c2)
            s.commit()
            s.refresh(c2)
            p2 = Project(name="In Two", client_id=c2.id, tenant_id=t2.id)
            s.add(p2)
            s.commit()
            s.refresh(p2)
            s.add(ActivityLog(project_id=p2.id, entity_type="backlog_item",
                              entity_id=1, action="created", summary="legacy row"))
            s.add(ActivityLog(entity_type="backlog_item", entity_id=2,
                              action="created", summary="no project at all"))
            s.commit()
            expected_tenant_id = t2.id

        cfg = _alembic_config(db_url)
        command.stamp(cfg, PREVIOUS_HEAD)
        command.upgrade(cfg, "head")

        with Session(engine) as s:
            logs = {log.summary: log.tenant_id for log in s.query(ActivityLog).all()}
            assert logs["legacy row"] == expected_tenant_id  # derived from ITS project
            assert logs["no project at all"] is None  # ambiguous: left NULL
        with engine.connect() as conn:
            cols = {c["name"]: c for c in inspect(conn).get_columns("activity_logs")}
            assert cols["tenant_id"]["nullable"] is True  # NOT NULL skipped, not forced
        engine.dispose()
