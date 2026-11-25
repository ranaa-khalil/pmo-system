"""Forms API router — automated form generation from release process templates."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.form_template import FormInstance, FormTemplate
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.forms import (
    FormInstanceCreate,
    FormInstanceResponse,
    FormInstanceUpdate,
    FormInstanceWithTemplateResponse,
    FormTemplateResponse,
)
from app.services.scope import tenant_scoped
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["forms"])


@router.get("/forms/templates", response_model=list[FormTemplateResponse])
def list_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """List all available form templates."""
    templates = tenant_scoped(db, FormTemplate, current_tenant.id).all()
    # If no templates exist yet, seed them
    if not templates:
        from app.services.form_seeds import seed_form_templates
        seed_form_templates(db)
        # Set tenant_id on seeded templates
        db.query(FormTemplate).filter(FormTemplate.tenant_id.is_(None)).update({FormTemplate.tenant_id: current_tenant.id})
        db.commit()
        templates = tenant_scoped(db, FormTemplate, current_tenant.id).all()
    return templates


@router.post("/projects/{project_id}/forms", response_model=FormInstanceResponse, status_code=201)
def create_form_instance(
    project_id: int,
    form: FormInstanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new form instance from a template."""
    if not tenant_scoped(db, Project, current_tenant.id).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if form.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")

    template = tenant_scoped(db, FormTemplate, current_tenant.id).filter(FormTemplate.id == form.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    instance = FormInstance(
        template_id=form.template_id,
        project_id=project_id,
        backlog_item_id=form.backlog_item_id,
        data={},
        created_by=current_user.id,
        tenant_id=current_tenant.id,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


@router.get("/projects/{project_id}/forms", response_model=list[FormInstanceWithTemplateResponse])
def list_project_forms(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all form instances for a project."""
    instances = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.project_id == project_id).all()
    for inst in instances:
        inst.template = tenant_scoped(db, FormTemplate, current_tenant.id).filter(FormTemplate.id == inst.template_id).first()
    return instances


@router.get("/forms/{form_id}", response_model=FormInstanceWithTemplateResponse)
def get_form_instance(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get a form instance with its template."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    instance.template = tenant_scoped(db, FormTemplate, current_tenant.id).filter(FormTemplate.id == instance.template_id).first()
    return instance


@router.put("/forms/{form_id}", response_model=FormInstanceResponse)
def update_form_instance(
    form_id: int,
    form_update: FormInstanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update form field data."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    if form_update.data is not None:
        instance.data = form_update.data
    db.commit()
    db.refresh(instance)
    return instance


@router.post("/forms/{form_id}/submit", response_model=FormInstanceResponse)
def submit_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Submit a form (Draft → Submitted)."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    if instance.status != "Draft":
        raise HTTPException(status_code=400, detail=f"Cannot submit form in '{instance.status}' status")
    instance.status = "Submitted"
    db.commit()
    db.refresh(instance)
    return instance


@router.post("/forms/{form_id}/approve", response_model=FormInstanceResponse)
def approve_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Approve a submitted form (Submitted → Approved)."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    if instance.status != "Submitted":
        raise HTTPException(status_code=400, detail=f"Cannot approve form in '{instance.status}' status")
    instance.status = "Approved"
    db.commit()
    db.refresh(instance)
    return instance


@router.post("/forms/{form_id}/reject", response_model=FormInstanceResponse)
def reject_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Reject a submitted form (Submitted → Rejected)."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    if instance.status not in ("Submitted", "Approved"):
        raise HTTPException(status_code=400, detail=f"Cannot reject form in '{instance.status}' status")
    instance.status = "Rejected"
    db.commit()
    db.refresh(instance)
    return instance


@router.delete("/forms/{form_id}", status_code=204)
def delete_form_instance(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a form instance."""
    instance = tenant_scoped(db, FormInstance, current_tenant.id).filter(FormInstance.id == form_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")
    db.delete(instance)
    db.commit()
