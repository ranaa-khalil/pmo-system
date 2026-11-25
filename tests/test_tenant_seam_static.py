"""Static pins for Tenant P1 — the ONE scoping seam (2026-11-25).

Pins the seam + the hot-router migration so a regression reverts the test
with it (the test_p0_fix_round_static.py pattern):

- S1  the seam exists once: app/services/scope.tenant_scoped(db, model,
      tenant_id) — a query pre-filtered to the tenant, with the rule in its
      docstring: every tenant-scoped read goes through it.
- S2  the HOT routers (dashboard, projects, backlog, releases, approvals,
      copilot/ai, clients, stakeholders, tags, user_tasks) and the delegate
      services their hot routes run through (stats, schedule, copilot) import
      the seam and route their entity reads through it — the exact number of
      seam call sites per file is pinned.
- S3  the hot files' remaining inline ``tenant_id ==`` fragments are EXACTLY
      the seam's documented exclusions (join/membership checks, column
      queries, User.active_tenant_id) — a forgotten fragment (the quiet leak
      vector) fails here; migrate it through the seam or document the
      exclusion.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCOPE_PY = REPO / "app/services/scope.py"

# The hot routers + the delegate services their hot routes run through
# (dashboard delegates to stats/schedule; the copilot endpoints in ai.py
# delegate to services/copilot.py).
HOT_FILES = [
    "app/routers/dashboard.py", "app/routers/projects.py", "app/routers/backlog.py",
    "app/routers/releases.py", "app/routers/approvals.py", "app/routers/ai.py",
    "app/routers/clients.py", "app/routers/stakeholders.py", "app/routers/tags.py",
    "app/routers/user_tasks.py",
    "app/services/stats.py", "app/services/schedule.py", "app/services/copilot.py",
]

# Pinned seam call sites per hot file (the migration's shape — a regression
# that silently un-migrates a query drops the count with it).
SEAM_SITES = {
    "app/routers/dashboard.py": 3,
    "app/routers/projects.py": 6,
    "app/routers/backlog.py": 27,
    "app/routers/releases.py": 25,
    "app/routers/approvals.py": 13,
    "app/routers/ai.py": 17,
    "app/routers/clients.py": 4,
    "app/routers/stakeholders.py": 29,
    "app/routers/tags.py": 8,
    "app/routers/user_tasks.py": 11,
    "app/services/stats.py": 4,
    "app/services/schedule.py": 1,
    "app/services/copilot.py": 9,
}

# Every inline `tenant_id ==` fragment left in a hot file, each carried by the
# seam's documented exclusion — never a tenant-owned entity read.
ALLOWED_INLINE = {
    "app/routers/dashboard.py": [
        "TenantMembership.tenant_id == current_tenant.id",  # workload members: JOIN-table filter
    ],
    "app/routers/backlog.py": [
        "BacklogItem.tenant_id == current_tenant.id",  # phase rail: item_type COLUMN query (tuple rows)
    ],
    "app/routers/stakeholders.py": [
        "User.active_tenant_id == tid",  # users directory: active-tenant FK, not a tenant-owned entity
    ],
    "app/routers/user_tasks.py": [
        "TenantMembership.tenant_id == tenant_id",  # assignee membership check
    ],
    "app/services/stats.py": [
        "Client.tenant_id == tid",  # AM client ids: Client.id COLUMN query (tuple rows)
    ],
    "app/services/copilot.py": [
        "Project.tenant_id == tid",  # _assigned_project_ids: Project.id COLUMN query
        "TenantMembership.tenant_id == tenant.id",  # assign_user: assignee membership check
    ],
}


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


# ── S1 — the seam exists once, with the rule ──────────────────────────────


def test_s1_seam_exists_with_the_contract():
    """tenant_scoped returns db.query(model).filter(model.tenant_id == tid)
    and states the rule: every tenant-scoped read goes through it."""
    src = _read(SCOPE_PY)
    assert "def tenant_scoped(db: Session, model: type, tenant_id: int) -> Query:" in src, (
        "the ONE scoping seam lives in app/services/scope.py"
    )
    assert "return db.query(model).filter(model.tenant_id == tenant_id)" in src, (
        "the seam pre-filters the query to the tenant (same filter, same 404/[] behavior)"
    )
    assert "every tenant-scoped READ" in src, "the rule must be in the seam's docstring"


def test_s1_seam_is_not_duplicated():
    """One seam — no second copy of the helper anywhere in app/."""
    for p in (REPO / "app").rglob("*.py"):
        if p.name == "scope.py" or "__pycache__" in str(p):
            continue
        src = _read(p)
        assert "def tenant_scoped(" not in src, f"a second tenant_scoped copy lives in {p.name}"


# ── S2 — the hot routers route their reads through the seam ───────────────


def test_s2_hot_files_import_the_seam():
    for rel in HOT_FILES:
        src = _read(REPO / rel)
        assert "from app.services.scope import tenant_scoped" in src, (
            f"{rel} must import the ONE scoping seam"
        )


def test_s2_hot_files_route_their_reads_through_the_seam():
    """The pinned migration shape: the exact number of seam call sites per
    hot file — a query silently un-migrated drops the count with it."""
    for rel, expected in SEAM_SITES.items():
        src = _read(REPO / rel)
        found = len(re.findall(r"tenant_scoped\(db,", src))
        assert found == expected, f"{rel}: expected {expected} tenant_scoped call sites, found {found}"


# ── S3 — remaining inline fragments are only the documented exclusions ────


def test_s3_hot_files_keep_only_the_documented_inline_exclusions():
    """A NEW inline `tenant_id ==` fragment in a hot file fails here — the
    quiet leak vector. Migrate it through the seam or document the exclusion."""
    for rel in HOT_FILES:
        src = _read(REPO / rel)
        lines = [l for l in src.splitlines() if re.search(r"tenant_id\s*==", l)]
        allowed = ALLOWED_INLINE.get(rel, [])
        assert len(lines) == len(allowed), (
            f"{rel}: expected {len(allowed)} inline fragment(s), found {len(lines)} — "
            + " | ".join(l.strip()[:100] for l in lines)
        )
        for line in lines:
            assert any(a in line for a in allowed), (
                f"{rel}: undocumented inline fragment: {line.strip()[:120]}"
            )


def test_s3_exclusions_are_not_tenant_owned_entity_reads():
    """Each exclusion's shape holds: the fragment sits on a JOIN/membership
    check or a column query, not a tenant-owned entity lookup."""
    backlog = _read(REPO / "app/routers/backlog.py")
    assert "db.query(BacklogItem.item_type)" in backlog, (
        "backlog's exclusion is the item_type COLUMN query, not an entity read"
    )
    stats = _read(REPO / "app/services/stats.py")
    assert "db.query(Client.id)" in stats, "stats' exclusion is the Client.id COLUMN query"
    copilot = _read(REPO / "app/services/copilot.py")
    assert "db.query(Project.id)" in copilot, "copilot's exclusion is the Project.id COLUMN query"
    assert "db.query(TenantMembership)" in copilot, "copilot's membership check stays hand-written"
