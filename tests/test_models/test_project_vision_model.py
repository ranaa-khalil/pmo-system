"""Test the ProjectVision model — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestProjectVisionModel:
    """Tests for the ProjectVision model."""

    def test_create_vision_for_project(self, db_session):
        """A vision can be created and linked to a project."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.project_vision import ProjectVision

        client = Client(name="NITC", contact_email="n@n.sa")
        db_session.add(client)
        db_session.commit()

        project = Project(name="PNU Cloud", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        vision = ProjectVision(
            project_id=project.id,
            statement="Become the leading cloud platform for Saudi universities by 2030",
            strategic_objectives="1. 99.9% uptime\n2. 50K active users\n3. Multi-region DR",
        )
        db_session.add(vision)
        db_session.commit()

        assert vision.id is not None
        assert vision.project_id == project.id
        assert "cloud platform" in vision.statement

    def test_vision_requires_project_id(self, db_session):
        """Vision cannot be created without a project_id."""
        from app.models.project_vision import ProjectVision

        vision = ProjectVision(statement="Some vision")
        db_session.add(vision)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_vision_statement_is_required(self, db_session):
        """Vision cannot be created without a statement."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.project_vision import ProjectVision

        client = Client(name="Test", contact_email="t@t.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        vision = ProjectVision(project_id=project.id)
        db_session.add(vision)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_one_vision_per_project(self, db_session):
        """Only one vision per project (one-to-one)."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.project_vision import ProjectVision

        client = Client(name="Test2", contact_email="t2@t.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P2", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        vision1 = ProjectVision(project_id=project.id, statement="Vision 1")
        db_session.add(vision1)
        db_session.commit()

        vision2 = ProjectVision(project_id=project.id, statement="Vision 2")
        db_session.add(vision2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_vision_repr(self, db_session):
        """Vision has a useful repr."""
        from app.models.project_vision import ProjectVision
        vision = ProjectVision(statement="Test", project_id=1)
        assert "ProjectVision" in repr(vision)
