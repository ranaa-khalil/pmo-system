"""Test the Release model — TDD RED phase."""
from app.models.release import Release, ReleaseItem


class TestReleaseModel:
    """Tests for the Release model."""

    def test_create_release(self, db_session):
        r = Release(project_id=1, version="1.0.0", name="Initial Release",
                     description="First production release")
        db_session.add(r)
        db_session.commit()
        assert r.id is not None
        assert r.version == "1.0.0"
        assert r.status == "Planning"
        assert r.target_date is None
        assert r.release_date is None

    def test_release_status_defaults(self, db_session):
        r = Release(project_id=1, version="0.1.0", name="Alpha")
        db_session.add(r)
        db_session.commit()
        assert r.status == "Planning"

    def test_release_with_dates(self, db_session):
        r = Release(project_id=1, version="2.0.0", name="Major Update",
                     target_date="2026-12-01", release_date="2026-12-15")
        db_session.add(r)
        db_session.commit()
        assert r.target_date == "2026-12-01"
        assert r.release_date == "2026-12-15"


class TestReleaseItemModel:
    """Tests for the ReleaseItem link table."""

    def test_create_release_item_link(self, db_session):
        ri = ReleaseItem(release_id=1, backlog_item_id=1)
        db_session.add(ri)
        db_session.commit()
        assert ri.id is not None
        assert ri.release_id == 1
        assert ri.backlog_item_id == 1

    def test_multiple_items_per_release(self, db_session):
        for i in range(5):
            db_session.add(ReleaseItem(release_id=1, backlog_item_id=i+1))
        db_session.commit()
        items = db_session.query(ReleaseItem).filter(ReleaseItem.release_id == 1).all()
        assert len(items) == 5
