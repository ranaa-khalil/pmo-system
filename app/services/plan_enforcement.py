"""Plan enforcement — feature gates based on tenant plan.

Checks whether a tenant's plan allows a specific feature.
Raises 403 with an upgrade message if the feature is not available.

Plans and features:
  Free:      basic backlog, V-Cycle, RBAC, max 1 project, 3 users
  Team:      + GitHub sync, AI assistant, approvals, KPIs, max 10 projects
  Business:  + SSO (OIDC), audit logs export, data export, unlimited projects
  Enterprise: + SAML SSO, white-label, dedicated instance
"""
from fastapi import HTTPException

from app.models.tenant import PLAN_FREE, PLAN_BUSINESS, PLAN_ENTERPRISE, PLAN_TEAM


# Feature → minimum plan required
FEATURE_GATES = {
    "github_sync": PLAN_TEAM,
    "ai_assistant": PLAN_TEAM,
    "approvals": PLAN_TEAM,
    "kpis": PLAN_TEAM,
    "releases": PLAN_TEAM,
    "data_export": PLAN_BUSINESS,
    "audit_log_export": PLAN_BUSINESS,
    "sso_oidc": PLAN_BUSINESS,
    "sso_saml": PLAN_ENTERPRISE,
    "white_label": PLAN_ENTERPRISE,
}

# Plan hierarchy for comparison
_PLAN_ORDER = {PLAN_FREE: 0, PLAN_TEAM: 1, PLAN_BUSINESS: 2, PLAN_ENTERPRISE: 3}


def _plan_level(plan: str) -> int:
    return _PLAN_ORDER.get(plan, 0)


def has_feature(plan: str, feature: str) -> bool:
    """Check if a plan includes a specific feature."""
    required = FEATURE_GATES.get(feature)
    if required is None:
        return True  # No gate for this feature
    return _plan_level(plan) >= _plan_level(required)


def require_feature(plan: str, feature: str):
    """Raise 403 if the plan doesn't include the feature."""
    if not has_feature(plan, feature):
        required = FEATURE_GATES.get(feature, PLAN_FREE)
        raise HTTPException(
            status_code=403,
            detail=f"Feature '{feature}' requires the {required} plan or higher. "
                   f"Your current plan is {plan}. Contact your administrator to upgrade.",
        )
