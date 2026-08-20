"""Test fixtures for the PMO system."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import sys
import os

# Add the project root to the path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db
from app.main import app as fastapi_app
import app.models  # noqa: F401 — register all models with Base.metadata


@pytest.fixture
def db_engine():
    """Create a fresh in-memory SQLite database for each test.

    Uses StaticPool so the same connection is shared across threads
    (FastAPI TestClient runs route handlers in a threadpool).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    """Create a database session for tests."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


class AuthenticatedClient(TestClient):
    """TestClient that automatically includes the auth token in all requests."""

    def __init__(self, *args, token=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._token = token

    def _add_auth(self, kwargs):
        headers = kwargs.get("headers", {})
        if "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self._token}"
            kwargs["headers"] = headers
        return kwargs

    def get(self, url, **kwargs):
        return super().get(url, **self._add_auth(kwargs))

    def post(self, url, **kwargs):
        return super().post(url, **self._add_auth(kwargs))

    def put(self, url, **kwargs):
        return super().put(url, **self._add_auth(kwargs))

    def delete(self, url, **kwargs):
        return super().delete(url, **self._add_auth(kwargs))

    def patch(self, url, **kwargs):
        return super().patch(url, **self._add_auth(kwargs))


@pytest.fixture
def client(db_session):
    """Create a FastAPI test client with the test database.

    Auto-registers and logs in a test user so all authenticated routes work.
    The auth token is automatically attached to all requests.
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db
    test_client = AuthenticatedClient(fastapi_app, token="")

    # Register and login a test user to get a token
    # Use raw TestClient methods (via super) to avoid auth header injection
    TestClient.post(test_client, "/api/auth/register", json={
        "email": "testuser@test.com",
        "full_name": "Test User",
        "password": "TestPass123!",
    })
    login_resp = TestClient.post(test_client, "/api/auth/login", json={
        "email": "testuser@test.com",
        "password": "TestPass123!",
    })
    token = login_resp.json()["access_token"]
    test_client._token = token

    yield test_client
    fastapi_app.dependency_overrides.clear()
