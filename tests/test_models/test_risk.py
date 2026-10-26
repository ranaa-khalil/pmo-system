"""Tests for the Risk register model — real risk rows replace risk drafts.

Risks are per-project, carry severity/probability/score, status (Open →
Mitigating → Closed), an owner, and a source (manual | copilot | evidence).
Tenant isolation via tenant_id; traceability at birth (source records every
risk's origin).
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture()
def risk_world(db):
    tenant = Tenant(name="Risk Co", slug="risk-co")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-risk@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "pm": pm, "project": project}


def test_risk_row_with_score(db, risk_world):
    """A risk row carries severity × probability as its score."""
    risk = Risk(
        tenant_id=risk_world["tenant"].id, project_id=risk_world["project"].id,
        title="SSO integration slips", description="Vendor API not ready",
        severity="High", probability="Medium", status="Open",
        owner_id=risk_world["pm"].id, source="manual",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    assert risk.score == 9  # High(3) × Medium(3)


def test_risk_score_defaults_safe(db, risk_world):
    """Unknown severity/probability strings score 0, never raise."""
    risk = Risk(
        tenant_id=risk_world["tenant"].id, project_id=risk_world["project"].id,
        title="Weird", severity="Catastrophic", probability="Sometimes",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    assert risk.score == 0


def test_risk_copilot_source(db, risk_world):
    """Copilot-drafted risks carry source='copilot' for traceability."""
    risk = Risk(
        tenant_id=risk_world["tenant"].id, project_id=risk_world["project"].id,
        title="Release date at risk", severity="Medium", probability="High",
        source="copilot",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    assert risk.source == "copilot"


def test_risk_tenant_isolation(db, risk_world):
    """A second tenant cannot see the first tenant's risks."""
    other = Tenant(name="Other Co", slug="other-co")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(Risk(tenant_id=risk_world["tenant"].id, project_id=risk_world["project"].id, title="Hidden"))
    db.commit()
    visible = db.query(Risk).filter(Risk.tenant_id == other.id).all()
    assert visible == []
