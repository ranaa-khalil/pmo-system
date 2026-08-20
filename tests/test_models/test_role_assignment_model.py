"""Test the RoleAssignment model — TDD RED phase.

RoleAssignment links a User to a Role on a specific Project.
This is the core of RBAC: a user can have different roles on different projects.
"""
import pytest
from sqlalchemy.exc import IntegrityError


class TestRoleAssignmentModel:
    """Tests for the RoleAssignment model."""

    def test_assign_role_to_user_on_project(self, db_session):
        """A user can be assigned a role on a project."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.user import User
        from app.models.role import Role
        from app.models.role_assignment import RoleAssignment

        # Create prerequisites
        client = Client(name="NITC / PNU", contact_email="AEalmuqrin@nitc.sa")
        db_session.add(client)
        db_session.commit()

        project = Project(name="PNU Cloud", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        user = User(email="r.khalil@opex.com.sa", name="Rana Khalil", hashed_password="x")
        db_session.add(user)
        db_session.commit()

        role = Role(name="Product Manager", description="PM role")
        db_session.add(role)
        db_session.commit()

        # Assign role
        assignment = RoleAssignment(
            user_id=user.id,
            role_id=role.id,
            project_id=project.id,
        )
        db_session.add(assignment)
        db_session.commit()

        assert assignment.id is not None
        assert assignment.user_id == user.id
        assert assignment.role_id == role.id
        assert assignment.project_id == project.id

    def test_role_assignment_relationships(self, db_session):
        """RoleAssignment has relationships back to user, role, and project."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.user import User
        from app.models.role import Role
        from app.models.role_assignment import RoleAssignment

        client = Client(name="GO Telecom", contact_email="info@go.com.sa")
        db_session.add(client)
        db_session.commit()

        project = Project(name="CloudGate", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        user = User(email="ahmed@opex.com.sa", name="Ahmed Eldosoukey", hashed_password="x")
        db_session.add(user)
        db_session.commit()

        role = Role(name="Tech Lead", description="Leads development")
        db_session.add(role)
        db_session.commit()

        assignment = RoleAssignment(
            user_id=user.id,
            role_id=role.id,
            project_id=project.id,
        )
        db_session.add(assignment)
        db_session.commit()

        assert assignment.user.name == "Ahmed Eldosoukey"
        assert assignment.role.name == "Tech Lead"
        assert assignment.project.name == "CloudGate"

    def test_user_can_have_different_roles_on_different_projects(self, db_session):
        """A user can be Tech Lead on one project and QA Lead on another."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.user import User
        from app.models.role import Role
        from app.models.role_assignment import RoleAssignment

        client = Client(name="Test", contact_email="t@t.com")
        db_session.add(client)
        db_session.commit()

        project1 = Project(name="PNU Cloud", client_id=client.id)
        project2 = Project(name="CloudGate", client_id=client.id)
        db_session.add_all([project1, project2])
        db_session.commit()

        user = User(email="multi@opex.com.sa", name="Multi Role", hashed_password="x")
        db_session.add(user)
        db_session.commit()

        role1 = Role(name="Tech Lead", description="Dev lead")
        role2 = Role(name="QA Lead", description="QA lead")
        db_session.add_all([role1, role2])
        db_session.commit()

        assign1 = RoleAssignment(user_id=user.id, role_id=role1.id, project_id=project1.id)
        assign2 = RoleAssignment(user_id=user.id, role_id=role2.id, project_id=project2.id)
        db_session.add_all([assign1, assign2])
        db_session.commit()

        assignments = db_session.query(RoleAssignment).filter_by(user_id=user.id).all()
        assert len(assignments) == 2

    def test_project_github_repo_field(self, db_session):
        """A project can have a github_repo field for GitHub integration."""
        from app.models.client import Client
        from app.models.project import Project

        client = Client(name="Test", contact_email="t@t.com")
        db_session.add(client)
        db_session.commit()

        project = Project(
            name="CloudGate",
            client_id=client.id,
            github_repo="opexsa/cloudgate",
        )
        db_session.add(project)
        db_session.commit()

        assert project.github_repo == "opexsa/cloudgate"

    def test_role_assignment_repr(self, db_session):
        """RoleAssignment has a readable string representation."""
        from app.models.client import Client
        from app.models.project import Project
        from app.models.user import User
        from app.models.role import Role
        from app.models.role_assignment import RoleAssignment

        client = Client(name="Test", contact_email="t@t.com")
        db_session.add(client)
        db_session.commit()

        project = Project(name="PNU Cloud", client_id=client.id)
        db_session.add(project)
        db_session.commit()

        user = User(email="r.khalil@opex.com.sa", name="Rana Khalil", hashed_password="x")
        db_session.add(user)
        db_session.commit()

        role = Role(name="Product Manager", description="PM")
        db_session.add(role)
        db_session.commit()

        assignment = RoleAssignment(user_id=user.id, role_id=role.id, project_id=project.id)
        db_session.add(assignment)
        db_session.commit()

        assert "RoleAssignment" in repr(assignment)
