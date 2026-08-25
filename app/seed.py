"""Seed script — creates default admin user, RACI roles, and sample data with traceability links.

Run with: python -m app.seed
"""
from datetime import date, timedelta
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
from app.models.user_task import UserTask
from app.models.release import Release, ReleaseItem
from app.models.form_template import FormTemplate, FormInstance
from app.models.stakeholder import Stakeholder
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

    # ====================================================================
    # COMPREHENSIVE SAMPLE DATA — clients, projects, KPIs, roadmaps,
    # releases, backlog, forms, stakeholders across multiple projects
    # ====================================================================

    # --- Additional clients ---
    tasama = db.query(Client).filter(Client.name == "TASAMA").first()
    if not tasama:
        tasama = Client(name="TASAMA", contact_name="Mohammed Al-Otaibi",
                        contact_email="partners@tasama.sa",
                        description="Saudi tech alliance — multi-cloud services",
                        account_manager_id=admin.id)
        db.add(tasama)
        print("✅ Created client: TASAMA")

    yotta = db.query(Client).filter(Client.name == "Yotta").first()
    if not yotta:
        yotta = Client(name="Yotta", contact_name="Sara Al-Dossari",
                       contact_email="ops@yottacloud.io",
                       description="Cloud infrastructure provider",
                       account_manager_id=admin.id)
        db.add(yotta)
        print("✅ Created client: Yotta")
    db.commit()

    # --- Additional team members ---
    team_members = [
        ("ahmed@opex.com.sa", "Ahmed Eldosoukey", "member"),
        ("khalid@opex.com.sa", "Khalid Al-Harbi", "member"),
        ("fatima@opex.com.sa", "Fatima Al-Zahra", "member"),
        ("omar@opex.com.sa", "Omar Al-Shehri", "member"),
        ("nora@opex.com.sa", "Nora Al-Qahtani", "member"),
    ]
    created_users = {}
    for email, name, role in team_members:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(email=email, name=name, hashed_password=hash_password("Pmo@2026"),
                     system_role=role)
            db.add(u)
            db.commit()
            db.refresh(u)
            print(f"✅ Created team member: {name}")
        created_users[email] = u

    # --- Helper: create a full project with vision, KPIs, roadmap, milestones ---
    def create_project_with_data(
        name, client, description, status, pm_user,
        vision_stmt, objectives,
        kpis_data,  # [(name, target, current, unit, category, objective)]
        roadmap_title, rm_start, rm_end,
        milestones_data,  # [(title, date, status, desc)]
        releases_data,  # [(version, name, desc, status, target_date, milestone_idx)]
        backlog_data,  # [(title, desc, phase, status, priority, epic, type, actor, pts, target_rel, kpi_idx)]
        stakeholders_data,  # [(name, email, company, role_name, raci_type)]
    ):
        existing = db.query(Project).filter(Project.name == name).first()
        if existing:
            return existing

        proj = Project(
            name=name, client_id=client.id, description=description,
            status=status, project_manager_id=pm_user.id,
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)
        print(f"✅ Created project: {name}")

        # Vision
        v = ProjectVision(project_id=proj.id, statement=vision_stmt, strategic_objectives=objectives)
        db.add(v)
        db.commit()

        # KPIs
        kpi_ids = []
        for kname, ktgt, kcur, kunit, kcat, kobj in kpis_data:
            k = KPI(project_id=proj.id, name=kname, target_value=ktgt, current_value=kcur,
                    unit=kunit, category=kcat, vision_objective=kobj)
            db.add(k)
            db.commit()
            db.refresh(k)
            kpi_ids.append(k.id)

        # Roadmap + milestones
        rm = Roadmap(project_id=proj.id, title=roadmap_title, start_date=rm_start, end_date=rm_end)
        db.add(rm)
        db.commit()
        db.refresh(rm)

        ms_ids = []
        for mstitle, msdate, msstatus, msdesc in milestones_data:
            ms = Milestone(roadmap_id=rm.id, title=mstitle, target_date=msdate,
                           status=msstatus, description=msdesc)
            db.add(ms)
            db.commit()
            db.refresh(ms)
            ms_ids.append(ms.id)

        # Releases
        rel_ids = []
        for ver, rname, rdesc, rstatus, rdate, msidx in releases_data:
            ms_id = ms_ids[msidx] if msidx < len(ms_ids) else None
            r = Release(project_id=proj.id, version=ver, name=rname, description=rdesc,
                        status=rstatus, target_date=rdate, milestone_id=ms_id, created_by=admin.id)
            db.add(r)
            db.commit()
            db.refresh(r)
            rel_ids.append(r.id)

        # Backlog items
        bi_ids = []
        for btitle, bdesc, bphase, bstatus, bpriority, bepic, btype, bactor, bpts, btgtrel, bkpiidx in backlog_data:
            bkpi = kpi_ids[bkpiidx] if bkpiidx < len(kpi_ids) else None
            bi = BacklogItem(
                project_id=proj.id, title=btitle, description=bdesc,
                current_phase=bphase, status=bstatus, priority=bpriority,
                epic=bepic, item_type=btype, primary_actor=bactor,
                story_points=bpts, target_release=btgtrel,
                acceptance_criteria=bdesc, dependencies="—",
                kpi_id=bkpi,
            )
            db.add(bi)
            db.commit()
            db.refresh(bi)
            bi_ids.append(bi.id)

        # Link some backlog items to the first release
        if rel_ids and bi_ids:
            for bi_id in bi_ids[:3]:
                db.add(ReleaseItem(release_id=rel_ids[0], backlog_item_id=bi_id))
            db.commit()

        # Stakeholders
        for sname, semail, scompany, srole, sraci in stakeholders_data:
            s = Stakeholder(project_id=proj.id, name=sname, email=semail,
                            company=scompany, role_name=srole, raci_type=sraci)
            db.add(s)
        db.commit()

        # Assign PM role
        pm_r = db.query(Role).filter(Role.name == "Project Manager").first()
        existing_ra = db.query(RoleAssignment).filter(
            RoleAssignment.user_id == pm_user.id,
            RoleAssignment.project_id == proj.id,
        ).first()
        if not existing_ra and pm_r:
            db.add(RoleAssignment(user_id=pm_user.id, role_id=pm_r.id, project_id=proj.id))
            db.commit()

        return proj

    # --- Project 2: CloudGate Platform (NITC/PNU) ---
    create_project_with_data(
        name="CloudGate Platform",
        client=nitc,
        description="Unified cloud management portal with billing, catalog, and marketplace",
        status="Active",
        pm_user=admin,
        vision_stmt="Build the leading multi-cloud management platform for Saudi enterprises, enabling self-service provisioning, transparent billing, and marketplace integration.",
        objectives="1. Launch marketplace with 50+ vendor listings\n2. Achieve 95% billing accuracy\n3. Enable self-service provisioning for 90% of services\n4. Support 5,000+ active users\n5. Achieve sub-2s page load time",
        kpis_data=[
            ("Billing Accuracy", "95", "82", "%", "Financial", "Achieve 95% billing accuracy"),
            ("Page Load Time", "2", "3.5", "seconds", "Performance", "Achieve sub-2s page load time"),
            ("Active Users", "5000", "1800", "users", "Growth", "Support 5,000+ active users"),
        ],
        roadmap_title="2026-2027 CloudGate Roadmap",
        rm_start=date(2026, 3, 1), rm_end=date(2027, 6, 30),
        milestones_data=[
            ("Q3 2026: Marketplace MVP", date(2026, 9, 30), "On Track", "Vendor storefront, product listings, search"),
            ("Q4 2026: Billing Engine", date(2026, 12, 31), "On Track", "Invoice generation, payment gateway, margin calculation"),
            ("Q1 2027: Scale & Optimize", date(2027, 3, 31), "At Risk", "Performance optimization, 5K users, multi-region"),
        ],
        releases_data=[
            ("0.9.0", "Marketplace Beta", "Vendor storefront and product listing MVP", "Released", "2026-07-15", 0),
            ("1.0.0", "Billing & Payments", "Full billing engine with payment gateway integration", "UAT", "2026-09-30", 1),
            ("1.1.0", "Performance Pack", "Caching, CDN, query optimization", "Planning", "2026-12-15", 2),
        ],
        backlog_data=[
            ("Vendor registration flow", "Self-service vendor onboarding with verification", "Release", "Done", "High", "Marketplace", "Feature", "Vendor", 8, "2026-07", 0),
            ("Product catalog API", "RESTful API for catalog CRUD operations", "Post-Release", "Done", "Critical", "Catalog & PIM", "Feature", "Platform Admin", 13, "2026-07", 0),
            ("Invoice PDF generation", "Generate branded PDF invoices with line items", "UAT", "In Progress", "Critical", "Billing & Invoicing", "Feature", "Finance Admin", 8, "2026-09", 0),
            ("Payment retry logic", "Automatic retry for failed payments with 3 attempts", "Development", "In Progress", "High", "Payments", "Feature", "End Customer", 5, "2026-09", 0),
            ("Vendor analytics dashboard", "Sales metrics, conversion rates, top products", "Design", "In Progress", "Medium", "Analytics", "Feature", "Vendor", 8, "2026-10", 1),
            ("Multi-currency support", "Support SAR, USD, EUR with live FX rates", "Requirements", "Draft", "Medium", "Billing & Invoicing", "Feature", "Finance Admin", 13, "2026-11", 0),
            ("Cart abandonment recovery", "Email reminders for abandoned carts", "Requirements", "Draft", "Low", "Commerce", "Enhancement", "End Customer", 5, "2026-12", 2),
            ("API rate limiting", "Per-vendor rate limits with usage quotas", "Testing", "In Progress", "High", "Platform / Core", "Feature", "Platform Admin", 5, "2026-08", 0),
            ("Search relevance tuning", "Improve catalog search with fuzzy matching", "Retrospective", "Done", "Medium", "Catalog & PIM", "Enhancement", "End Customer", 3, "2026-07", 1),
            ("Vendor payout scheduling", "Automated payout runs with configurable frequency", "Requirements", "Draft", "Low", "Payments", "Feature", "Vendor", 8, "2027-01", 0),
        ],
        stakeholders_data=[
            ("Aldaana Almuqrin", "aldaana@pnu.edu.sa", "PNU", "Sponsor", "Accountable"),
            ("Mohammed Aljahmi", "mohammed@opex.com.sa", "OPEX", "COO", "Accountable"),
            ("Tarek Eltarrass", "tarek@opex.com.sa", "OPEX", "Former PM", "Informed"),
        ],
    )
    print("✅ CloudGate Platform: vision, 3 KPIs, 3 milestones, 3 releases, 10 backlog, 3 stakeholders")

    # --- Project 3: GO Telecom Integration ---
    go_user = created_users.get("ahmed@opex.com.sa", admin)
    create_project_with_data(
        name="GO Telecom Integration",
        client=go,
        description="Network connectivity integration and SD-WAN provisioning for GO Telecom",
        status="Active",
        pm_user=go_user,
        vision_stmt="Seamlessly integrate GO Telecom's network infrastructure with our cloud platform, enabling automated SD-WAN provisioning and real-time circuit monitoring.",
        objectives="1. Provision SD-WAN circuits in under 24 hours\n2. Achieve 99.95% network uptime\n3. Monitor 500+ circuits in real-time\n4. Reduce manual provisioning by 80%",
        kpis_data=[
            ("Provisioning Time", "24", "72", "hours", "Operations", "Provision SD-WAN in under 24h"),
            ("Network Uptime", "99.95", "99.7", "%", "Reliability", "Achieve 99.95% network uptime"),
            ("Circuits Monitored", "500", "150", "circuits", "Scale", "Monitor 500+ circuits"),
        ],
        roadmap_title="2026 GO Telecom Integration",
        rm_start=date(2026, 1, 1), rm_end=date(2026, 12, 31),
        milestones_data=[
            ("Q2 2026: API Integration", date(2026, 6, 30), "Completed", "GO Telecom API integration complete"),
            ("Q3 2026: SD-WAN Automation", date(2026, 9, 30), "On Track", "Automated SD-WAN provisioning"),
            ("Q4 2026: Monitoring Dashboard", date(2026, 12, 31), "At Risk", "Real-time circuit monitoring"),
        ],
        releases_data=[
            ("1.0.0", "GO API Connector", "Bidirectional API integration with GO Telecom", "Released", "2026-06-30", 0),
            ("1.1.0", "SD-WAN Provisioning", "Automated SD-WAN circuit provisioning", "Testing", "2026-09-30", 1),
            ("1.2.0", "Circuit Monitor", "Real-time monitoring with alerting", "In Progress", "2026-12-31", 2),
        ],
        backlog_data=[
            ("GO Telecom API authentication", "OAuth2 flow with token refresh", "Retrospective", "Done", "Critical", "Integration", "Feature", "Platform Admin", 8, "2026-06", 0),
            ("Circuit inventory sync", "Hourly sync of circuit inventory from GO API", "Release", "Done", "High", "Integration", "Feature", "Platform Admin", 5, "2026-06", 0),
            ("SD-WAN template builder", "Visual template builder for SD-WAN configs", "Testing", "In Progress", "Critical", "SD-WAN", "Feature", "Network Engineer", 13, "2026-09", 1),
            ("Automated circuit activation", "End-to-end circuit activation workflow", "Development", "In Progress", "High", "SD-WAN", "Feature", "Network Engineer", 8, "2026-09", 1),
            ("Real-time bandwidth monitor", "Live bandwidth graphs per circuit", "Design", "In Progress", "Medium", "Monitoring", "Feature", "Platform Admin", 8, "2026-12", 1),
            ("Alerting engine", "Threshold-based alerts with Slack/email", "Requirements", "Draft", "High", "Monitoring", "Feature", "Platform Admin", 5, "2026-11", 1),
            ("Circuit health scoring", "AI-based health score from multiple metrics", "Requirements", "Draft", "Low", "Monitoring", "Enhancement", "Platform Admin", 8, "2027-01", 1),
            ("Bulk circuit import", "CSV import for bulk circuit onboarding", "Post-Release", "Done", "Low", "Integration", "Enhancement", "Platform Admin", 3, "2026-06", 0),
        ],
        stakeholders_data=[
            ("Khalid Al-Harbi", "khalid@gotelecom.com.sa", "GO Telecom", "Technical Lead", "Responsible"),
            ("Ahmed Eldosoukey", "ahmed@opex.com.sa", "OPEX", "Cloud Architect", "Consulted"),
            ("Sara Al-Dossari", "sara@gotelecom.com.sa", "GO Telecom", "Sponsor", "Accountable"),
        ],
    )
    print("✅ GO Telecom Integration: vision, 3 KPIs, 3 milestones, 3 releases, 8 backlog, 3 stakeholders")

    # --- Project 4: TASAMA Multi-Cloud ---
    tasama_user = created_users.get("khalid@opex.com.sa", admin)
    create_project_with_data(
        name="TASAMA Multi-Cloud",
        client=tasama,
        description="Multi-cloud aggregation platform with cost optimization and resource intelligence",
        status="Active",
        pm_user=tasama_user,
        vision_stmt="Build a unified multi-cloud management platform aggregating AWS, Azure, and GCP resources with intelligent cost optimization and automated rightsizing recommendations.",
        objectives="1. Aggregate 3 cloud providers (AWS, Azure, GCP)\n2. Achieve 30% cost savings via rightsizing\n3. Process 10,000+ resources in real-time\n4. Generate weekly cost optimization reports\n5. Achieve SOC2 compliance",
        kpis_data=[
            ("Cost Savings", "30", "12", "%", "Financial", "Achieve 30% cost savings"),
            ("Resources Tracked", "10000", "3500", "resources", "Scale", "Process 10K+ resources"),
            ("Report Accuracy", "98", "91", "%", "Quality", "Generate accurate cost reports"),
        ],
        roadmap_title="2026-2027 TASAMA Platform",
        rm_start=date(2026, 4, 1), rm_end=date(2027, 6, 30),
        milestones_data=[
            ("Q3 2026: AWS Integration", date(2026, 9, 30), "Completed", "Full AWS resource aggregation"),
            ("Q4 2026: Azure + GCP", date(2026, 12, 31), "On Track", "Azure and GCP provider integration"),
            ("Q2 2027: Cost Optimization AI", date(2027, 6, 30), "At Risk", "AI-powered rightsizing recommendations"),
        ],
        releases_data=[
            ("1.0.0", "AWS Aggregation", "Full AWS resource aggregation and cost tracking", "Released", "2026-09-30", 0),
            ("1.1.0", "Multi-Cloud Dashboard", "Unified dashboard for AWS + Azure + GCP", "Pre-Release", "2026-12-31", 1),
            ("2.0.0", "Cost Optimization AI", "AI-powered rightsizing and cost recommendations", "Planning", "2027-06-30", 2),
        ],
        backlog_data=[
            ("AWS resource inventory", "Discover and track all EC2, RDS, S3 resources", "Retrospective", "Done", "Critical", "AWS Integration", "Feature", "Platform Admin", 13, "2026-09", 0),
            ("AWS cost aggregation", "Daily cost aggregation by account, service, tag", "Release", "Done", "Critical", "Cost Management", "Feature", "Platform Admin", 8, "2026-09", 0),
            ("Azure resource discovery", "Discover Azure VMs, databases, storage", "Pre-Release", "In Progress", "Critical", "Azure Integration", "Feature", "Platform Admin", 13, "2026-12", 0),
            ("GCP project scanning", "Scan GCP projects for compute resources", "Testing", "In Progress", "High", "GCP Integration", "Feature", "Platform Admin", 8, "2026-12", 0),
            ("Unified cost dashboard", "Cross-cloud cost comparison dashboard", "UAT", "In Progress", "High", "Dashboard", "Feature", "Platform Admin", 8, "2026-12", 1),
            ("Rightsizing recommendations", "AI-based rightsizing suggestions", "Requirements", "Draft", "Critical", "Optimization", "Feature", "Platform Admin", 13, "2027-03", 1),
            ("Cost anomaly detection", "ML-based anomaly detection on spend", "Design", "In Progress", "Medium", "Optimization", "Feature", "Platform Admin", 8, "2027-04", 1),
            ("SOC2 audit logging", "Comprehensive audit trail for SOC2", "Requirements", "Draft", "High", "Compliance", "Feature", "Auditor", 8, "2027-05", 0),
            ("Tag-based cost allocation", "Allocate costs by resource tags", "Post-Release", "Done", "Medium", "Cost Management", "Feature", "Platform Admin", 5, "2026-09", 0),
            ("Reserved instance planner", "Recommend RI purchases based on usage", "Requirements", "Draft", "Low", "Optimization", "Enhancement", "Platform Admin", 5, "2027-06", 0),
        ],
        stakeholders_data=[
            ("Mohammed Al-Otaibi", "mohammed@tasama.sa", "TASAMA", "Program Director", "Accountable"),
            ("Fatima Al-Zahra", "fatima@opex.com.sa", "OPEX", "Cloud Architect", "Responsible"),
            ("Omar Al-Shehri", "omar@tasama.sa", "TASAMA", "Technical Lead", "Consulted"),
        ],
    )
    print("✅ TASAMA Multi-Cloud: vision, 3 KPIs, 3 milestones, 3 releases, 10 backlog, 3 stakeholders")

    # --- Project 5: PNU Mobile App (Yotta) ---
    yotta_user = created_users.get("fatima@opex.com.sa", admin)
    create_project_with_data(
        name="PNU Mobile App",
        client=yotta,
        description="Native iOS/Android app for PNU students — schedules, grades, campus services",
        status="On Hold",
        pm_user=yotta_user,
        vision_stmt="Deliver a premium mobile experience for PNU students, providing instant access to schedules, grades, campus navigation, and university services.",
        objectives="1. Achieve 4.5+ app store rating\n2. Reach 50,000+ active users\n3. Sub-1s screen load time\n4. Support push notifications for 100% of announcements\n5. Offline mode for key features",
        kpis_data=[
            ("App Store Rating", "4.5", "3.8", "stars", "Quality", "Achieve 4.5+ rating"),
            ("Active Users", "50000", "8000", "users", "Growth", "Reach 50K+ users"),
            ("Screen Load Time", "1", "2.8", "seconds", "Performance", "Sub-1s load time"),
        ],
        roadmap_title="2026-2027 Mobile App Roadmap",
        rm_start=date(2026, 5, 1), rm_end=date(2027, 6, 30),
        milestones_data=[
            ("Q3 2026: MVP Release", date(2026, 9, 30), "On Track", "Login, schedule, grades"),
            ("Q4 2026: Campus Services", date(2026, 12, 31), "At Risk", "Navigation, cafeteria, library"),
            ("Q2 2027: Full Feature Set", date(2027, 6, 30), "On Track", "Offline mode, push, social"),
        ],
        releases_data=[
            ("1.0.0", "MVP — Schedule & Grades", "Core student features", "Released", "2026-09-30", 0),
            ("1.1.0", "Campus Services", "Navigation, cafeteria, library access", "UAT", "2026-12-31", 1),
            ("1.2.0", "Offline Mode", "Offline access to schedule and grades", "Planning", "2027-06-30", 2),
        ],
        backlog_data=[
            ("Student login with SSO", "SSO integration with PNU Active Directory", "Retrospective", "Done", "Critical", "Auth", "Feature", "Student", 8, "2026-09", 0),
            ("Schedule viewer", "Weekly and daily schedule with push reminders", "Release", "Done", "High", "Schedule", "Feature", "Student", 8, "2026-09", 0),
            ("Grades display", "Semester grades with GPA calculator", "Post-Release", "Done", "High", "Academic", "Feature", "Student", 5, "2026-09", 0),
            ("Campus map navigation", "Interactive map with building search", "UAT", "In Progress", "Medium", "Campus", "Feature", "Student", 13, "2026-12", 1),
            ("Cafeteria menu & ordering", "Daily menu with pre-order", "Testing", "In Progress", "Medium", "Services", "Feature", "Student", 8, "2026-12", 1),
            ("Push notification system", "Real-time announcements and grade alerts", "Development", "In Progress", "Critical", "Notifications", "Feature", "Student", 8, "2027-03", 1),
            ("Offline schedule access", "Cache schedule for offline viewing", "Design", "In Progress", "High", "Offline", "Feature", "Student", 5, "2027-06", 2),
            ("Social feed", "Student social feed with moderation", "Requirements", "Draft", "Low", "Social", "Feature", "Student", 13, "2027-06", 2),
            ("Biometric login", "Face ID / fingerprint authentication", "Requirements", "Draft", "Medium", "Auth", "Enhancement", "Student", 5, "2027-04", 0),
        ],
        stakeholders_data=[
            ("Nora Al-Qahtani", "nora@pnu.edu.sa", "PNU", "Product Owner", "Accountable"),
            ("Omar Al-Shehri", "omar@opex.com.sa", "OPEX", "Mobile Lead", "Responsible"),
            ("Aldaana Almuqrin", "aldaana@pnu.edu.sa", "PNU", "Dean of IT", "Informed"),
        ],
    )
    print("✅ PNU Mobile App: vision, 3 KPIs, 3 milestones, 3 releases, 9 backlog, 3 stakeholders")

    # --- Form templates + instances ---
    if db.query(FormTemplate).count() == 0:
        ft1 = FormTemplate(
            name="Release Readiness Checklist",
            form_type="checklist",
            description="Pre-release readiness verification checklist",
            field_schema='[{"name":"code_review_complete","label":"Code review complete","type":"boolean"},{"name":"tests_passing","label":"All tests passing","type":"boolean"},{"name":"docs_updated","label":"Documentation updated","type":"boolean"},{"name":"security_scan","label":"Security scan passed","type":"boolean"},{"name":"stakeholder_signoff","label":"Stakeholder sign-off received","type":"boolean"}]',
        )
        db.add(ft1)

        ft2 = FormTemplate(
            name="UAT Sign-off Form",
            form_type="signoff",
            description="User acceptance testing sign-off",
            field_schema='[{"name":"tester_name","label":"Tester Name","type":"text"},{"name":"test_cases_run","label":"Test Cases Run","type":"number"},{"name":"test_cases_passed","label":"Test Cases Passed","type":"number"},{"name":"defects_found","label":"Defects Found","type":"number"},{"name":"signoff_decision","label":"Sign-off Decision","type":"select","options":["Approved","Rejected","Conditional"]},{"name":"comments","label":"Comments","type":"textarea"}]',
        )
        db.add(ft2)

        ft3 = FormTemplate(
            name="Change Request Form",
            form_type="request",
            description="Submit a change request for review",
            field_schema='[{"name":"change_title","label":"Change Title","type":"text"},{"name":"change_type","label":"Change Type","type":"select","options":["Feature","Bug Fix","Enhancement","Infrastructure"]},{"name":"priority","label":"Priority","type":"select","options":["Critical","High","Medium","Low"]},{"name":"description","label":"Description","type":"textarea"},{"name":"impact","label":"Business Impact","type":"textarea"},{"name":"requested_by","label":"Requested By","type":"text"}]',
        )
        db.add(ft3)
        db.commit()
        print("✅ Created 3 form templates (Release Readiness, UAT Sign-off, Change Request)")

        # Create form instances for PNU Cloud
        fi1 = FormInstance(
            template_id=ft1.id, project_id=pnu.id,
            status="Submitted", created_by=admin.id,
            data='{"code_review_complete":true,"tests_passing":true,"docs_updated":false,"security_scan":true,"stakeholder_signoff":false}',
        )
        db.add(fi1)

        fi2 = FormInstance(
            template_id=ft2.id, project_id=pnu.id,
            status="Draft", created_by=admin.id,
            data='{"tester_name":"Khalid Al-Harbi","test_cases_run":45,"test_cases_passed":42,"defects_found":3,"signoff_decision":"Conditional","comments":"3 minor defects, recommend conditional sign-off"}',
        )
        db.add(fi2)

        # Create form instances for CloudGate
        cg = db.query(Project).filter(Project.name == "CloudGate Platform").first()
        if cg:
            fi3 = FormInstance(
                template_id=ft3.id, project_id=cg.id,
                status="Approved", created_by=admin.id,
                data='{"change_title":"Add multi-currency support","change_type":"Feature","priority":"Medium","description":"Support SAR, USD, EUR with live FX rates","impact":"Enables international vendors","requested_by":"Aldaana Almuqrin"}',
            )
            db.add(fi3)

        # Create form instances for TASAMA
        tm = db.query(Project).filter(Project.name == "TASAMA Multi-Cloud").first()
        if tm:
            fi4 = FormInstance(
                template_id=ft1.id, project_id=tm.id,
                status="Approved", created_by=admin.id,
                data='{"code_review_complete":true,"tests_passing":true,"docs_updated":true,"security_scan":true,"stakeholder_signoff":true}',
            )
            db.add(fi4)

        db.commit()
        print("✅ Created 4 form instances across projects")

    # --- Additional approvals for other projects ---
    from app.models.approval import ApprovalRequest, ApprovalStep
    from sqlalchemy.sql import func as sa_func

    cg_proj = db.query(Project).filter(Project.name == "CloudGate Platform").first()
    cg_rel = db.query(Release).filter(Release.project_id == cg_proj.id).first() if cg_proj else None
    if cg_proj and cg_rel and not db.query(ApprovalRequest).filter(ApprovalRequest.release_id == cg_rel.id).first():
        # CloudGate release 1.0.0 is in UAT → pending approval from Product Owner for UAT → Pre-Release
        ap_cg = ApprovalRequest(
            project_id=cg_proj.id,
            title=f"Release {cg_rel.version}: UAT → Pre-Release",
            description="Approve UAT passed and readiness for release",
            request_type="release", requested_by=admin.id,
            release_id=cg_rel.id, target_phase="Pre-Release", status="Pending",
        )
        db.add(ap_cg)
        db.commit()
        db.refresh(ap_cg)
        db.add(ApprovalStep(request_id=ap_cg.id, step_order=1, role_name="Product Owner", status="Pending"))
        db.commit()
        print("✅ Created pending approval for CloudGate release (Product Owner)")

    go_proj = db.query(Project).filter(Project.name == "GO Telecom Integration").first()
    go_rel = db.query(Release).filter(Release.project_id == go_proj.id, Release.status == "Testing").first() if go_proj else None
    if go_proj and go_rel and not db.query(ApprovalRequest).filter(ApprovalRequest.release_id == go_rel.id).first():
        # GO Telecom release is in Testing → pending approval from QA Lead for Testing → UAT
        ap_go = ApprovalRequest(
            project_id=go_proj.id,
            title=f"Release {go_rel.version}: Testing → UAT",
            description="Approve SIT results and readiness for UAT",
            request_type="release", requested_by=admin.id,
            release_id=go_rel.id, target_phase="UAT", status="Pending",
        )
        db.add(ap_go)
        db.commit()
        db.refresh(ap_go)
        db.add(ApprovalStep(request_id=ap_go.id, step_order=1, role_name="QA Lead", status="Pending"))
        db.commit()
        print("✅ Created pending approval for GO Telecom release (QA Lead)")

    tm_proj = db.query(Project).filter(Project.name == "TASAMA Multi-Cloud").first()
    tm_rel = db.query(Release).filter(Release.project_id == tm_proj.id, Release.status == "Pre-Release").first() if tm_proj else None
    if tm_proj and tm_rel and not db.query(ApprovalRequest).filter(ApprovalRequest.release_id == tm_rel.id).first():
        # TASAMA release is in Pre-Release → pending approval from Release Manager for Pre-Release → Released
        ap_tm = ApprovalRequest(
            project_id=tm_proj.id,
            title=f"Release {tm_rel.version}: Pre-Release → Released",
            description="Approve deployment checklist and go-live",
            request_type="release", requested_by=admin.id,
            release_id=tm_rel.id, target_phase="Released", status="Pending",
        )
        db.add(ap_tm)
        db.commit()
        db.refresh(ap_tm)
        db.add(ApprovalStep(request_id=ap_tm.id, step_order=1, role_name="Release Manager", status="Pending"))
        db.commit()
        print("✅ Created pending approval for TASAMA release (Release Manager)")

    # --- User Tasks (personal to-dos) ---
    if db.query(UserTask).count() == 0:
        pnu = db.query(Project).filter(Project.name == "PNU Cloud").first()
        cg = db.query(Project).filter(Project.name == "CloudGate").first()
        ms = db.query(Milestone).first()

        sample_tasks = [
            UserTask(
                title="Review AD domain integration proposal for Citrix",
                description="Follow up with GO Telecom on the AD domain question before Citrix deployment.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=pnu.id if pnu else None,
                milestone_id=ms.id if ms else None,
                due_date=date.today() + timedelta(days=2),
                reminder_days=3, status="Pending", priority="Urgent",
            ),
            UserTask(
                title="Prepare weekly status report for NITC",
                description="Compile progress from all partners for the weekly client update.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=pnu.id if pnu else None,
                due_date=date.today() + timedelta(days=5),
                reminder_days=3, status="Pending", priority="High",
            ),
            UserTask(
                title="Review backlog items for CloudGate release",
                description="Prioritize features for the next release cycle.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=cg.id if cg else None,
                due_date=date.today() + timedelta(days=7),
                reminder_days=3, status="Pending", priority="Medium",
            ),
            UserTask(
                title="Update stakeholder matrix",
                description="Add new contacts from TASAMA and Yotta.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=pnu.id if pnu else None,
                due_date=date.today() - timedelta(days=1),  # overdue
                reminder_days=3, status="In Progress", priority="High",
            ),
            UserTask(
                title="Schedule Q3 retrospective",
                description="Coordinate with team for a 1-hour retrospective session.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=None,  # general task
                due_date=date.today() + timedelta(days=14),
                reminder_days=5, status="Pending", priority="Low",
            ),
            UserTask(
                title="Complete CPMAI module 3",
                description="Finish the data preparation module.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=None,  # general personal task
                due_date=date.today() + timedelta(days=21),
                reminder_days=7, status="Pending", priority="Medium",
            ),
            UserTask(
                title="Review OPEX organizational structure",
                description="Finalize the updated org chart with Mohammed Aljahmi.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=None,
                due_date=date.today() - timedelta(days=3),  # overdue
                reminder_days=3, status="Pending", priority="Urgent",
            ),
            UserTask(
                title="Submit monthly expense report",
                description="Compile and submit August expenses to finance.",
                assigned_to=admin.id, created_by=admin.id,
                project_id=None,
                due_date=date.today() + timedelta(days=1),
                reminder_days=2, status="Completed", priority="Medium",
            ),
        ]
        for t in sample_tasks:
            db.add(t)
        db.commit()
        print(f"✅ Created {len(sample_tasks)} user tasks (including overdue and completed)")

    # --- Summary ---
    total_clients = db.query(Client).count()
    total_projects = db.query(Project).count()
    total_kpis = db.query(KPI).count()
    total_milestones = db.query(Milestone).count()
    total_releases = db.query(Release).count()
    total_backlog = db.query(BacklogItem).count()
    total_stakeholders = db.query(Stakeholder).count()
    total_forms = db.query(FormInstance).count()
    total_approvals = db.query(ApprovalRequest).count()
    total_users = db.query(User).count()

    db.close()
    print(f"\n📊 COMPREHENSIVE SAMPLE DATA SUMMARY:")
    print(f"   {total_clients} clients | {total_projects} projects | {total_users} users")
    print(f"   {total_kpis} KPIs | {total_milestones} milestones | {total_releases} releases")
    print(f"   {total_backlog} backlog items | {total_stakeholders} stakeholders")
    print(f"   {total_forms} form instances | {total_approvals} approval requests")
    print(f"\n🔐 Login credentials:")
    print(f"   Email:    rana@opex.com.sa")
    print(f"   Password: Pmo@2026")


if __name__ == "__main__":
    seed()
