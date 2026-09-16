"""Seed script — creates minimal demo data for the PMO System.

Creates: 1 OPEX tenant, super admin, tenant admin, 2 clients, 2 projects,
3 KPIs, 1 roadmap with 3 milestones, 6 backlog items, 1 release with approvals.

Run with: python -m app.seed
"""
from datetime import date

import app.models  # noqa: F401 — register all models
from app.database import Base, SessionLocal, engine
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.release import Release, ReleaseItem
from app.models.roadmap import Roadmap
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.user import User
from app.services.auth import hash_password

# The 12 RACI roles from RACI Matrix v2.3
RACI_ROLES = [
    ("Product Owner", "Owns the product vision, priorities, and backlog. Accountable for requirements, entry type, and UAT sign-off."),
    ("Product Manager", "Plans delivery, documents requirements, prepares release notes. Accountable for UAT gate and PIV."),
    ("Business Lead", "Runs UAT execution with business users. Responsible for validating business value."),
    ("UX Designer", "Conceptualizes UX, creates mockups/prototypes. Accountable for UX sign-off gate."),
    ("Tech Lead", "Owns technical architecture, code quality, version numbering. Accountable for In Progress gate."),
    ("Engineering Team", "Implements features, writes unit tests, peer code review. Responsible for development phase."),
    ("QA Lead", "Owns test strategy and quality gates. Accountable for SIT sign-off gate."),
    ("QA Engineer", "Writes and executes test cases (SIT, regression). Reports defects."),
    ("DevOps Lead", "Owns CI/CD, infrastructure, deployment. Accountable for deployment and rollback."),
    ("DevOps Engineer", "Maintains build pipelines, monitors systems, executes deployments."),
    ("CX Engineer", "Monitors support tickets post-release. Accountable for post-implementation support."),
    ("PMO", "Validates business value and approves post-implementation verification."),
]

DEFAULT_PASSWORD = "Pmo@2026"


def seed():
    """Create minimal demo data if the database is empty."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── Tenant ──────────────────────────────────────────────────────────
    from app.models.tenant import Tenant, TenantMembership

    tenant = db.query(Tenant).first()
    if not tenant:
        tenant = Tenant(name="OPEX", slug="opex", plan="enterprise", status="active")
        db.add(tenant)
        db.flush()
        print(f"✅ Created tenant: {tenant.name}")
    else:
        print(f"ℹ️ Tenant already exists: {tenant.name}")

    # ── Super admin ─────────────────────────────────────────────────────
    sys_admin = db.query(User).filter(User.email == "admin@pmosystem.app").first()
    if not sys_admin:
        sys_admin = User(
            email="admin@pmosystem.app",
            name="System Administrator",
            hashed_password=hash_password(DEFAULT_PASSWORD),
            system_role="super_admin",
            is_active=True,
            active_tenant_id=None,
        )
        db.add(sys_admin)
        print("✅ Created super admin: admin@pmosystem.app")
    else:
        sys_admin.hashed_password = hash_password(DEFAULT_PASSWORD)
        sys_admin.system_role = "super_admin"
        print("ℹ️ Super admin already exists — password reset")

    # ── Tenant admin (Rana) ─────────────────────────────────────────────
    rana = db.query(User).filter(User.email == "rana@opex.com.sa").first()
    if not rana:
        rana = User(
            email="rana@opex.com.sa",
            name="Rana Khalil",
            hashed_password=hash_password(DEFAULT_PASSWORD),
            system_role="tenant_admin",
            is_active=True,
        )
        db.add(rana)
        db.flush()
        print("✅ Created tenant admin: rana@opex.com.sa")
    else:
        rana.hashed_password = hash_password(DEFAULT_PASSWORD)
        rana.system_role = "tenant_admin"
        print("ℹ️ Tenant admin already exists — password reset")

    # Ensure Rana is owner of the OPEX tenant
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == rana.id,
        TenantMembership.tenant_id == tenant.id,
    ).first()
    if not membership:
        db.add(TenantMembership(user_id=rana.id, tenant_id=tenant.id, role="owner"))
    rana.active_tenant_id = tenant.id
    db.commit()

    # ── RACI Roles ──────────────────────────────────────────────────────
    for name, desc in RACI_ROLES:
        existing = db.query(Role).filter(Role.name == name).first()
        if not existing:
            db.add(Role(name=name, description=desc))
    db.commit()
    print(f"✅ RACI roles: {db.query(Role).count()} in database")

    # ── Clients ─────────────────────────────────────────────────────────
    nitc = db.query(Client).filter(Client.name == "NITC / PNU").first()
    if not nitc:
        nitc = Client(
            name="NITC / PNU",
            contact_name="Aldaana Almuqrin",
            contact_email="pmo@nitc.gov.sa",
            description="Princess Nourah University — Cloud Services",
            account_manager_id=rana.id,
            tenant_id=tenant.id,
        )
        db.add(nitc)
        print("✅ Created client: NITC / PNU")

    go = db.query(Client).filter(Client.name == "GO Telecom").first()
    if not go:
        go = Client(
            name="GO Telecom",
            contact_email="partners@gotelecom.com.sa",
            description="Telecom partner for connectivity",
            account_manager_id=rana.id,
            tenant_id=tenant.id,
        )
        db.add(go)
    db.commit()
    print("✅ Created client: GO Telecom")

    # ── Project 1: PNU Cloud ────────────────────────────────────────────
    pnu = db.query(Project).filter(Project.name == "PNU Cloud").first()
    if not pnu:
        pnu = Project(
            name="PNU Cloud",
            client_id=nitc.id,
            description="Cloud infrastructure and managed services for PNU",
            status="Active",
            github_repo="obelion/pnu-cloud",
            version_prefix="1.0",
            project_manager_id=rana.id,
            dev_url="https://dev.pnu-cloud.opex.com.sa",
            uat_url="https://uat.pnu-cloud.opex.com.sa",
            prod_url="https://pnu-cloud.opex.com.sa",
            tenant_id=tenant.id,
        )
        db.add(pnu)
        db.commit()
        print("✅ Created project: PNU Cloud")

    # Assign Rana as PM + gate-keeper roles on PNU Cloud
    for role_name in ["Product Manager", "Product Owner", "Tech Lead", "QA Lead", "DevOps Lead"]:
        role = db.query(Role).filter(Role.name == role_name).first()
        if role:
            exists = db.query(RoleAssignment).filter(
                RoleAssignment.user_id == rana.id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.project_id == pnu.id,
            ).first()
            if not exists:
                db.add(RoleAssignment(user_id=rana.id, role_id=role.id, project_id=pnu.id))
    db.commit()
    print("✅ Assigned Rana as PM + gate-keeper roles on PNU Cloud")

    # Vision for PNU Cloud
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == pnu.id).first()
    if not vision:
        vision = ProjectVision(
            project_id=pnu.id,
            statement="Become the leading cloud platform for PNU, delivering 99.9% uptime with enterprise-grade security and automated self-service capabilities.",
            strategic_objectives="1. Achieve 99.9% service uptime\n2. Reduce incident response time to under 15 minutes\n3. Enable self-service provisioning for 80% of requests",
        )
        db.add(vision)
        db.commit()

    # KPIs for PNU Cloud
    kpi_uptime = db.query(KPI).filter(KPI.name == "Service Uptime", KPI.project_id == pnu.id).first()
    if not kpi_uptime:
        kpi_uptime = KPI(project_id=pnu.id, name="Service Uptime",
                         target_value="99.9", current_value="99.5", unit="%", category="Reliability",
                         vision_objective="Achieve 99.9% service uptime")
        db.add(kpi_uptime)
        db.add(KPI(project_id=pnu.id, name="Incident Response Time",
                   target_value="15", current_value="45", unit="minutes", category="Operations",
                   vision_objective="Reduce incident response time to under 15 minutes"))
        db.add(KPI(project_id=pnu.id, name="Self-Service Adoption",
                   target_value="80", current_value="20", unit="%", category="User Experience",
                   vision_objective="Enable self-service provisioning for 80% of requests"))
        db.commit()
        print("✅ Created 3 KPIs for PNU Cloud")

    # Roadmap + milestones for PNU Cloud
    roadmap = db.query(Roadmap).filter(Roadmap.project_id == pnu.id).first()
    if not roadmap:
        roadmap = Roadmap(project_id=pnu.id, title="2026-2027 Platform Roadmap",
                          start_date=date(2026, 1, 1), end_date=date(2027, 6, 30))
        db.add(roadmap)
        db.commit()
        db.add(Milestone(roadmap_id=roadmap.id, title="Q3 2026: Core Platform",
                         target_date=date(2026, 9, 30), status="On Track",
                         description="Authentication, infrastructure, and monitoring foundation"))
        db.add(Milestone(roadmap_id=roadmap.id, title="Q4 2026: Advanced Features",
                         target_date=date(2026, 12, 31), status="On Track",
                         description="Analytics dashboard, self-service portal, reporting"))
        db.add(Milestone(roadmap_id=roadmap.id, title="Q1 2027: Scale & Optimize",
                         target_date=date(2027, 3, 31), status="On Track",
                         description="Performance optimization, multi-region, compliance audit"))
        db.commit()
        print("✅ Created roadmap with 3 milestones for PNU Cloud")

    # Backlog items for PNU Cloud (6 items)
    existing_backlog = db.query(BacklogItem).filter(BacklogItem.project_id == pnu.id).count()
    if existing_backlog == 0:
        kpi_uptime_id = db.query(KPI).filter(KPI.name == "Service Uptime", KPI.project_id == pnu.id).first().id
        kpi_response_id = db.query(KPI).filter(KPI.name == "Incident Response Time", KPI.project_id == pnu.id).first().id
        kpi_self_id = db.query(KPI).filter(KPI.name == "Self-Service Adoption", KPI.project_id == pnu.id).first().id

        backlog_items = [
            BacklogItem(project_id=pnu.id, title="Bilingual service catalog search",
                        description="Users can search the catalog in Arabic and English",
                        epic="Catalog & PIM", item_type="Feature", primary_actor="End Customer",
                        story_points=5, priority="Critical", current_phase="Retrospective",
                        status="Done", target_release="2026-07", kpi_id=kpi_self_id,
                        acceptance_criteria="Search works in both AR and EN", dependencies="—"),
            BacklogItem(project_id=pnu.id, title="Multi-tenant role management",
                        description="Admins define roles/permissions per tenant; changes audited",
                        epic="RBAC & Identity", item_type="Feature", primary_actor="Platform Admin",
                        story_points=8, priority="Critical", current_phase="UAT",
                        status="In Progress", target_release="2026-08", kpi_id=kpi_uptime_id,
                        acceptance_criteria="Roles defined per tenant, changes audited", dependencies="—"),
            BacklogItem(project_id=pnu.id, title="Enforce MFA for admin logins",
                        description="All admin logins require MFA; enrolment flow provided",
                        epic="Platform / Core", item_type="Feature", primary_actor="Platform Admin",
                        story_points=5, priority="Critical", current_phase="UAT",
                        status="In Progress", target_release="2026-08", kpi_id=kpi_uptime_id,
                        acceptance_criteria="MFA enforced for admin accounts", dependencies="RBAC & Identity"),
            BacklogItem(project_id=pnu.id, title="Immutable audit trail for admin actions",
                        description="Every admin action is logged immutably with actor, time, before/after",
                        epic="Audit & Compliance", item_type="Feature", primary_actor="Auditor",
                        story_points=5, priority="High", current_phase="Pre-Release",
                        status="In Progress", target_release="2026-08", kpi_id=kpi_uptime_id,
                        acceptance_criteria="Admin actions logged immutably", dependencies="—"),
            BacklogItem(project_id=pnu.id, title="Cart-to-checkout transaction flow",
                        description="End customer can add to cart and complete a checkout transaction",
                        epic="Commerce", item_type="Feature", primary_actor="End Customer",
                        story_points=8, priority="High", current_phase="Development",
                        status="In Progress", target_release="2026-09", kpi_id=kpi_self_id,
                        acceptance_criteria="Checkout flow works end-to-end", dependencies="Payments"),
            BacklogItem(project_id=pnu.id, title="Multi-cloud usage aggregation dashboard",
                        description="Aggregate usage across providers into a single dashboard",
                        epic="Cloud Intelligence", item_type="Enhancement", primary_actor="Platform Admin",
                        story_points=5, priority="Medium", current_phase="Requirements",
                        status="Draft", target_release="2026-10", kpi_id=kpi_response_id,
                        acceptance_criteria="Dashboard shows usage from all providers", dependencies="—"),
        ]
        for item in backlog_items:
            db.add(item)
        db.commit()
        print(f"✅ Created {len(backlog_items)} backlog items for PNU Cloud")

    # Release + approval chain for PNU Cloud
    existing_release = db.query(Release).filter(Release.project_id == pnu.id).first()
    if not existing_release:
        ms_q3 = db.query(Milestone).filter(Milestone.title == "Q3 2026: Core Platform").first()
        backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == pnu.id).all()

        rel = Release(
            project_id=pnu.id, version="1.0.0", name="Core Platform Launch",
            description="Initial production release: authentication, infrastructure, monitoring",
            status="In Progress", target_date="2026-09-30",
            milestone_id=ms_q3.id if ms_q3 else None,
            tenant_id=tenant.id,
        )
        db.add(rel)
        db.commit()

        for item in backlog_items[:3]:
            db.add(ReleaseItem(release_id=rel.id, backlog_item_id=item.id))
        db.commit()

        # Approval chain: Planning→In Progress (approved), In Progress→Testing (pending)
        from app.models.approval import ApprovalRequest, ApprovalStep
        from sqlalchemy.sql import func

        ap1 = ApprovalRequest(
            project_id=pnu.id,
            title=f"Release {rel.version}: Planning → In Progress",
            description="Approve requirements are complete and ready for development",
            request_type="release", requested_by=rana.id, release_id=rel.id,
            target_phase="In Progress", status="Approved", tenant_id=tenant.id,
        )
        db.add(ap1)
        db.commit()
        db.refresh(ap1)
        db.add(ApprovalStep(
            request_id=ap1.id, step_order=1, role_name="Product Owner",
            status="Approved", approver_id=rana.id,
            comment="Requirements reviewed and approved", decided_at=func.now(),
        ))

        ap2 = ApprovalRequest(
            project_id=pnu.id,
            title=f"Release {rel.version}: In Progress → Testing",
            description="Approve code completion and readiness for testing",
            request_type="release", requested_by=rana.id, release_id=rel.id,
            target_phase="Testing", status="Pending", tenant_id=tenant.id,
        )
        db.add(ap2)
        db.commit()
        db.refresh(ap2)
        db.add(ApprovalStep(
            request_id=ap2.id, step_order=1, role_name="Tech Lead",
            status="Pending", approver_id=rana.id,
        ))
        db.commit()
        print("✅ Created release v1.0.0 with approval chain for PNU Cloud")

    # ── Project 2: CloudGate Platform ───────────────────────────────────
    cg = db.query(Project).filter(Project.name == "CloudGate Platform").first()
    if not cg:
        cg = Project(
            name="CloudGate Platform",
            client_id=nitc.id,
            description="Multi-tenant SaaS platform for managing cloud infrastructure",
            status="Active",
            github_repo="opex-sa/CloudGate",
            version_prefix="2.0",
            project_manager_id=rana.id,
            dev_url="https://dev.cloudgate.opex.com.sa",
            uat_url="https://uat.cloudgate.opex.com.sa",
            prod_url="https://cloudgate.opex.com.sa",
            tenant_id=tenant.id,
        )
        db.add(cg)
        db.commit()
        print("✅ Created project: CloudGate Platform")

    # Assign Rana as PM on CloudGate
    pm_role = db.query(Role).filter(Role.name == "Product Manager").first()
    if pm_role:
        exists = db.query(RoleAssignment).filter(
            RoleAssignment.user_id == rana.id,
            RoleAssignment.role_id == pm_role.id,
            RoleAssignment.project_id == cg.id,
        ).first()
        if not exists:
            db.add(RoleAssignment(user_id=rana.id, role_id=pm_role.id, project_id=cg.id))
    db.commit()

    # Vision for CloudGate
    vision_cg = db.query(ProjectVision).filter(ProjectVision.project_id == cg.id).first()
    if not vision_cg:
        db.add(ProjectVision(
            project_id=cg.id,
            statement="Unified cloud management platform serving enterprise customers across Saudi Arabia.",
            strategic_objectives="1. Onboard 5 enterprise tenants\n2. Achieve SOC2 compliance\n3. Automate 90% of provisioning workflows",
        ))
        db.commit()

    # KPIs for CloudGate
    if db.query(KPI).filter(KPI.project_id == cg.id).count() == 0:
        db.add(KPI(project_id=cg.id, name="Tenant Onboarding Time",
                   target_value="48", current_value="120", unit="hours", category="Operations",
                   vision_objective="Onboard 5 enterprise tenants"))
        db.add(KPI(project_id=cg.id, name="Automation Coverage",
                   target_value="90", current_value="35", unit="%", category="Efficiency",
                   vision_objective="Automate 90% of provisioning workflows"))
        db.commit()
        print("✅ Created 2 KPIs for CloudGate Platform")

    # Roadmap for CloudGate
    roadmap_cg = db.query(Roadmap).filter(Roadmap.project_id == cg.id).first()
    if not roadmap_cg:
        roadmap_cg = Roadmap(project_id=cg.id, title="2026-2027 CloudGate Roadmap",
                             start_date=date(2026, 1, 1), end_date=date(2027, 6, 30))
        db.add(roadmap_cg)
        db.commit()
        db.add(Milestone(roadmap_id=roadmap_cg.id, title="Q4 2026: Multi-tenant SaaS",
                         target_date=date(2026, 12, 31), status="On Track",
                         description="SaaS layer, tenant management, configurable plans"))
        db.add(Milestone(roadmap_id=roadmap_cg.id, title="Q2 2027: SOC2 Compliance",
                         target_date=date(2027, 6, 30), status="On Track",
                         description="Security audit, compliance documentation, pen test"))
        db.commit()
        print("✅ Created roadmap with 2 milestones for CloudGate Platform")

    # ── Summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PMO System — Seed Complete")
    print("=" * 60)
    print(f"  Tenant:      {tenant.name} (slug: {tenant.slug})")
    print(f"  Super admin: admin@pmosystem.app")
    print(f"  Tenant admin: rana@opex.com.sa")
    print(f"  Password:    {DEFAULT_PASSWORD} (change after first login!)")
    print(f"  Clients:     {db.query(Client).count()}")
    print(f"  Projects:    {db.query(Project).count()}")
    print(f"  Backlog:     {db.query(BacklogItem).count()} items")
    print(f"  KPIs:        {db.query(KPI).count()}")
    print(f"  Releases:    {db.query(Release).count()}")
    print(f"  Milestones:  {db.query(Milestone).count()}")
    print(f"  RACI roles:  {db.query(Role).count()}")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    seed()
