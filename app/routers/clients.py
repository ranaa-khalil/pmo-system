"""Clients API router — CRUD endpoints with hierarchical RBAC."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.client import Client
from app.models.tenant import Tenant
from app.models.user import User
from app.permissions import can_assign_am, can_create_client, can_manage_client, get_visible_clients
from app.schemas.client import ClientCreate, ClientResponse, ClientUpdate
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.post("", response_model=ClientResponse, status_code=201)
def create_client(client: ClientCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Create a new client (super admin, tenant owner, or tenant admin)."""
    if not can_create_client(current_user, db):
        raise HTTPException(status_code=403, detail="You don't have permission to create clients")
    from app.services.usage_service import check_quota, METRIC_CLIENTS
    check_quota(db, current_tenant, METRIC_CLIENTS)
    db_client = Client(
        name=client.name,
        contact_name=client.contact_name,
        contact_email=client.contact_email,
        description=client.description,
        tenant_id=current_tenant.id,
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.get("", response_model=list[ClientResponse])
def list_clients(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """List clients visible to the current user."""
    return get_visible_clients(current_user, db, tenant_id=current_tenant.id)


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Get a specific client by ID."""
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.put("/{client_id}", response_model=ClientResponse)
def update_client(client_id: int, client_update: ClientUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Update a client (super admin, tenant owner/admin, or assigned AM)."""
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not can_manage_client(current_user, client, db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage this client")
    update_data = client_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


@router.put("/{client_id}/account-manager", response_model=ClientResponse)
def assign_account_manager(
    client_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Assign an account manager to a client (super admin, tenant owner/admin, or current AM)."""
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not can_assign_am(current_user, client, db):
        raise HTTPException(status_code=403, detail="You don't have permission to assign an account manager")
    am_id = data.get("account_manager_id")
    if am_id:
        am = db.query(User).filter(User.id == am_id, User.tenant_id == current_tenant.id).first()
        if not am:
            raise HTTPException(status_code=404, detail="User not found")
        am.system_role = "account_manager"
    client.account_manager_id = am_id
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Delete a client (super admin, tenant owner, or tenant admin)."""
    if not can_create_client(current_user, db):
        raise HTTPException(status_code=403, detail="You don't have permission to delete clients")
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
