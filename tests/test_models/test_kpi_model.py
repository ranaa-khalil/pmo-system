"""Test the KPI model — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestKPIModel:
    """Tests for the KPI model."""

    def test_create_kpi_for_project(self, db_session):
        """A KPI can be created and linked to a project."""
        from app.models.client import Client
        from app.models.kpi import KPI
        from app.models.project import Project

        client = Client(name="KPI Test", contact_email="k@k.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="KPI Proj", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        kpi = KPI(
            project_id=project.id,
            name="System Uptime",
            target_value="99.9%",
            current_value="99.5%",
            unit="percentage",
            category="SLA",
        )
        db_session.add(kpi)
        db_session.commit()

        assert kpi.id is not None
        assert kpi.project_id == project.id
        assert kpi.name == "System Uptime"

    def test_kpi_requires_project_id(self, db_session):
        """KPI cannot be created without a project_id."""
        from app.models.kpi import KPI

        kpi = KPI(name="Test KPI")
        db_session.add(kpi)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_kpi_name_is_required(self, db_session):
        """KPI cannot be created without a name."""
        from app.models.client import Client
        from app.models.kpi import KPI
        from app.models.project import Project

        client = Client(name="K2", contact_email="k2@k.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P2", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        kpi = KPI(project_id=project.id)
        db_session.add(kpi)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_project_can_have_multiple_kpis(self, db_session):
        """A project can have many KPIs."""
        from app.models.client import Client
        from app.models.kpi import KPI
        from app.models.project import Project

        client = Client(name="K3", contact_email="k3@k.sa")
        db_session.add(client)
        db_session.commit()
        project = Project(name="P3", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        for name in ["Uptime", "Response Time", "User Count", "Cost"]:
            db_session.add(KPI(project_id=project.id, name=name, target_value="X"))
        db_session.commit()

        kpis = db_session.query(KPI).filter_by(project_id=project.id).all()
        assert len(kpis) == 4

    def test_kpi_repr(self, db_session):
        """KPI has a useful repr."""
        from app.models.kpi import KPI
        kpi = KPI(name="Test", project_id=1)
        assert "KPI" in repr(kpi)
