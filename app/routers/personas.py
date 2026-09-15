"""Personas & Test Accounts API router — CRUD for project personas and test accounts."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.project_test_account import ProjectTestAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_persona import UserPersona
from app.permissions import can_manage_project
from app.schemas.persona import (
    PersonaCreate,
    PersonaResponse,
    PersonaUpdate,
    TestAccountCreate,
    TestAccountResponse,
    TestAccountUpdate,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/projects/{project_id}", tags=["personas"])


# ===== Personas =====

@router.get("/personas", response_model=list[PersonaResponse])
def list_personas(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    return db.query(UserPersona).filter(UserPersona.project_id == project_id, UserPersona.tenant_id == current_tenant.id).order_by(UserPersona.name).all()


@router.post("/personas", response_model=PersonaResponse, status_code=201)
def create_persona(project_id: int, persona: PersonaCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_manage_project(current_user, project, db):
        raise HTTPException(status_code=403, detail="Not authorized to manage this project")
    db_persona = UserPersona(project_id=project_id, tenant_id=current_tenant.id, **persona.model_dump(exclude={"project_id"}))
    db.add(db_persona)
    db.commit()
    db.refresh(db_persona)
    return db_persona


@router.put("/personas/{persona_id}", response_model=PersonaResponse)
def update_persona(project_id: int, persona_id: int, persona: PersonaUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    db_persona = db.query(UserPersona).filter(UserPersona.id == persona_id, UserPersona.project_id == project_id, UserPersona.tenant_id == current_tenant.id).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if not can_manage_project(current_user, db_persona.project, db):
        raise HTTPException(status_code=403, detail="Not authorized")
    for k, v in persona.model_dump(exclude_unset=True).items():
        setattr(db_persona, k, v)
    db.commit()
    db.refresh(db_persona)
    return db_persona


@router.delete("/personas/{persona_id}")
def delete_persona(project_id: int, persona_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    db_persona = db.query(UserPersona).filter(UserPersona.id == persona_id, UserPersona.project_id == project_id, UserPersona.tenant_id == current_tenant.id).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if not can_manage_project(current_user, db_persona.project, db):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(db_persona)
    db.commit()
    return {"ok": True}


# ===== Test Accounts =====

@router.get("/test-accounts", response_model=list[TestAccountResponse])
def list_test_accounts(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    return db.query(ProjectTestAccount).filter(ProjectTestAccount.project_id == project_id, ProjectTestAccount.tenant_id == current_tenant.id).order_by(
        ProjectTestAccount.environment, ProjectTestAccount.username
    ).all()


@router.post("/test-accounts", response_model=TestAccountResponse, status_code=201)
def create_test_account(project_id: int, account: TestAccountCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_manage_project(current_user, project, db):
        raise HTTPException(status_code=403, detail="Not authorized to manage this project")
    db_account = ProjectTestAccount(project_id=project_id, tenant_id=current_tenant.id, **account.model_dump(exclude={"project_id"}))
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


@router.put("/test-accounts/{account_id}", response_model=TestAccountResponse)
def update_test_account(project_id: int, account_id: int, account: TestAccountUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    db_account = db.query(ProjectTestAccount).filter(ProjectTestAccount.id == account_id, ProjectTestAccount.project_id == project_id, ProjectTestAccount.tenant_id == current_tenant.id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Test account not found")
    if not can_manage_project(current_user, db_account.project, db):
        raise HTTPException(status_code=403, detail="Not authorized")
    for k, v in account.model_dump(exclude_unset=True).items():
        setattr(db_account, k, v)
    db.commit()
    db.refresh(db_account)
    return db_account


@router.delete("/test-accounts/{account_id}")
def delete_test_account(project_id: int, account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    db_account = db.query(ProjectTestAccount).filter(ProjectTestAccount.id == account_id, ProjectTestAccount.project_id == project_id, ProjectTestAccount.tenant_id == current_tenant.id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Test account not found")
    if not can_manage_project(current_user, db_account.project, db):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(db_account)
    db.commit()
    return {"ok": True}
