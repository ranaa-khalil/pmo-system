"""Test the User model — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestUserModel:
    """Tests for the User model."""

    def test_create_user_with_email_and_name(self, db_session):
        """A user can be created with email and name."""
        from app.models.user import User

        user = User(
            email="r.khalil@opex.com.sa",
            name="Rana Khalil",
            hashed_password="fakehashedpassword",
        )
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.email == "r.khalil@opex.com.sa"
        assert user.name == "Rana Khalil"
        assert user.is_active is True
        assert user.created_at is not None

    def test_user_email_is_unique(self, db_session):
        """Two users cannot have the same email."""
        from app.models.user import User

        user1 = User(email="same@opex.com.sa", name="User 1", hashed_password="x")
        user2 = User(email="same@opex.com.sa", name="User 2", hashed_password="y")
        db_session.add(user1)
        db_session.add(user2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_user_email_is_required(self, db_session):
        """A user cannot be created without an email."""
        from app.models.user import User

        user = User(name="No Email", hashed_password="x")
        db_session.add(user)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_user_is_active_defaults_true(self, db_session):
        """A user defaults to active."""
        from app.models.user import User

        user = User(email="active@test.com", name="Active User", hashed_password="x")
        db_session.add(user)
        db_session.commit()

        assert user.is_active is True

    def test_user_repr(self, db_session):
        """User has a readable string representation."""
        from app.models.user import User

        user = User(email="r.khalil@opex.com.sa", name="Rana Khalil", hashed_password="x")
        assert "r.khalil@opex.com.sa" in repr(user)
