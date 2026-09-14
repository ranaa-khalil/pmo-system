"""Test the Project model — TDD RED phase."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError


class TestProjectModel:
    """Tests for the Project model."""

    def test_create_project_linked_to_client(self, db_session):
        """A project can be created and linked to a client."""
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="NITC / PNU", contact_email="AEalmuqrin@nitc.sa")
        db_session.add(client)
        db_session.commit()

        project = Project(
            name="PNU Cloud",
            client_id=client.id,
            description="Cloud infrastructure project for PNU",
            status="Active",
            start_date=date(2026, 4, 1),
        )
        db_session.add(project)
        db_session.commit()

        assert project.id is not None
        assert project.name == "PNU Cloud"
        assert project.client_id == client.id
        assert project.status == "Active"
        assert project.start_date == date(2026, 4, 1)

    def test_project_name_is_required(self, db_session):
        """A project cannot be created without a name."""
        from app.models.project import Project

        project = Project(client_id=1)
        db_session.add(project)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_project_client_relationship(self, db_session):
        """Project has a relationship back to its client."""
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="GO Telecom", contact_email="info@go.com.sa")
        db_session.add(client)
        db_session.commit()

        project = Project(name="CloudGate", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        assert project.client.name == "GO Telecom"

    def test_project_status_defaults_to_active(self, db_session):
        """A project defaults to Active status."""
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="Test Client", contact_email="test@test.com")
        db_session.add(client)
        db_session.commit()

        project = Project(name="Test Project", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        assert project.status == "Active"

    def test_project_repr(self, db_session):
        """Project has a readable string representation."""
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="Test", contact_email="t@t.com")
        db_session.add(client)
        db_session.commit()

        project = Project(name="PNU Cloud", client_id=client.id)
        assert "PNU Cloud" in repr(project)
