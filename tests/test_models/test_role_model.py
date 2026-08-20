"""Test the Role model — TDD RED phase."""
import pytest


class TestRoleModel:
    """Tests for the Role model — based on the 12 RACI roles."""

    RACI_ROLES = [
        "Product Owner",
        "Product Manager",
        "Business Lead",
        "UX Designer",
        "Tech Lead",
        "Engineering Team",
        "QA Lead",
        "QA Engineer",
        "DevOps Lead",
        "DevOps Engineer",
        "CX Engineer",
        "PMO",
    ]

    def test_create_role(self, db_session):
        """A role can be created with name and description."""
        from app.models.role import Role

        role = Role(
            name="Product Manager",
            description="Accountable for product gates, UAT sign-off, PIV",
        )
        db_session.add(role)
        db_session.commit()

        assert role.id is not None
        assert role.name == "Product Manager"

    def test_create_all_12_raci_roles(self, db_session):
        """All 12 RACI roles can be created."""
        from app.models.role import Role

        for role_name in self.RACI_ROLES:
            role = Role(name=role_name, description=f"RACI role: {role_name}")
            db_session.add(role)

        db_session.commit()

        roles = db_session.query(Role).all()
        assert len(roles) == 12
        role_names = [r.name for r in roles]
        for expected in self.RACI_ROLES:
            assert expected in role_names

    def test_role_name_is_required(self, db_session):
        """A role cannot be created without a name."""
        from app.models.role import Role

        role = Role(description="No name")
        db_session.add(role)
        with pytest.raises(Exception):
            db_session.commit()

    def test_role_name_is_unique(self, db_session):
        """Two roles cannot have the same name."""
        from app.models.role import Role

        role1 = Role(name="Tech Lead", description="Leads development")
        role2 = Role(name="Tech Lead", description="Duplicate")
        db_session.add(role1)
        db_session.add(role2)
        with pytest.raises(Exception):
            db_session.commit()

    def test_role_repr(self, db_session):
        """Role has a readable string representation."""
        from app.models.role import Role

        role = Role(name="QA Lead", description="Quality assurance lead")
        assert "QA Lead" in repr(role)
