"""Seed script — creates default admin user, RACI roles, and sample data.

Run with: python -m app.seed
"""
from app.database import SessionLocal, engine, Base
import app.models  # noqa: F401 — register all models
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.backlog_item import BacklogItem
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
        )
        db.add(admin)
        print("✅ Created admin user: rana@opex.com.sa")
    else:
        admin.hashed_password = hash_password("Pmo@2026")
        print("ℹ️ Admin user already exists — password reset to default")

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
                       description="Princess Nourah University — Cloud Services")
        db.add(nitc)
        print("✅ Created client: NITC / PNU")

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

    # --- Sample backlog items ---
    existing_backlog = db.query(BacklogItem).filter(BacklogItem.project_id == pnu.id).count()
    if existing_backlog == 0:
        items = [
            BacklogItem(project_id=pnu.id, title="User authentication module",
                        description="SSO integration with AD, role-based access control",
                        priority="High", current_phase="Development", status="In Progress"),
            BacklogItem(project_id=pnu.id, title="Dashboard analytics",
                        description="Real-time metrics dashboard with SLA tracking",
                        priority="Medium", current_phase="Design", status="In Progress"),
            BacklogItem(project_id=pnu.id, title="Multi-tenant infrastructure",
                        description="Kubernetes namespaces, network policies, resource quotas",
                        priority="Critical", current_phase="Requirements", status="Draft"),
        ]
        for item in items:
            db.add(item)
        db.commit()
        print(f"✅ Created {len(items)} backlog items for PNU Cloud")

    db.close()
    print("\n🔐 Login credentials:")
    print("   Email:    rana@opex.com.sa")
    print("   Password: Pmo@2026")


if __name__ == "__main__":
    seed()
