"""The ONE tenant-scoping seam (ADR-01) — every tenant-scoped read starts here.

Rule: every tenant-scoped READ of a tenant-owned table goes through
``tenant_scoped`` instead of a hand-written
``Model.tenant_id == current_tenant.id`` fragment. One seam means one place to
tighten (row-level security, ``with_loader_criteria``, audit) and one place a
new route cannot forget — the quiet leak vector was the ~392 inline filter
fragments scattered across the routers.

Scope: entity reads on models that carry a ``tenant_id`` column (Project,
BacklogItem, Client, Release, Tag, UserTask, …). NOT in seam scope, and still
hand-written:
  - join-table filters (e.g. ``TenantMembership.tenant_id`` inside a User join)
  - membership/access-control checks (``TenantMembership`` lookups)
  - association-table selects (``backlog_item_tags`` and friends)
  - column/aggregate queries that build tuple rows (``db.query(Model.id)``)
"""

from sqlalchemy.orm import Query, Session


def tenant_scoped(db: Session, model: type, tenant_id: int) -> Query:
    """Return a query on ``model`` pre-filtered to ``tenant_id``.

    Equivalent to ``db.query(model).filter(model.tenant_id == tenant_id)``:
    chain ``.filter(...)`` / ``.order_by(...)`` / ``.first()`` / ``.all()`` /
    ``.count()`` on it exactly as on a plain query. Same filter, same 404/[]
    behavior — the seam is a refactor, not a behavior change.
    """
    return db.query(model).filter(model.tenant_id == tenant_id)
