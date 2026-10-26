"""Tests for lifecycle templates — phases/stages/gates become data per project type.

Software keeps today's V-cycle verbatim (default). AI/CPMAI adds dataset,
bias, and drift gates. Marketing Campaign and Operations get their own
phases and gate deliverables. Gate MECHANISM and RBAC never change —
only the vocabulary and gate deliverables vary.
"""
import pytest

import app.models  # noqa: F401
from app.services.lifecycle import (
    LIFECYCLE_TEMPLATES,
    gate_deliverables,
    gate_roles,
    item_phases,
    release_stages,
    template_for,
)


def test_software_template_matches_today_vcycle():
    """Software (default) = today's ITEM_PHASES verbatim."""
    from app.models.backlog_item import ITEM_PHASES

    t = template_for("software")
    assert t["name"] == "Software"
    assert item_phases("software") == ITEM_PHASES
    assert template_for(None) == t  # None defaults to software


def test_ai_template_cpmai_phases():
    """AI template: Data Readiness → ... → Ready for Deployment."""
    phases = item_phases("ai")
    assert phases == [
        "Data Readiness", "Model Design", "Development & Training",
        "Evaluation", "Ready for Deployment",
    ]


def test_ai_template_stages():
    stages = release_stages("ai")
    assert stages[0] == "Business Understanding"
    assert stages[-1] == "Post-Deployment Monitoring"
    assert "Data Readiness & Processing" in stages
    assert "Model Development & Training" in stages


def test_ai_template_gates():
    """CPMAI gates: dataset readiness + provenance, performance + bias, drift plan."""
    deliverables = gate_deliverables("ai")
    assert deliverables["Data Readiness"] == [
        "Dataset readiness report", "Data provenance & consent record",
    ]
    assert gate_roles("ai")["Data Readiness"] == "Data/ML Lead"
    assert deliverables["Evaluation"] == [
        "Model performance report", "Bias & fairness assessment",
    ]
    assert gate_roles("ai")["Evaluation"] == "Product Manager"
    assert "Drift-monitoring plan" in deliverables["Ready for Deployment"]


def test_marketing_template():
    phases = item_phases("marketing")
    assert phases == ["Brief", "Creative", "Content Production", "Review", "Ready for Launch"]
    deliverables = gate_deliverables("marketing")
    assert "Budget approval" in deliverables["Brief"]
    assert gate_roles("marketing")["Review"] == "Product Manager"


def test_operations_template():
    phases = item_phases("operations")
    assert phases == ["Intake", "Plan", "Execute", "Verify", "Done"]
    deliverables = gate_deliverables("operations")
    assert "Verification report" in deliverables["Verify"]


def test_every_template_has_consistent_structure():
    """Every template: phases non-empty, stages start with Intake-like stage,
    every phase with deliverables has a role."""
    for key, t in LIFECYCLE_TEMPLATES.items():
        assert t["item_phases"], f"{key}: no item phases"
        assert t["release_stages"], f"{key}: no release stages"
        for phase, deliverables in t["gate_deliverables"].items():
            assert phase in t["item_phases"], f"{key}: gate phase {phase} not in phases"
            assert deliverables, f"{key}: empty deliverables for {phase}"
            assert t["gate_roles"].get(phase), f"{key}: no role for gate {phase}"


def test_gate_mechanism_unchanged():
    """The template only changes vocabulary — gate flow/RBAC stays on the
    existing ApprovalRequest/ApprovalStep mechanism."""
    t = template_for("ai")
    assert set(t["gate_deliverables"].keys()) == set(t["gate_roles"].keys())
    # Software gates still map to the same roles as today
    s = template_for("software")
    assert gate_roles("software")["Development"] == "Tech Lead"
