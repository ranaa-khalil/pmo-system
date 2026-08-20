"""Test the FormTemplate and FormInstance models — TDD RED phase."""
import pytest
from sqlalchemy.exc import IntegrityError


class TestFormTemplateModel:
    """Tests for the FormTemplate model."""

    def test_create_form_template(self, db_session):
        """A form template can be created with a field schema."""
        from app.models.form_template import FormTemplate

        template = FormTemplate(
            name="UAT Sign-off",
            form_type="uat_signoff",
            description="User acceptance testing sign-off form",
            field_schema=[
                {"name": "release_version", "label": "Release Version", "type": "text", "required": True},
                {"name": "tester_name", "label": "Tester Name", "type": "text", "required": True},
                {"name": "test_passed", "label": "All tests passed?", "type": "boolean", "required": True},
            ],
        )
        db_session.add(template)
        db_session.commit()

        assert template.id is not None
        assert template.name == "UAT Sign-off"
        assert len(template.field_schema) == 3

    def test_form_template_name_is_required(self, db_session):
        """Template cannot be created without a name."""
        from app.models.form_template import FormTemplate

        template = FormTemplate(form_type="rca")
        db_session.add(template)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_form_template_type_is_required(self, db_session):
        """Template cannot be created without a form_type."""
        from app.models.form_template import FormTemplate

        template = FormTemplate(name="Test")
        db_session.add(template)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_form_template_repr(self, db_session):
        """Template has a useful repr."""
        from app.models.form_template import FormTemplate
        t = FormTemplate(name="Test", form_type="rca")
        assert "FormTemplate" in repr(t)


class TestFormInstanceModel:
    """Tests for the FormInstance model."""

    def _create_project(self, db_session):
        from app.models.client import Client
        from app.models.project import Project
        c = Client(name="Form Test", contact_email="f@f.sa")
        db_session.add(c)
        db_session.commit()
        p = Project(name="Form Proj", client_id=c.id)
        db_session.add(p)
        db_session.commit()
        return p

    def test_create_form_instance(self, db_session):
        """A form instance can be created from a template."""
        from app.models.form_template import FormTemplate, FormInstance

        p = self._create_project(db_session)
        template = FormTemplate(
            name="Deployment Checklist",
            form_type="deployment_checklist",
            field_schema=[{"name": "version", "label": "Version", "type": "text"}],
        )
        db_session.add(template)
        db_session.commit()

        instance = FormInstance(
            template_id=template.id,
            project_id=p.id,
            data={"version": "1.2.0"},
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.id is not None
        assert instance.status == "Draft"
        assert instance.data["version"] == "1.2.0"

    def test_form_instance_requires_template_id(self, db_session):
        """Instance cannot be created without a template_id."""
        from app.models.form_template import FormInstance
        p = self._create_project(db_session)

        instance = FormInstance(project_id=p.id, data={})
        db_session.add(instance)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_form_instance_requires_project_id(self, db_session):
        """Instance cannot be created without a project_id."""
        from app.models.form_template import FormTemplate, FormInstance

        template = FormTemplate(name="T", form_type="rca", field_schema=[])
        db_session.add(template)
        db_session.commit()

        instance = FormInstance(template_id=template.id, data={})
        db_session.add(instance)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_default_status_is_draft(self, db_session):
        """New form instances default to 'Draft' status."""
        from app.models.form_template import FormTemplate, FormInstance
        p = self._create_project(db_session)
        template = FormTemplate(name="T2", form_type="retrospective", field_schema=[])
        db_session.add(template)
        db_session.commit()

        instance = FormInstance(template_id=template.id, project_id=p.id, data={})
        db_session.add(instance)
        db_session.commit()

        assert instance.status == "Draft"

    def test_form_instance_repr(self, db_session):
        """Instance has a useful repr."""
        from app.models.form_template import FormInstance
        instance = FormInstance(template_id=1, project_id=1, data={})
        assert "FormInstance" in repr(instance)
