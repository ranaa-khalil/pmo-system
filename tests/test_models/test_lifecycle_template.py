"""Tests for methodology depth (P4.4): tenant-defined lifecycle templates.

TenantLifecycleTemplate model: tenants define custom lifecycles for edge
project types (per the plan) with item_phases, release_stages, gate
deliverables/roles, and custom fields. template_for() prefers the tenant's
custom template for its project_type key and falls back to the built-ins.
"""

from app.models.lifecycle_template import TenantLifecycleTemplate
from app.services import lifecycle


def test_tenant_template_overrides_builtin(db_session, auth_user):
    tenant_id = auth_user["tenant"].id
    db_session.add(TenantLifecycleTemplate(
        tenant_id=tenant_id, project_type="research",
        name="Research Study",
        item_phases=["Proposal", "Collection", "Analysis", "Writeup"],
        release_stages=["Proposal", "Fieldwork", "Analysis", "Publication"],
        gate_deliverables={"Proposal": ["Study plan"], "Analysis": ["Findings report"]},
        gate_roles={"Proposal": "Product Manager", "Analysis": "Product Manager"},
        fields=[{"name": "sample_size", "label": "Sample size", "type": "text"}],
        created_by=auth_user["user"].id,
    ))
    db_session.commit()

    template = lifecycle.template_for("research", tenant_id=tenant_id, db=db_session)
    assert template["name"] == "Research Study"
    assert template["item_phases"][0] == "Proposal"
    assert template["fields"][0]["name"] == "sample_size"


def test_unknown_type_still_defaults_to_software(db_session, auth_user):
    tenant_id = auth_user["tenant"].id
    template = lifecycle.template_for("nonexistent", tenant_id=tenant_id)
    assert template["name"] == "Software"


def test_other_tenant_template_not_visible(db_session, auth_user):
    from app.models.tenant import Tenant

    other = Tenant(name="Other T", slug="other-t", plan="enterprise", status="active")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    db_session.add(TenantLifecycleTemplate(
        tenant_id=other.id, project_type="secret_type",
        name="Other Tenant Template",
        item_phases=["X"], release_stages=["X"],
        gate_deliverables={}, gate_roles={}, fields=[],
    ))
    db_session.commit()

    # From auth_user's tenant, "secret_type" is unknown → software default
    template = lifecycle.template_for("secret_type", tenant_id=auth_user["tenant"].id, db=db_session)
    assert template["name"] == "Software"
    # From the owning tenant, it resolves
    assert lifecycle.template_for("secret_type", tenant_id=other.id, db=db_session)["name"] == "Other Tenant Template"


def test_builtin_templates_unchanged(db_session, auth_user):
    """Built-ins stay verbatim when the tenant defines nothing."""
    tenant_id = auth_user["tenant"].id
    template = lifecycle.template_for("software", tenant_id=tenant_id, db=db_session)
    assert template["item_phases"][0] == "Requirements"
    assert template["gate_roles"]["Development"] == "Tech Lead"
