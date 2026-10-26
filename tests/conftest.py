"""Pytest fixtures for PMO System tests.

Two eras of tests live in this suite:
- JWT-era endpoints require a Bearer token AND a resolvable tenant
  (get_current_tenant 403s without an active tenant + membership).
- Legacy model tests only need a raw SQLAlchemy session.

`client` is auto-authenticated (super_admin + tenant owner) so router tests
read like business flows; `anon_client` exercises the no-auth path.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import all models BEFORE create_all
import app.models  # noqa: F401 — register all models with Base
from app.database import Base, get_db
from app.main import app
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.auth import create_access_token, hash_password

# Use in-memory SQLite with StaticPool so all sessions share the same connection
# (otherwise each session gets its own empty in-memory DB)
TEST_DB_URL = "sqlite://"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session(db):
    """Alias for `db` — older model tests request `db_session`."""
    return db


@pytest.fixture(scope="function")
def auth_user(db):
    """Super admin with an active tenant + owner membership (JWT era)."""
    tenant = Tenant(name="Test Tenant", slug="test-tenant", plan="enterprise", status="active")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    user = User(
        email="test@pmo.test",
        name="Test User",
        hashed_password=hash_password("TestPass123!"),
        system_role="super_admin",
        active_tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    return {"user": user, "tenant": tenant}


@pytest.fixture(scope="function")
def client(db, auth_user):
    """Test client with database override + Bearer auth pre-applied."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token({"sub": str(auth_user["user"].id)})
    tc = TestClient(app)
    tc.headers.update({"Authorization": f"Bearer {token}"})
    yield tc
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def anon_client(db):
    """Test client with database override but NO auth — for 401/403 paths."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(db, auth_user):
    """Auth token for the shared test user."""
    return create_access_token({"sub": str(auth_user["user"].id)})


@pytest.fixture
def auth_headers(auth_token):
    """Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {auth_token}"}
