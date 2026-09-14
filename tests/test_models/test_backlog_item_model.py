"""Test the BacklogItem model — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestBacklogItemModel:
    """Tests for the BacklogItem model."""

    def test_create_backlog_item(self, db_session):
        """A backlog item can be created and linked to a project."""
        from app.models.backlog_item import BacklogItem
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="BL Test", contact_email="b@b.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="BL Proj", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        item = BacklogItem(
            project_id=project.id,
            title="User authentication module",
            description="Implement JWT-based login for the portal",
            current_phase="Requirements",
            status="Draft",
            priority="High",
        )
        db_session.add(item)
        db_session.commit()

        assert item.id is not None
        assert item.project_id == project.id
        assert item.title == "User authentication module"
        assert item.current_phase == "Requirements"

    def test_backlog_item_requires_project_id(self, db_session):
        """BacklogItem cannot be created without a project_id."""
        from app.models.backlog_item import BacklogItem

        item = BacklogItem(title="Test")
        db_session.add(item)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_backlog_item_title_is_required(self, db_session):
        """BacklogItem cannot be created without a title."""
        from app.models.backlog_item import BacklogItem
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="BL2", contact_email="b2@b.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P2", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        item = BacklogItem(project_id=project.id)
        db_session.add(item)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_default_phase_is_requirements(self, db_session):
        """New backlog items default to 'Requirements' phase."""
        from app.models.backlog_item import BacklogItem
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="BL3", contact_email="b3@b.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P3", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        item = BacklogItem(project_id=project.id, title="Default phase item")
        db_session.add(item)
        db_session.commit()

        assert item.current_phase == "Requirements"
        assert item.status == "Draft"
        assert item.priority == "Medium"

    def test_project_can_have_multiple_backlog_items(self, db_session):
        """A project can have many backlog items."""
        from app.models.backlog_item import BacklogItem
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="BL4", contact_email="b4@b.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P4", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        for i in range(5):
            db_session.add(BacklogItem(
                project_id=project.id,
                title=f"Feature {i}",
                priority="High" if i < 2 else "Medium",
            ))
        db_session.commit()

        items = db_session.query(BacklogItem).filter_by(project_id=project.id).all()
        assert len(items) == 5

    def test_github_issue_number_nullable(self, db_session):
        """github_issue_number is nullable (not synced yet)."""
        from app.models.backlog_item import BacklogItem
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="BL5", contact_email="b5@b.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P5", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        item = BacklogItem(project_id=project.id, title="GitHub item")
        db_session.add(item)
        db_session.commit()

        assert item.github_issue_number is None

    def test_backlog_item_repr(self, db_session):
        """BacklogItem has a useful repr."""
        from app.models.backlog_item import BacklogItem
        item = BacklogItem(title="Test", project_id=1)
        assert "BacklogItem" in repr(item)
