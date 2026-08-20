"""Seed script — creates default admin user, RACI roles, and sample data with traceability links.

Run with: python -m app.seed
"""
from datetime import date
from app.database import SessionLocal, engine, Base
import app.models  # noqa: F401 — register all models
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.project_vision import ProjectVision
from app.models.kpi import KPI
from app.models.roadmap import Roadmap
from app.models.milestone import Milestone
from app.models.backlog_item import BacklogItem
from app.models.release import Release, ReleaseItem
from app.services.auth import hash_password


# The 12 RACI roles from RACI Matrix v2.3
RACI_ROLES = [
    ("Product Owner", "Owns the product vision, priorities, and backlog. Accountable for what gets built and why."),
    ("Project Manager", "Plans, schedules, and tracks delivery. Facilitates communication and removes blockers."),
    ("Tech Lead", "Owns technical architecture and code quality. Makes technical design decisions."),
    ("Dev Lead", "Coordinates the development team. Breaks down work and reviews code."),
    ("Developer", "Implements features, fixes bugs, writes unit tests. Produces the code."),
    ("QA Lead", "Owns test strategy and quality gates. Reviews test plans and coverage."),
    ("QA Engineer", "Writes and executes test cases. Reports defects. Performs regression testing."),
    ("DevOps Lead", "Owns CI/CD pipelines, infrastructure, and deployment strategy."),
    ("DevOps Engineer", "Maintains build pipelines, monitors systems, executes deployments."),
    ("Security Officer", "Reviews security requirements, performs security testing, signs off on compliance."),
    ("Release Manager", "Coordinates release activities, manages deployment windows, owns the release calendar."),
    ("Stakeholder", "Business sponsor or interested party. Provides requirements and accepts deliverables."),
]


def seed():
    """Create default data if the database is empty."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # --- Admin user ---
    admin = db.query(User).filter(User.email == "rana@opex.com.sa").first()
    if not admin:
        admin = User(
            email="rana@opex.com.sa",
            name="Rana Khalil",
            hashed_password=hash_password("Pmo@2026"),
            system_role="super_admin",
        )
        db.add(admin)
        print("✅ Created super admin: rana@opex.com.sa")
    else:
        admin.hashed_password = hash_password("Pmo@2026")
        admin.system_role = "super_admin"
        print("ℹ️ Admin user already exists — password reset, role set to super_admin")

    # --- RACI Roles ---
    for name, desc in RACI_ROLES:
        existing = db.query(Role).filter(Role.name == name).first()
        if not existing:
            db.add(Role(name=name, description=desc))
    db.commit()
    role_count = db.query(Role).count()
    print(f"✅ RACI roles: {role_count} in database")

    # --- Sample clients ---
    nitc = db.query(Client).filter(Client.name == "NITC / PNU").first()
    if not nitc:
        nitc = Client(name="NITC / PNU", contact_name="Aldaana Almuqrin",
                       contact_email="pmo@nitc.gov.sa",
                       description="Princess Nourah University — Cloud Services",
                       account_manager_id=admin.id)
        db.add(nitc)
        print("✅ Created client: NITC / PNU (AM: Rana)")
    else:
        nitc.account_manager_id = admin.id

    go = db.query(Client).filter(Client.name == "GO Telecom").first()
    if not go:
        go = Client(name="GO Telecom", contact_email="partners@gotelecom.com.sa",
                     description="Telecom partner for connectivity")
        db.add(go)
        print("✅ Created client: GO Telecom")

    db.commit()

    # --- Sample project ---
    pnu = db.query(Project).filter(Project.name == "PNU Cloud").first()
    if not pnu:
        pnu = Project(
            name="PNU Cloud",
            client_id=nitc.id,
            description="Cloud infrastructure and managed services for PNU",
            status="Active",
            github_repo="opexsa/pnu-cloud",
            project_manager_id=admin.id,
        )
        db.add(pnu)
        db.commit()
        print("✅ Created project: PNU Cloud")

    # --- Assign admin as PM on PNU Cloud ---
    pm_role = db.query(Role).filter(Role.name == "Project Manager").first()
    existing_assign = db.query(RoleAssignment).filter(
        RoleAssignment.user_id == admin.id,
        RoleAssignment.role_id == pm_role.id,
        RoleAssignment.project_id == pnu.id,
    ).first()
    if not existing_assign:
        db.add(RoleAssignment(user_id=admin.id, role_id=pm_role.id, project_id=pnu.id))
        db.commit()
        print("✅ Assigned Rana as Project Manager on PNU Cloud")

    # --- Vision (connected to KPIs) ---
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == pnu.id).first()
    if not vision:
        vision = ProjectVision(
            project_id=pnu.id,
            statement="Become the leading cloud platform for PNU, delivering 99.9% uptime with enterprise-grade security and automated self-service capabilities.",
            strategic_objectives="1. Achieve 99.9% service uptime\n2. Reduce incident response time to under 15 minutes\n3. Enable self-service provisioning for 80% of requests\n4. Pass security compliance audit (NCA/ECC)\n5. Scale to 10,000+ active users",
        )
        db.add(vision)
        db.commit()
        print("✅ Created project vision with 5 strategic objectives")

    # --- KPIs (linked to vision objectives) ---
    kpi_uptime = db.query(KPI).filter(KPI.name == "Service Uptime", KPI.project_id == pnu.id).first()
    if not kpi_uptime:
        kpi_uptime = KPI(project_id=pnu.id, name="Service Uptime",
                         target_value="99.9", current_value="99.5", unit="%", category="Reliability",
                         vision_objective="Achieve 99.9% service uptime")
        db.add(kpi_uptime)

        kpi_response = KPI(project_id=pnu.id, name="Incident Response Time",
                           target_value="15", current_value="45", unit="minutes", category="Operations",
                           vision_objective="Reduce incident response time to under 15 minutes")
        db.add(kpi_response)

        kpi_self = KPI(project_id=pnu.id, name="Self-Service Adoption",
                       target_value="80", current_value="20", unit="%", category="User Experience",
                       vision_objective="Enable self-service provisioning for 80% of requests")
        db.add(kpi_self)

        db.commit()
        print("✅ Created 3 KPIs linked to vision objectives")

    # --- Roadmap with milestones ---
    roadmap = db.query(Roadmap).filter(Roadmap.project_id == pnu.id).first()
    if not roadmap:
        roadmap = Roadmap(project_id=pnu.id, title="2026-2027 Platform Roadmap",
                          start_date=date(2026, 1, 1), end_date=date(2027, 6, 30))
        db.add(roadmap)
        db.commit()

        ms_q3 = Milestone(roadmap_id=roadmap.id, title="Q3 2026: Core Platform",
                          target_date=date(2026, 9, 30), status="On Track",
                          description="Authentication, infrastructure, and monitoring foundation")
        db.add(ms_q3)
        ms_q4 = Milestone(roadmap_id=roadmap.id, title="Q4 2026: Advanced Features",
                          target_date=date(2026, 12, 31), status="On Track",
                          description="Analytics dashboard, self-service portal, reporting")
        db.add(ms_q4)
        ms_q1 = Milestone(roadmap_id=roadmap.id, title="Q1 2027: Scale & Optimize",
                          target_date=date(2027, 3, 31), status="At Risk",
                          description="Performance optimization, multi-region, compliance audit")
        db.add(ms_q1)
        db.commit()
        print("✅ Created roadmap with 3 milestones (Q3 2026, Q4 2026, Q1 2027)")

    # --- Backlog items (linked to KPIs) ---
    existing_backlog = db.query(BacklogItem).filter(BacklogItem.project_id == pnu.id).count()
    if existing_backlog == 0:
        kpi_uptime_id = db.query(KPI).filter(KPI.name == "Service Uptime", KPI.project_id == pnu.id).first().id
        kpi_response_id = db.query(KPI).filter(KPI.name == "Incident Response Time", KPI.project_id == pnu.id).first().id
        kpi_self_id = db.query(KPI).filter(KPI.name == "Self-Service Adoption", KPI.project_id == pnu.id).first().id

        # Map Excel statuses to model phase + status
        def map_status(excel_status):
            """Map Excel status to (current_phase, status)."""
            mapping = {
                "Done": ("Retrospective", "Done"),
                "In UAT": ("UAT", "In Progress"),
                "Ready for Release": ("Pre-Release", "In Progress"),
                "In QA": ("Testing", "In Progress"),
                "In Progress": ("Development", "In Progress"),
                "Planned": ("Requirements", "Draft"),
                "Backlog": ("Requirements", "Draft"),
                "Backlog (unscheduled)": ("Requirements", "Draft"),
                "Blocked": ("Development", "Blocked"),
            }
            return mapping.get(excel_status, ("Requirements", "Draft"))

        def map_priority(excel_priority):
            """Map Excel priority (Must/Should/Could) to model priority."""
            return {"Must": "Critical", "Should": "High", "Could": "Medium"}.get(excel_priority, "Medium")

        # 12 backlog items from Master Backlog (09_Master_Backlog_Automated.xlsx)
        master_items = [
            {"epic": "Catalog & PIM", "title": "Bilingual (AR/EN) service catalog search",
             "item_type": "Feature", "actor": "End Customer", "priority": "Must", "pts": 5,
             "status": "Done", "release": "2026-07",
             "criteria": "Users can search the catalog in Arabic and English; results respect locale.",
             "deps": "—", "kpi": kpi_self_id},
            {"epic": "RBAC & Identity", "title": "Multi-tenant role management with granular permissions",
             "item_type": "Feature", "actor": "Platform Admin", "priority": "Must", "pts": 8,
             "status": "In UAT", "release": "2026-08",
             "criteria": "Admins define roles/permissions per tenant; changes audited.",
             "deps": "Audit & Compliance", "kpi": kpi_uptime_id},
            {"epic": "Platform / Core", "title": "Enforce MFA for admin logins",
             "item_type": "Feature", "actor": "Platform Admin", "priority": "Must", "pts": 5,
             "status": "In UAT", "release": "2026-08",
             "criteria": "All admin logins require MFA; enrolment flow provided.",
             "deps": "RBAC & Identity", "kpi": kpi_uptime_id},
            {"epic": "Audit & Compliance", "title": "Immutable audit trail for admin actions",
             "item_type": "Feature", "actor": "Auditor", "priority": "Must", "pts": 5,
             "status": "Ready for Release", "release": "2026-08",
             "criteria": "Every admin action is logged immutably with actor, time, before/after.",
             "deps": "—", "kpi": kpi_uptime_id},
            {"epic": "Notifications", "title": "Verify push notification delivery on web client",
             "item_type": "Bug", "actor": "End Customer", "priority": "Should", "pts": 3,
             "status": "In QA", "release": "2026-08",
             "criteria": "Push notifications must deliver reliably on the web client.",
             "deps": "—", "kpi": kpi_response_id},
            {"epic": "Billing & Invoicing", "title": "Generate customer invoices with applied margin",
             "item_type": "Feature", "actor": "Finance Admin", "priority": "Must", "pts": 13,
             "status": "In Progress", "release": "2026-09",
             "criteria": "System generates customer invoices applying the configured margin.",
             "deps": "Payments", "kpi": kpi_self_id},
            {"epic": "Payments", "title": "Integrate payment gateway (card + local methods)",
             "item_type": "Feature", "actor": "End Customer", "priority": "Must", "pts": 13,
             "status": "Planned", "release": "2026-09",
             "criteria": "Checkout supports card and local payment methods via gateway.",
             "deps": "Billing & Invoicing", "kpi": kpi_self_id},
            {"epic": "Commerce / Cart & Checkout", "title": "Cart-to-checkout transaction flow",
             "item_type": "Feature", "actor": "End Customer", "priority": "Must", "pts": 8,
             "status": "In Progress", "release": "2026-09",
             "criteria": "End customer can add to cart and complete a checkout transaction.",
             "deps": "Payments", "kpi": kpi_self_id},
            {"epic": "Marketplace / Storefront", "title": "Vendor product listing & storefront",
             "item_type": "Feature", "actor": "Vendor", "priority": "Should", "pts": 8,
             "status": "Backlog", "release": "2026-10",
             "criteria": "Vendors publish listings to a branded storefront.",
             "deps": "Vendor Self-Service Portal", "kpi": kpi_self_id},
            {"epic": "Reseller / Channel", "title": "N-tier reseller hierarchy & pricing",
             "item_type": "Feature", "actor": "Reseller Admin", "priority": "Should", "pts": 13,
             "status": "Backlog", "release": "2026-11",
             "criteria": "Support multi-level reseller hierarchy with per-tier pricing.",
             "deps": "Billing & Invoicing", "kpi": kpi_self_id},
            {"epic": "Cloud Resource Intelligence", "title": "Multi-cloud usage aggregation dashboard",
             "item_type": "Enhancement", "actor": "Platform Admin", "priority": "Should", "pts": 5,
             "status": "Done", "release": "2026-07",
             "criteria": "Aggregate usage across providers into a single dashboard.",
             "deps": "—", "kpi": kpi_response_id},
            {"epic": "Provisioning & Orchestration", "title": "Enable write actions on provisioning connector (currently read-only)",
             "item_type": "Feature", "actor": "Platform Admin", "priority": "Could", "pts": 13,
             "status": "Blocked", "release": "Backlog (unscheduled)",
             "criteria": "Move connector from read-only to supported write/provisioning actions.",
             "deps": "Connector API (external)", "kpi": kpi_uptime_id},
        ]

        items = []
        for mi in master_items:
            phase, status = map_status(mi["status"])
            items.append(BacklogItem(
                project_id=pnu.id,
                title=mi["title"],
                description=mi["criteria"],
                epic=mi["epic"],
                item_type=mi["item_type"],
                primary_actor=mi["actor"],
                story_points=mi["pts"],
                target_release=mi["release"],
                acceptance_criteria=mi["criteria"],
                dependencies=mi["deps"],
                priority=map_priority(mi["priority"]),
                current_phase=phase,
                status=status,
                kpi_id=mi["kpi"],
            ))

        for item in items:
            db.add(item)
        db.commit()
        print(f"✅ Created {len(items)} backlog items from Master Backlog (09_Master_Backlog_Automated.xlsx)")

    # --- Release (linked to milestone) ---
    existing_release = db.query(Release).filter(Release.project_id == pnu.id).first()
    if not existing_release:
        ms_q3 = db.query(Milestone).filter(Milestone.title == "Q3 2026: Core Platform").first()
        backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == pnu.id).all()

        rel = Release(
            project_id=pnu.id, version="1.0.0", name="Core Platform Launch",
            description="Initial production release: authentication, infrastructure, monitoring",
            status="In Progress", target_date="2026-09-30",
            milestone_id=ms_q3.id if ms_q3 else None,
        )
        db.add(rel)
        db.commit()

        # Link first 3 backlog items to the release
        for item in backlog_items[:3]:
            db.add(ReleaseItem(release_id=rel.id, backlog_item_id=item.id))
        db.commit()
        print(f"✅ Created release v1.0.0 linked to Q3 milestone with 3 backlog items")

        # --- Auto-routed approval chain for the release ---
        # The release is in "In Progress" phase. Backfill:
        # 1. Approved approval for Planning → In Progress (Product Owner gate)
        # 2. Pending approval for In Progress → Testing (Tech Lead gate)
        from app.models.approval import ApprovalRequest, ApprovalStep
        from sqlalchemy.sql import func

        # 1. Approved: Planning → In Progress (Product Owner)
        ap1 = ApprovalRequest(
            project_id=pnu.id,
            title=f"Release {rel.version}: Planning → In Progress",
            description="Approve requirements are complete and ready for development",
            request_type="release",
            requested_by=admin.id,
            release_id=rel.id,
            target_phase="In Progress",
            status="Approved",
        )
        db.add(ap1)
        db.commit()
        db.refresh(ap1)
        st1 = ApprovalStep(
            request_id=ap1.id,
            step_order=1,
            role_name="Product Owner",
            status="Approved",
            approver_id=admin.id,
            comment="Requirements reviewed and approved",
            decided_at=func.now(),
        )
        db.add(st1)

        # 2. Pending: In Progress → Testing (Tech Lead)
        ap2 = ApprovalRequest(
            project_id=pnu.id,
            title=f"Release {rel.version}: In Progress → Testing",
            description="Approve code completion and readiness for testing",
            request_type="release",
            requested_by=admin.id,
            release_id=rel.id,
            target_phase="Testing",
            status="Pending",
        )
        db.add(ap2)
        db.commit()
        db.refresh(ap2)
        st2 = ApprovalStep(
            request_id=ap2.id,
            step_order=1,
            role_name="Tech Lead",
            status="Pending",
        )
        db.add(st2)
        db.commit()
        print(f"✅ Created auto-routed approval chain: Planning→In Progress (approved), In Progress→Testing (pending Tech Lead)")

    db.close()
    print("\n🔐 Login credentials:")
    print("   Email:    rana@opex.com.sa")
    print("   Password: Pmo@2026")
    print("\n📊 Traceability chain:")
    print("   Vision → 3 KPIs → 3 Milestones → 1 Release → 12 Backlog Items")


if __name__ == "__main__":
    seed()
