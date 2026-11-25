"""Static pins + regression tests for the 2026-11-24 DB fix round.

Pins the fixes from the DB Structure & Data-Integrity Review (v1) — the
QA agent proved these live on the Postgres sandbox, the fix round applied
them. Assert the exact code shape so a regression reverts the test with it:

- DB1  app/migrate.py carries the 9 hot-path indexes (a7c2e9f41d05) — they
       never reached the live DB because Alembic has never run on it.
- DB2  app/migrate.py adds the 3 self-referencing parent FKs the live DB was
       built without (sub-issues / sub-tasks / escalations had no integrity).
- A1   the 10 flush-only write routes commit AFTER their audit write —
       the ActivityLog row used to roll back with the request session
       (live-only failure; same-session tests read flushed rows).
- D1   delete_project sweeps stakeholders first (NO ACTION FK + NOT NULL
       project_id → live Postgres 500'd on any project with stakeholders).
- D2   delete_user sweeps the NO ACTION children first (notifications +
       preferences deleted, activity history null-out to survive the user).
- D3   functional: DELETE a project WITH stakeholders returns 204.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIGRATE_PY = REPO / "app/migrate.py"
TAGS_PY = REPO / "app/routers/tags.py"
AGENTS_PY = REPO / "app/routers/agents.py"
SHARE_PY = REPO / "app/routers/share.py"
PROOFS_PY = REPO / "app/routers/proofs.py"
USER_TASKS_PY = REPO / "app/routers/user_tasks.py"
GUEST_LINKS_PY = REPO / "app/routers/guest_links.py"
GITHUB_SYNC_PY = REPO / "app/routers/github_sync.py"
PROJECTS_PY = REPO / "app/routers/projects.py"
STAKEHOLDERS_PY = REPO / "app/routers/stakeholders.py"

HOT_PATH_INDEXES = [
    "ix_backlog_items_project_id",
    "ix_backlog_items_current_phase",
    "ix_approval_steps_request_id",
    "ix_approval_steps_status",
    "ix_decision_records_project_created",
    "ix_user_tasks_assigned_to",
    "ix_kpis_project_id",
    "ix_release_items_release_id",
    "ix_projects_status",
]

SELF_REF_FKS = [
    '("backlog_items", "parent_item_id", "CASCADE")',
    '("risks", "escalated_from_id", "SET NULL")',
    '("user_tasks", "parent_task_id", "CASCADE")',
]


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def _py_body(src: str, name: str) -> str:
    """A top-level def body: from its def line to the next top-level block."""
    m = re.search(rf"^def {name}\(.*?(?=^def |^@|^class |\Z)", src, re.S | re.M)
    assert m, f"{name} missing"
    return m.group(0)


def _audit_followed_by_commit(src: str, marker: str) -> None:
    """The log_activity call containing `marker` must commit before it returns."""
    idx = src.find(marker)
    assert idx != -1, f"{marker} missing"
    call = src.rfind("log_activity(", 0, idx)
    assert call != -1, f"no log_activity call before {marker}"
    window = src[call:call + 1500]
    end = len(window)
    for stop in ("\n    return", "\n    finally:", "\n\n    finally:"):
        pos = window.find(stop)
        if pos != -1:
            end = min(end, pos)
    segment = window[:end]
    assert "db.commit()" in segment, (
        f"audit write ({marker}) is not committed — it rolls back with the request session"
    )


# ── DB1 — the 9 hot-path indexes are in the de-facto migration source ────


def test_db1_migrate_has_hot_path_indexes():
    """app/migrate.py carries all 9 a7c2e9f41d05 indexes (Alembic never runs)."""
    src = _read(MIGRATE_PY)
    for name in HOT_PATH_INDEXES:
        assert name in src, f"{name} missing from app/migrate.py INDEXES"


def test_db1_migrate_index_definitions_match_the_alembic_revision():
    """Columns match a7c2e9f41d05 exactly — decisions is a composite, newest-first."""
    src = _read(MIGRATE_PY)
    assert '("ix_decision_records_project_created", "decision_records", "project_id, made_at")' in src


# ── DB2 — the 3 self-referencing parent FKs ──────────────────────────────


def test_db2_migrate_declares_self_ref_fks():
    """ondelete matches the model declarations (backlog_item.py/risk.py/user_task.py)."""
    src = _read(MIGRATE_PY)
    for pair in SELF_REF_FKS:
        assert pair in src, f"{pair} missing from SELF_REF_FKS"


def test_db2_run_migrations_calls_the_self_ref_fk_fix():
    src = _read(MIGRATE_PY)
    body = _py_body(src, "run_migrations")
    assert "_add_missing_self_ref_fks()" in body, "the FK fix never runs"


def test_db2_fk_idempotence_checks_read_options():
    """get_foreign_keys reports ondelete under options — a top-level read never
    matches, so every startup drop+recreates the FKs (the 2026-11-25 bug)."""
    src = _read(MIGRATE_PY)
    assert 'existing.get("ondelete")' not in src, "broken idempotence check is back"
    assert src.count('(existing.get("options") or {}).get("ondelete", "").upper()') == 2


# ── A1 — the 10 flush-only routes commit their audit writes ──────────────


def test_a1_attach_item_tag_commits_audit():
    _audit_followed_by_commit(_read(TAGS_PY), "Tagged '{item.title[:100]}' with #{tag.name}")


def test_a1_attach_task_tag_commits_audit():
    _audit_followed_by_commit(_read(TAGS_PY), "Tagged '{task.title[:100]}' with #{tag.name}")


def test_a1_create_rule_commits_audit():
    _audit_followed_by_commit(_read(AGENTS_PY), "Created agent: {rule.name[:80]}")


def test_a1_create_share_link_commits_audit():
    _audit_followed_by_commit(_read(SHARE_PY), "Created {body.scope} share link")


def test_a1_upload_proof_commits_audit():
    _audit_followed_by_commit(_read(PROOFS_PY), "Uploaded proof v{proof.version}")


def test_a1_create_task_commits_audit():
    _audit_followed_by_commit(_read(USER_TASKS_PY), "Created task: {db_task.title}")


def test_a1_create_guest_link_commits_audit():
    _audit_followed_by_commit(_read(GUEST_LINKS_PY), "Created guest link for: {request.title[:80]}")


def test_a1_github_config_update_commits_audit():
    _audit_followed_by_commit(_read(GITHUB_SYNC_PY), "Updated GitHub board config")


def test_a1_github_export_commits_audit():
    _audit_followed_by_commit(_read(GITHUB_SYNC_PY), "Exported {result.exported} items")


def test_a1_github_import_commits_audit():
    _audit_followed_by_commit(_read(GITHUB_SYNC_PY), "Imported status from GitHub")


# ── D1/D2 — the delete paths sweep NO ACTION children first ──────────────


def test_d1_delete_project_sweeps_stakeholders():
    """Stakeholders deleted before db.delete(project) — live Postgres 500'd."""
    src = _read(PROJECTS_PY)
    body = _py_body(src, "delete_project")
    assert "Stakeholder.project_id == project_id" in body, "stakeholder sweep missing"
    assert body.find("Stakeholder.project_id") < body.find("db.delete(project)"), (
        "the sweep must run before db.delete(project)"
    )


def test_d2_delete_user_sweeps_no_action_children():
    """notifications + preferences deleted, activity history null-out to survive."""
    src = _read(STAKEHOLDERS_PY)
    body = _py_body(src, "delete_user")
    assert "ActivityLog.user_id == user_id" in body, "activity null-out missing"
    assert '"user_id": None' in body, "history must survive the user (null-out, not delete)"
    assert "Notification.user_id == user_id" in body, "notifications sweep missing"
    assert "NotificationPreference.user_id == user_id" in body, "preferences sweep missing"
    assert body.find("ActivityLog.user_id") < body.find("db.delete(user)"), (
        "the sweeps must run before db.delete(user)"
    )


# ── D3 — functional regression: delete a project WITH stakeholders ───────


def test_d3_delete_project_with_stakeholder(client):
    """DELETE /api/projects/{id} with stakeholders returns 204 (was a live 500)."""
    client_id = client.post("/api/clients", json={
        "name": "Fix Round Client",
        "contact_email": "fixround@test.com",
    }).json()["id"]
    project_id = client.post("/api/projects", json={
        "name": "Fix Round Delete",
        "client_id": client_id,
    }).json()["id"]
    resp = client.post(f"/api/projects/{project_id}/stakeholders", json={
        "name": "QA Lead",
        "role_name": "QA Lead",
    })
    assert resp.status_code == 201, "stakeholder setup failed"

    response = client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 204
