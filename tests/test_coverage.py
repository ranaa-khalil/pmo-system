"""Slice 9 — R3 both-direction KPI coverage: KPI → its work, item → its KPI.

Covers: the coverage math (2 of 4 KPIs with items → 50, all covered → 100,
no KPIs → null — never an invented 100), the forward direction (each KPI's
items are the RIGHT items — the unlinked KPI shows up in kpis_without_work
and never in the per-KPI lists), the reverse direction (unlinked_items
counts the project's kpi_id NULL items; the sample is the 10 newest by
created desc), tenant scoping (a foreign tenant's KPIs/items are invisible
— their linkage never counts), the empty project, the response shape, and
the endpoint itself (payload + 404 on a foreign-tenant project).
"""
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — register all models with Base
from app.main import app
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.kpi import KPI
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.coverage import compute_coverage

# --------------------------------------------------------------------------- helpers


def _project(db, tenant, user, name="Coverage P") -> Project:
    """Projects require a client (NOT NULL FK) — seed one for the test."""
    c = Client(tenant_id=tenant.id, name=f"Client {name}")
    db.add(c)
    db.commit()
    db.refresh(c)
    p = Project(
        tenant_id=tenant.id, name=name, status="active",
        client_id=c.id, project_manager_id=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _kpi(db, tenant, project, name, **extra) -> KPI:
    k = KPI(tenant_id=tenant.id, project_id=project.id, name=name, **extra)
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


def _item(db, tenant, project, title, kpi=None, **extra) -> BacklogItem:
    it = BacklogItem(tenant_id=tenant.id, project_id=project.id, title=title, kpi_id=kpi.id if kpi else None, **extra)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _second_tenant(db) -> Tenant:
    t = Tenant(name="Other Tenant", slug="other-tenant", plan="enterprise", status="active")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _foreign_user(db, tenant, email="other@pmo.test"):
    """A user whose active tenant is the OTHER tenant (own Bearer token)."""
    u = User(
        email=email, name=f"User {email}",
        hashed_password=hash_password("TestPass123!"),
        system_role="super_admin", active_tenant_id=tenant.id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    tc = TestClient(app)
    tc.headers.update({"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"})
    return tc, u


# --------------------------------------------------------------------------- 1. the math


def test_coverage_pct_two_of_four_kpis_have_work(client, db, auth_user):
    """2 of 4 KPIs have at least one linked item → coverage 50."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k1, k2, k3, k4 = (_kpi(db, t, p, f"KPI {i}") for i in range(1, 5))
    _item(db, t, p, "Work A", kpi=k1)
    _item(db, t, p, "Work B", kpi=k3)

    cov = compute_coverage(db, t.id, p.id)
    assert cov["kpi_total"] == 4
    assert cov["kpis_with_work"] == 2
    assert cov["kpis_without_work"] == 2
    assert cov["coverage_pct"] == 50


def test_coverage_pct_all_kpis_have_work_is_100(client, db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k1, k2 = _kpi(db, t, p, "KPI one"), _kpi(db, t, p, "KPI two")
    _item(db, t, p, "Work A", kpi=k1)
    _item(db, t, p, "Work B", kpi=k2)

    cov = compute_coverage(db, t.id, p.id)
    assert cov["coverage_pct"] == 100
    assert cov["kpis_without_work"] == 0


def test_coverage_pct_null_when_project_has_no_kpis(client, db, auth_user):
    """Items but no KPIs → coverage null — never an invented 100."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    _item(db, t, p, "Uncovered work")

    cov = compute_coverage(db, t.id, p.id)
    assert cov["kpi_total"] == 0
    assert cov["coverage_pct"] is None


# --------------------------------------------------------------------------- 2. the forward direction (KPI → its work)


def test_per_kpi_items_are_the_right_items(client, db, auth_user):
    """Each KPI's items are exactly the items linked to it — the unlinked
    KPI appears in kpis_without_work and never in the per-KPI lists."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    ka, kb, kc = (_kpi(db, t, p, name, unit="%", category="Quality") for name in ("Alpha", "Beta", "Gamma"))
    a1 = _item(db, t, p, "Alpha work 1", kpi=ka, status="In Progress", current_phase="Development")
    a2 = _item(db, t, p, "Alpha work 2", kpi=ka, status="Done", current_phase="Testing")
    b1 = _item(db, t, p, "Beta work 1", kpi=kb)
    _item(db, t, p, "Orphan work")  # linked to NO KPI

    cov = compute_coverage(db, t.id, p.id)
    by_id = {block["id"]: block for block in cov["kpis"]}

    # Alpha carries exactly its two items, in the payload shape (newest first)
    alpha = {it["title"]: it for it in by_id[ka.id]["items"]}
    assert set(alpha) == {"Alpha work 1", "Alpha work 2"}
    assert by_id[ka.id]["item_count"] == 2
    assert alpha["Alpha work 1"]["id"] == a1.id
    assert alpha["Alpha work 1"]["current_phase"] == "Development"
    assert alpha["Alpha work 1"]["status"] == "In Progress"
    assert alpha["Alpha work 2"]["id"] == a2.id
    assert alpha["Alpha work 2"]["status"] == "Done"

    # Beta carries exactly its one item
    assert [it["title"] for it in by_id[kb.id]["items"]] == ["Beta work 1"]
    assert by_id[kb.id]["item_count"] == 1

    # Gamma has no work beneath it: zero items, counted in kpis_without_work
    assert by_id[kc.id]["item_count"] == 0
    assert by_id[kc.id]["items"] == []
    assert cov["kpis_without_work"] == 1
    assert all(block["item_count"] == 0 for block in cov["kpis"] if block["id"] == kc.id)

    # The orphan item belongs to no KPI block
    orphan = db.query(BacklogItem).filter(BacklogItem.title == "Orphan work").first()
    for block in cov["kpis"]:
        assert orphan.id not in [it["id"] for it in block["items"]]


# --------------------------------------------------------------------------- 3. the reverse direction (item → its KPI: orphans)


def test_unlinked_items_counts_kpi_null_items(client, db, auth_user):
    """unlinked_items counts exactly the project items with kpi_id NULL —
    linked items never appear in the orphan sample."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k = _kpi(db, t, p, "KPI linked")
    _item(db, t, p, "Linked work", kpi=k)
    o1, o2, o3 = (_item(db, t, p, f"Orphan {i}") for i in range(1, 4))

    cov = compute_coverage(db, t.id, p.id)
    assert cov["unlinked_items"] == 3
    sample_ids = [it["id"] for it in cov["unlinked_sample"]]
    assert set(sample_ids) == {o1.id, o2.id, o3.id}
    # The linked item never appears in the orphan pool
    assert "Linked work" not in [it["title"] for it in cov["unlinked_sample"]]


def test_unlinked_sample_is_ten_newest_by_created_desc(client, db, auth_user):
    """12 orphans → count 12, sample capped at the 10 newest (id desc tiebreak)."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    orphans = [_item(db, t, p, f"Orphan {i}") for i in range(1, 13)]

    cov = compute_coverage(db, t.id, p.id)
    assert cov["unlinked_items"] == 12
    assert len(cov["unlinked_sample"]) == 10
    sample_ids = [it["id"] for it in cov["unlinked_sample"]]
    expected = sorted((o.id for o in orphans), reverse=True)[:10]
    assert sample_ids == expected
    # Sample entries carry the orphan-chip shape
    for entry in cov["unlinked_sample"]:
        assert set(entry.keys()) == {"id", "title", "current_phase"}


# --------------------------------------------------------------------------- 4. tenant scoping


def test_foreign_tenant_kpis_and_orphans_invisible(client, db, auth_user):
    """Another tenant's KPI on this project id and its orphan items never
    leak into the coverage numbers."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k = _kpi(db, t, p, "Mine")
    _item(db, t, p, "My real work", kpi=k)
    _item(db, t, p, "My orphan")

    tb = _second_tenant(db)
    # A foreign tenant's KPI pointing at THIS project id (unvalidated FK)
    rogue_kpi = KPI(tenant_id=tb.id, project_id=p.id, name="Foreign KPI")
    db.add(rogue_kpi)
    # Foreign tenant's orphan item inside this project
    db.add(BacklogItem(tenant_id=tb.id, project_id=p.id, title="Foreign orphan"))
    db.commit()

    cov = compute_coverage(db, t.id, p.id)
    assert cov["kpi_total"] == 1
    assert [block["name"] for block in cov["kpis"]] == ["Mine"]
    assert cov["coverage_pct"] == 100  # the one real KPI has its work
    assert cov["kpis_without_work"] == 0
    assert cov["unlinked_items"] == 1  # only MY orphan, never the foreign one
    assert [it["title"] for it in cov["unlinked_sample"]] == ["My orphan"]


def test_foreign_tenant_linkage_never_counts(client, db, auth_user):
    """A foreign tenant's item linked to MY KPI never counts as its work."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k = _kpi(db, t, p, "My KPI")
    _item(db, t, p, "My real work", kpi=k)

    tb = _second_tenant(db)
    # Foreign tenant's item linked to MY KPI (rogue cross-tenant linkage)
    db.add(BacklogItem(tenant_id=tb.id, project_id=p.id, title="Foreign work", kpi_id=k.id))
    db.commit()

    cov = compute_coverage(db, t.id, p.id)
    by_id = {block["id"]: block for block in cov["kpis"]}
    assert by_id[k.id]["item_count"] == 1
    assert [it["title"] for it in by_id[k.id]["items"]] == ["My real work"]
    assert cov["kpis_without_work"] == 0


# --------------------------------------------------------------------------- 5. empty project


def test_empty_project_coverage_is_null_and_unlinked_zero(client, db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)

    cov = compute_coverage(db, t.id, p.id)
    assert cov["coverage_pct"] is None
    assert cov["kpi_total"] == 0
    assert cov["kpis_with_work"] == 0
    assert cov["kpis_without_work"] == 0
    assert cov["kpis"] == []
    assert cov["unlinked_items"] == 0
    assert cov["unlinked_sample"] == []


# --------------------------------------------------------------------------- 6. response shape


def test_response_shape_all_keys_present(client, db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k = _kpi(db, t, p, "KPI one", target_value="95", current_value="80", unit="%", category="Reliability")
    _item(db, t, p, "Work", kpi=k)
    _item(db, t, p, "Orphan")

    cov = compute_coverage(db, t.id, p.id)
    assert set(cov.keys()) == {
        "project_id", "kpi_total", "kpis_with_work", "coverage_pct",
        "kpis_without_work", "kpis", "unlinked_items", "unlinked_sample",
    }
    assert cov["project_id"] == p.id
    for block in cov["kpis"]:
        assert set(block.keys()) == {
            "id", "name", "category", "target_value", "current_value",
            "unit", "item_count", "items",
        }
        assert block["name"] == "KPI one"
        assert block["category"] == "Reliability"
        assert block["target_value"] == "95"
        assert block["current_value"] == "80"
        assert block["unit"] == "%"
        assert block["item_count"] == len(block["items"])
        for it in block["items"]:
            assert set(it.keys()) == {"id", "title", "current_phase", "status"}


# --------------------------------------------------------------------------- 7. the endpoint


def test_endpoint_returns_coverage_payload(client, db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    k1, k2 = _kpi(db, t, p, "KPI one"), _kpi(db, t, p, "KPI two")
    _item(db, t, p, "Work one", kpi=k1)
    _item(db, t, p, "Orphan")

    r = client.get(f"/api/projects/{p.id}/coverage")
    assert r.status_code == 200
    body = r.json()
    assert body == compute_coverage(db, t.id, p.id)
    assert body["coverage_pct"] == 50
    assert body["unlinked_items"] == 1
    assert body["kpis_without_work"] == 1


def test_endpoint_404_on_foreign_tenant_project(client, db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    tb = _second_tenant(db)
    foreign_tc, _ = _foreign_user(db, tb)

    r = foreign_tc.get(f"/api/projects/{p.id}/coverage")
    assert r.status_code == 404
    assert r.json()["detail"] == "Project not found"


# --------------------------------------------------------------------------- 8. the write path (regression)


def test_backlog_rejects_foreign_tenant_kpi_link(client, db, auth_user):
    """Regression: backlog create AND update must reject a FOREIGN tenant's
    kpi_id — the cross-tenant write path that the coverage reads guard but
    the writes didn't (a data row would hold a rogue link no read shows)."""
    t, u = auth_user["tenant"], auth_user["user"]
    p = _project(db, t, u)
    foreign_kpi = KPI(tenant_id=_second_tenant(db).id, project_id=p.id, name="Foreign KPI")
    db.add(foreign_kpi)
    db.commit()

    # Create: a body carrying the other tenant's kpi_id must be rejected…
    r = client.post(f"/api/projects/{p.id}/backlog",
                    json={"project_id": p.id, "title": "Rogue link", "kpi_id": foreign_kpi.id})
    assert r.status_code == 400
    # …and no row with the rogue link may exist.
    assert db.query(BacklogItem).filter(BacklogItem.kpi_id == foreign_kpi.id).first() is None

    # Update: pointing an existing item at the foreign KPI must be rejected too
    mine = client.post(f"/api/projects/{p.id}/backlog",
                       json={"project_id": p.id, "title": "Update target"}).json()
    r2 = client.put(f"/api/backlog/{mine['id']}", json={"kpi_id": foreign_kpi.id})
    assert r2.status_code == 400
    assert db.query(BacklogItem).filter(BacklogItem.id == mine["id"]).first().kpi_id != foreign_kpi.id

    # Unlink (kpi_id null) stays allowed, and a THIS-tenant kpi_id still works
    own_kpi = _kpi(db, t, p, "My KPI")
    r3 = client.put(f"/api/backlog/{mine['id']}", json={"kpi_id": own_kpi.id})
    assert r3.status_code == 200 and r3.json()["kpi_id"] == own_kpi.id
    r4 = client.put(f"/api/backlog/{mine['id']}", json={"kpi_id": None})
    assert r4.status_code == 200 and r4.json()["kpi_id"] is None
