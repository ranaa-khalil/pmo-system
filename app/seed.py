"""Seed script — creates default admin user and sample data.

Run with: python -m app.seed
"""
from app.database import SessionLocal, engine, Base
import app.models  # noqa: F401 — register all models
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.services.auth import hash_password


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
        # Ensure password is set (in case DB was partially reset)
        admin.hashed_password = hash_password("Pmo@2026")
        print("ℹ️ Admin user already exists — password reset to default")

    # --- Sample clients ---
    nitc = db.query(Client).filter(Client.name == "NITC / PNU").first()
    if not nitc:
        nitc = Client(name="NITC / PNU", contact_email="pmo@nitc.gov.sa",
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
        print("✅ Created project: PNU Cloud")

    db.commit()
    db.close()
    print("\n🔐 Login credentials:")
    print("   Email:    rana@opex.com.sa")
    print("   Password: Pmo@2026")


if __name__ == "__main__":
    seed()
