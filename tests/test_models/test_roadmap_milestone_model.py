"""Test the Roadmap and Milestone models — TDD RED phase."""
import pytest
from datetime import date
from sqlalchemy.exc import IntegrityError


class TestRoadmapModel:
    """Tests for the Roadmap model."""

    def test_create_roadmap_for_project(self, db_session):
        """A roadmap can be created and linked to a project."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap

        client = Client(name="RM Test", contact_email="r@r.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="RM Proj", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        roadmap = Roadmap(
            project_id=project.id,
            title="PNU Cloud 2026 Roadmap",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db_session.add(roadmap)
        db_session.commit()

        assert roadmap.id is not None
        assert roadmap.project_id == project.id
        assert roadmap.title == "PNU Cloud 2026 Roadmap"

    def test_roadmap_requires_project_id(self, db_session):
        """Roadmap cannot be created without a project_id."""
        from app.models.roadmap import Roadmap

        roadmap = Roadmap(title="Test")
        db_session.add(roadmap)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_roadmap_title_is_required(self, db_session):
        """Roadmap cannot be created without a title."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap

        client = Client(name="R2", contact_email="r2@r.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P2", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        roadmap = Roadmap(project_id=project.id)
        db_session.add(roadmap)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_project_can_have_multiple_roadmaps(self, db_session):
        """A project can have multiple roadmaps (e.g., yearly)."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap

        client = Client(name="R3", contact_email="r3@r.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P3", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        for year in [2026, 2027]:
            db_session.add(Roadmap(
                project_id=project.id,
                title=f"Roadmap {year}",
                start_date=date(year, 1, 1),
                end_date=date(year, 12, 31),
            ))
        db_session.commit()

        roadmaps = db_session.query(Roadmap).filter_by(project_id=project.id).all()
        assert len(roadmaps) == 2


class TestMilestoneModel:
    """Tests for the Milestone model."""

    def test_create_milestone_in_roadmap(self, db_session):
        """A milestone can be created and linked to a roadmap."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap
        from app.models.milestone import Milestone

        client = Client(name="MS Test", contact_email="m@m.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="MS Proj", client_id=client.id)
        db_session.add(project)
        db_session.commit()
        roadmap = Roadmap(project_id=project.id, title="Roadmap",
                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        db_session.add(roadmap)
        db_session.commit()

        milestone = Milestone(
            roadmap_id=roadmap.id,
            title="Phase 1 Go-Live",
            target_date=date(2026, 3, 31),
            status="On Track",
        )
        db_session.add(milestone)
        db_session.commit()

        assert milestone.id is not None
        assert milestone.roadmap_id == roadmap.id
        assert milestone.title == "Phase 1 Go-Live"

    def test_milestone_requires_roadmap_id(self, db_session):
        """Milestone cannot be created without a roadmap_id."""
        from app.models.milestone import Milestone
        from datetime import date

        milestone = Milestone(title="Test", target_date=date(2026, 6, 1))
        db_session.add(milestone)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_milestone_title_is_required(self, db_session):
        """Milestone cannot be created without a title."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap
        from app.models.milestone import Milestone
        from datetime import date

        client = Client(name="M2", contact_email="m2@m.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P2", client_id=client.id)
        db_session.add(project)
        db_session.commit()
        roadmap = Roadmap(project_id=project.id, title="R",
                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        db_session.add(roadmap)
        db_session.commit()

        milestone = Milestone(roadmap_id=roadmap.id, target_date=date(2026, 6, 1))
        db_session.add(milestone)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_roadmap_can_have_multiple_milestones(self, db_session):
        """A roadmap can have many milestones."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.roadmap import Roadmap
        from app.models.milestone import Milestone
        from datetime import date

        client = Client(name="M3", contact_email="m3@m.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P3", client_id=client.id)
        db_session.add(project)
        db_session.commit()
        roadmap = Roadmap(project_id=project.id, title="R3",
                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        db_session.add(roadmap)
        db_session.commit()

        for i, month in enumerate([3, 6, 9, 12], 1):
            db_session.add(Milestone(
                roadmap_id=roadmap.id,
                title=f"Milestone {i}",
                target_date=date(2026, month, 15),
                status="On Track",
            ))
        db_session.commit()

        milestones = db_session.query(Milestone).filter_by(roadmap_id=roadmap.id).all()
        assert len(milestones) == 4
