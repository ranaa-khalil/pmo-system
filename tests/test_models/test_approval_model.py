"""Test the ApprovalRequest and ApprovalStep models — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestApprovalRequestModel:
    """Tests for the ApprovalRequest model."""

    def _create_project(self, db_session):
        from app.models.client import Client
        from app.models.project import Project
        c = Client(name="Approval Test", contact_email="a@a.sa")
        db_session.add(c)
        db_session.commit()
        p = Project(name="Approval Proj", client_id=c.id)
        db_session.add(p)
        db_session.commit()
        return p

    def test_create_approval_request(self, db_session):
        """An approval request can be created for a project."""
        from app.models.approval import ApprovalRequest
        p = self._create_project(db_session)

        req = ApprovalRequest(
            project_id=p.id,
            title="Release v1.2.0 Approval",
            description="Approve release of v1.2.0 to production",
            request_type="release",
            requested_by=1,
        )
        db_session.add(req)
        db_session.commit()

        assert req.id is not None
        assert req.status == "Pending"
        assert req.title == "Release v1.2.0 Approval"

    def test_approval_request_requires_project_id(self, db_session):
        from app.models.approval import ApprovalRequest
        req = ApprovalRequest(title="Test", request_type="release")
        db_session.add(req)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_approval_request_repr(self, db_session):
        from app.models.approval import ApprovalRequest
        req = ApprovalRequest(project_id=1, title="T", request_type="release")
        assert "ApprovalRequest" in repr(req)


class TestApprovalStepModel:
    """Tests for the ApprovalStep model."""

    def _create_request(self, db_session):
        from app.models.client import Client
        from app.models.project import Project
        from app.models.approval import ApprovalRequest
        c = Client(name="Step Test", contact_email="s@s.sa")
        db_session.add(c)
        db_session.commit()
        p = Project(name="Step Proj", client_id=c.id)
        db_session.add(p)
        db_session.commit()
        req = ApprovalRequest(project_id=p.id, title="Step Req", request_type="release", requested_by=1)
        db_session.add(req)
        db_session.commit()
        return req

    def test_create_approval_step(self, db_session):
        """An approval step can be created for a request."""
        from app.models.approval import ApprovalStep
        req = self._create_request(db_session)

        step = ApprovalStep(
            request_id=req.id,
            step_order=1,
            role_name="Product Owner",
            approver_id=1,
        )
        db_session.add(step)
        db_session.commit()

        assert step.id is not None
        assert step.status == "Pending"
        assert step.step_order == 1

    def test_approval_step_requires_request_id(self, db_session):
        from app.models.approval import ApprovalStep
        step = ApprovalStep(step_order=1, role_name="PM")
        db_session.add(step)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_multiple_steps_ordered(self, db_session):
        """Multiple steps can be created with different orders."""
        from app.models.approval import ApprovalStep
        req = self._create_request(db_session)

        for i, role in enumerate(["Product Owner", "Tech Lead", "Release Manager"], 1):
            step = ApprovalStep(
                request_id=req.id,
                step_order=i,
                role_name=role,
            )
            db_session.add(step)
        db_session.commit()

        steps = db_session.query(ApprovalStep).filter(ApprovalStep.request_id == req.id).order_by(ApprovalStep.step_order).all()
        assert len(steps) == 3
        assert steps[0].role_name == "Product Owner"
        assert steps[2].role_name == "Release Manager"

    def test_step_repr(self, db_session):
        from app.models.approval import ApprovalStep
        step = ApprovalStep(request_id=1, step_order=1, role_name="PM")
        assert "ApprovalStep" in repr(step)
