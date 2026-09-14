"""Seed form templates based on the Obelion Release Process V2.0.

Templates:
1. Deployment Checklist — pre-deployment verification
2. UAT Sign-off — user acceptance testing approval
3. Hotfix Request — emergency hotfix authorization
4. RCA (Root Cause Analysis) — post-incident analysis
5. Retrospective — post-release lessons learned
"""
from sqlalchemy.orm import Session

from app.models.form_template import FormTemplate


def seed_form_templates(db: Session):
    """Create the 5 standard form templates if they don't exist."""

    templates = [
        FormTemplate(
            name="Deployment Checklist",
            form_type="deployment_checklist",
            description="Pre-deployment verification checklist for releases",
            field_schema=[
                {"name": "release_version", "label": "Release Version", "type": "text", "required": True},
                {"name": "deployment_date", "label": "Deployment Date", "type": "date", "required": True},
                {"name": "environment", "label": "Target Environment", "type": "select", "options": ["Staging", "Production"], "required": True},
                {"name": "deployed_by", "label": "Deployed By", "type": "text", "required": True},
                {"name": "backup_completed", "label": "Database backup completed", "type": "boolean", "required": True},
                {"name": "stakeholders_notified", "label": "Stakeholders notified", "type": "boolean", "required": True},
                {"name": "smoke_tests_passed", "label": "Smoke tests passed", "type": "boolean", "required": True},
                {"name": "rollback_plan_ready", "label": "Rollback plan ready", "type": "boolean", "required": True},
                {"name": "notes", "label": "Additional Notes", "type": "textarea", "required": False},
            ],
        ),
        FormTemplate(
            name="UAT Sign-off",
            form_type="uat_signoff",
            description="User acceptance testing sign-off form",
            field_schema=[
                {"name": "release_version", "label": "Release Version", "type": "text", "required": True},
                {"name": "tester_name", "label": "Tester Name", "type": "text", "required": True},
                {"name": "test_date", "label": "Test Date", "type": "date", "required": True},
                {"name": "test_cases_total", "label": "Total Test Cases", "type": "number", "required": True},
                {"name": "test_cases_passed", "label": "Test Cases Passed", "type": "number", "required": True},
                {"name": "test_cases_failed", "label": "Test Cases Failed", "type": "number", "required": True},
                {"name": "all_critical_passed", "label": "All critical tests passed?", "type": "boolean", "required": True},
                {"name": "signoff_decision", "label": "Sign-off Decision", "type": "select", "options": ["Approved", "Approved with Conditions", "Rejected"], "required": True},
                {"name": "comments", "label": "Comments", "type": "textarea", "required": False},
            ],
        ),
        FormTemplate(
            name="Hotfix Request",
            form_type="hotfix_request",
            description="Emergency hotfix authorization request",
            field_schema=[
                {"name": "issue_title", "label": "Issue Title", "type": "text", "required": True},
                {"name": "severity", "label": "Severity", "type": "select", "options": ["P1 - Critical", "P2 - High", "P3 - Medium"], "required": True},
                {"name": "affected_system", "label": "Affected System", "type": "text", "required": True},
                {"name": "impact_description", "label": "Impact Description", "type": "textarea", "required": True},
                {"name": "proposed_fix", "label": "Proposed Fix", "type": "textarea", "required": True},
                {"name": "requested_by", "label": "Requested By", "type": "text", "required": True},
                {"name": "approved_by", "label": "Approved By", "type": "text", "required": False},
                {"name": "target_deployment", "label": "Target Deployment Time", "type": "datetime", "required": False},
            ],
        ),
        FormTemplate(
            name="Root Cause Analysis",
            form_type="rca",
            description="Post-incident root cause analysis",
            field_schema=[
                {"name": "incident_title", "label": "Incident Title", "type": "text", "required": True},
                {"name": "incident_date", "label": "Incident Date", "type": "date", "required": True},
                {"name": "detected_by", "label": "Detected By", "type": "text", "required": True},
                {"name": "duration", "label": "Duration (minutes)", "type": "number", "required": True},
                {"name": "impact", "label": "Business Impact", "type": "textarea", "required": True},
                {"name": "root_cause", "label": "Root Cause", "type": "textarea", "required": True},
                {"name": "contributing_factors", "label": "Contributing Factors", "type": "textarea", "required": False},
                {"name": "preventive_actions", "label": "Preventive Actions", "type": "textarea", "required": True},
                {"name": "action_owners", "label": "Action Owners", "type": "text", "required": True},
                {"name": "follow_up_date", "label": "Follow-up Date", "type": "date", "required": False},
            ],
        ),
        FormTemplate(
            name="Retrospective",
            form_type="retrospective",
            description="Post-release retrospective lessons learned",
            field_schema=[
                {"name": "release_version", "label": "Release Version", "type": "text", "required": True},
                {"name": "sprint dates", "label": "Sprint/Release Dates", "type": "text", "required": False},
                {"name": "what_went_well", "label": "What went well?", "type": "textarea", "required": True},
                {"name": "what_didnt_go_well", "label": "What didn't go well?", "type": "textarea", "required": True},
                {"name": "lessons_learned", "label": "Lessons learned", "type": "textarea", "required": True},
                {"name": "action_items", "label": "Action items for next release", "type": "textarea", "required": False},
                {"name": "participants", "label": "Participants", "type": "text", "required": False},
            ],
        ),
    ]

    for template in templates:
        existing = db.query(FormTemplate).filter(FormTemplate.form_type == template.form_type).first()
        if not existing:
            db.add(template)

    db.commit()
