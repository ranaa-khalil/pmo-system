"""Test the Client model — TDD RED phase.

This test defines the expected behavior of the Client model before it exists.
"""

import pytest
from sqlalchemy.exc import IntegrityError


class TestClientModel:
    """Tests for the Client model."""

    def test_create_client_with_required_fields(self, db_session):
        """A client can be created with name and contact_email."""
        from app.models.client import Client

        client = Client(
            name="NITC / PNU",
            contact_name="Aldaana Almuqrin",
            contact_email="AEalmuqrin@nitc.sa",
        )
        db_session.add(client)
        db_session.commit()

        assert client.id is not None
        assert client.name == "NITC / PNU"
        assert client.contact_name == "Aldaana Almuqrin"
        assert client.contact_email == "AEalmuqrin@nitc.sa"
        assert client.created_at is not None

    def test_client_name_is_required(self, db_session):
        """A client cannot be created without a name."""
        from app.models.client import Client

        client = Client(contact_email="test@example.com")
        db_session.add(client)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_client_email_is_unique(self, db_session):
        """Two clients cannot have the same contact email."""
        from app.models.client import Client

        client1 = Client(name="Client A", contact_email="same@example.com")
        client2 = Client(name="Client B", contact_email="same@example.com")
        db_session.add(client1)
        db_session.add(client2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_client_has_description_field(self, db_session):
        """A client can have an optional description."""
        from app.models.client import Client

        client = Client(
            name="GO Telecom",
            contact_email="info@go.com.sa",
            description="Saudi telecommunications company",
        )
        db_session.add(client)
        db_session.commit()

        assert client.description == "Saudi telecommunications company"

    def test_client_repr(self, db_session):
        """Client has a readable string representation."""
        from app.models.client import Client

        client = Client(name="NITC / PNU", contact_email="AEalmuqrin@nitc.sa")
        assert "NITC / PNU" in repr(client)
