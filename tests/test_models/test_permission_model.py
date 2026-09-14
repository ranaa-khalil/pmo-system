"""Test the Permission and RolePermission models — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestPermissionModel:
    """Tests for the Permission model."""

    def test_create_permission(self, db_session):
        """Can create a permission with name and description."""
        from app.models.permission import Permission
        perm = Permission(name="client:create", description="Create new clients")
        db_session.add(perm)
        db_session.commit()
        assert perm.id is not None
        assert perm.name == "client:create"
        assert perm.description == "Create new clients"

    def test_permission_name_is_required(self, db_session):
        """Permission name is required."""
        from sqlalchemy.exc import IntegrityError

        from app.models.permission import Permission
        perm = Permission(description="No name")
        db_session.add(perm)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_permission_name_is_unique(self, db_session):
        """Permission name must be unique."""
        from app.models.permission import Permission
        db_session.add(Permission(name="project:read", description="Read projects"))
        db_session.commit()
        db_session.add(Permission(name="project:read", description="Duplicate"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_permission_repr(self, db_session):
        """Permission has a useful repr."""
        from app.models.permission import Permission
        perm = Permission(name="client:delete", description="Delete clients")
        assert "client:delete" in repr(perm)


class TestRolePermissionModel:
    """Tests for the RolePermission model — links Role to Permission."""

    def test_assign_permission_to_role(self, db_session):
        """Can assign a permission to a role."""
        from app.models.permission import Permission
        from app.models.role import Role
        from app.models.role_permission import RolePermission

        role = Role(name="Product Manager", description="PM role")
        perm = Permission(name="client:create", description="Create clients")
        db_session.add_all([role, perm])
        db_session.commit()

        rp = RolePermission(role_id=role.id, permission_id=perm.id)
        db_session.add(rp)
        db_session.commit()
        assert rp.id is not None

    def test_role_can_have_multiple_permissions(self, db_session):
        """A role can have many permissions."""
        from app.models.permission import Permission
        from app.models.role import Role
        from app.models.role_permission import RolePermission

        role = Role(name="Tech Lead", description="Tech Lead role")
        db_session.add(role)
        db_session.commit()

        for name in ["project:read", "project:create", "requirement:approve", "qa:signoff"]:
            perm = Permission(name=name, description=name)
            db_session.add(perm)
            db_session.flush()
            db_session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db_session.commit()

        perms = db_session.query(RolePermission).filter_by(role_id=role.id).all()
        assert len(perms) == 4

    def test_unique_role_permission_constraint(self, db_session):
        """Same permission can't be assigned to same role twice."""
        from app.models.permission import Permission
        from app.models.role import Role
        from app.models.role_permission import RolePermission

        role = Role(name="QA Lead", description="QA role")
        perm = Permission(name="qa:signoff", description="Sign off QA")
        db_session.add_all([role, perm])
        db_session.commit()

        db_session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db_session.commit()
        db_session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
