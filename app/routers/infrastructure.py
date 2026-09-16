"""Infrastructure management router — environments, secrets, assets, services, databases."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.infrastructure import (
    Asset,
    Environment,
    InfraDatabase,
    InfraService,
    Secret,
    SecretAccessLog,
    SecretVersion,
)
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.encryption import decrypt_value, encrypt_value
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["infrastructure"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_secret_access(db: Session, secret_id: int, user_id: int, action: str, request: Request = None):
    """Log a secret access event."""
    log = SecretAccessLog(
        secret_id=secret_id,
        user_id=user_id,
        action=action,
        ip_address=request.client.host if request and request.client else None,
    )
    db.add(log)
    db.commit()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/overview")
def get_infra_overview(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get infrastructure overview dashboard data."""
    tid = current_tenant.id

    env_count = db.query(Environment).filter(Environment.tenant_id == tid).count()
    secret_count = db.query(Secret).filter(Secret.tenant_id == tid).count()
    asset_count = db.query(Asset).filter(Asset.tenant_id == tid).count()
    service_count = db.query(InfraService).filter(InfraService.tenant_id == tid).count()
    db_count = db.query(InfraDatabase).filter(InfraDatabase.tenant_id == tid).count()

    # Expiring secrets (within 30 days)
    thirty_days = datetime.now(timezone.utc) + timedelta(days=30)
    expiring = (
        db.query(Secret)
        .filter(
            Secret.tenant_id == tid,
            Secret.expires_at.isnot(None),
            Secret.expires_at <= thirty_days,
        )
        .all()
    )

    # Recent activity (last 10 secret access logs)
    recent_logs = (
        db.query(SecretAccessLog)
        .join(Secret, SecretAccessLog.secret_id == Secret.id)
        .filter(Secret.tenant_id == tid)
        .order_by(SecretAccessLog.timestamp.desc())
        .limit(10)
        .all()
    )

    # Distributions
    assets_by_type = {}
    for a in db.query(Asset).filter(Asset.tenant_id == tid).all():
        assets_by_type[a.asset_type] = assets_by_type.get(a.asset_type, 0) + 1

    secrets_by_category = {}
    for s in db.query(Secret).filter(Secret.tenant_id == tid).all():
        secrets_by_category[s.category] = secrets_by_category.get(s.category, 0) + 1

    return {
        "counts": {
            "environments": env_count,
            "secrets": secret_count,
            "assets": asset_count,
            "services": service_count,
            "databases": db_count,
        },
        "expiring_secrets": [s.to_dict() for s in expiring],
        "recent_activity": [
            {
                **log.to_dict(),
                "secret_name": db.query(Secret).filter(Secret.id == log.secret_id).first().name
                if db.query(Secret).filter(Secret.id == log.secret_id).first()
                else "deleted",
            }
            for log in recent_logs
        ],
        "assets_by_type": assets_by_type,
        "secrets_by_category": secrets_by_category,
    }


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/environments")
def list_environments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all environments for the current tenant."""
    envs = db.query(Environment).filter(Environment.tenant_id == current_tenant.id).order_by(Environment.name).all()
    return [e.to_dict() for e in envs]


@router.post("/projects/{project_id}/infra/environments")
def create_environment(
    project_id: int,
    env: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new environment."""
    e = Environment(
        tenant_id=current_tenant.id,
        name=env.get("name", ""),
        type=env.get("type", "development"),
        url=env.get("url"),
        description=env.get("description"),
        owner_id=env.get("owner_id"),
        status=env.get("status", "active"),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e.to_dict()


@router.put("/infra/environments/{env_id}")
def update_environment(
    env_id: int,
    env: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update an environment."""
    e = db.query(Environment).filter(
        Environment.id == env_id, Environment.tenant_id == current_tenant.id
    ).first()
    if not e:
        raise HTTPException(status_code=404, detail="Environment not found")
    for field in ["name", "type", "url", "description", "owner_id", "status"]:
        if field in env:
            setattr(e, field, env[field])
    db.commit()
    db.refresh(e)
    return e.to_dict()


@router.delete("/infra/environments/{env_id}")
def delete_environment(
    env_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete an environment."""
    e = db.query(Environment).filter(
        Environment.id == env_id, Environment.tenant_id == current_tenant.id
    ).first()
    if not e:
        raise HTTPException(status_code=404, detail="Environment not found")
    db.delete(e)
    db.commit()
    return {"message": "Environment deleted"}


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/secrets")
def list_secrets(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all secrets for the current tenant (values always masked)."""
    secrets = db.query(Secret).filter(Secret.tenant_id == current_tenant.id).order_by(Secret.name).all()
    return [s.to_dict() for s in secrets]


@router.post("/projects/{project_id}/infra/secrets")
def create_secret(
    project_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new secret. The value is encrypted before storage."""
    if not body.get("value"):
        raise HTTPException(status_code=400, detail="Secret value is required")
    s = Secret(
        tenant_id=current_tenant.id,
        name=body.get("name", ""),
        category=body.get("category", "custom"),
        environment_id=body.get("environment_id"),
        encrypted_value=encrypt_value(body["value"]),
        description=body.get("description"),
        owner_id=body.get("owner_id", current_user.id),
        status="active",
        expires_at=body.get("expires_at"),
        version=1,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    # Create version 1
    sv = SecretVersion(
        secret_id=s.id, version=1,
        encrypted_value=s.encrypted_value,
        created_by=current_user.id,
    )
    db.add(sv)
    db.commit()

    _log_secret_access(db, s.id, current_user.id, "create", request)
    return s.to_dict()


@router.put("/infra/secrets/{secret_id}")
def update_secret(
    secret_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a secret. If value is changed, a new version is created."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")

    for field in ["name", "category", "environment_id", "description", "owner_id", "status", "expires_at"]:
        if field in body:
            setattr(s, field, body[field])

    # If a new value is provided, encrypt and create a new version
    if body.get("value"):
        s.encrypted_value = encrypt_value(body["value"])
        s.version += 1
        sv = SecretVersion(
            secret_id=s.id, version=s.version,
            encrypted_value=s.encrypted_value,
            created_by=current_user.id,
        )
        db.add(sv)

    db.commit()
    db.refresh(s)
    _log_secret_access(db, s.id, current_user.id, "update", request)
    return s.to_dict()


@router.delete("/infra/secrets/{secret_id}")
def delete_secret(
    secret_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a secret."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")
    _log_secret_access(db, s.id, current_user.id, "delete", request)
    db.delete(s)
    db.commit()
    return {"message": "Secret deleted"}


@router.get("/infra/secrets/{secret_id}/reveal")
def reveal_secret(
    secret_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Reveal a secret's decrypted value. Always logged."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")
    _log_secret_access(db, s.id, current_user.id, "reveal", request)
    return {"value": decrypt_value(s.encrypted_value), "version": s.version}


@router.post("/infra/secrets/{secret_id}/rotate")
def rotate_secret(
    secret_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Rotate a secret — saves old version, creates new version with new value."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")
    if not body.get("value"):
        raise HTTPException(status_code=400, detail="New value is required")

    s.encrypted_value = encrypt_value(body["value"])
    s.version += 1
    s.status = "active"
    sv = SecretVersion(
        secret_id=s.id, version=s.version,
        encrypted_value=s.encrypted_value,
        created_by=current_user.id,
    )
    db.add(sv)
    db.commit()
    db.refresh(s)
    _log_secret_access(db, s.id, current_user.id, "rotate", request)
    return s.to_dict()


@router.get("/infra/secrets/{secret_id}/versions")
def list_secret_versions(
    secret_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List version history for a secret."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")
    versions = (
        db.query(SecretVersion)
        .filter(SecretVersion.secret_id == secret_id)
        .order_by(SecretVersion.version.desc())
        .all()
    )
    return [v.to_dict() for v in versions]


@router.post("/infra/secrets/{secret_id}/rollback")
def rollback_secret(
    secret_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Rollback a secret to a previous version."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")

    target_version = body.get("version")
    if not target_version:
        raise HTTPException(status_code=400, detail="Target version is required")

    sv = db.query(SecretVersion).filter(
        SecretVersion.secret_id == secret_id,
        SecretVersion.version == target_version,
    ).first()
    if not sv:
        raise HTTPException(status_code=404, detail="Version not found")

    # Rollback: create a new version with the old value
    s.encrypted_value = sv.encrypted_value
    s.version += 1
    new_sv = SecretVersion(
        secret_id=s.id, version=s.version,
        encrypted_value=s.encrypted_value,
        created_by=current_user.id,
    )
    db.add(new_sv)
    db.commit()
    db.refresh(s)
    _log_secret_access(db, s.id, current_user.id, "rollback", request)
    return s.to_dict()


@router.get("/infra/secrets/{secret_id}/audit")
def get_secret_audit(
    secret_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get the access audit log for a secret."""
    s = db.query(Secret).filter(
        Secret.id == secret_id, Secret.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Secret not found")
    logs = (
        db.query(SecretAccessLog)
        .filter(SecretAccessLog.secret_id == secret_id)
        .order_by(SecretAccessLog.timestamp.desc())
        .limit(50)
        .all()
    )
    # Enrich with user names
    result = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        result.append({
            **log.to_dict(),
            "user_name": user.name if user else "unknown",
        })
    return result


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/assets")
def list_assets(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all assets for the current tenant."""
    assets = db.query(Asset).filter(Asset.tenant_id == current_tenant.id).order_by(Asset.name).all()
    return [a.to_dict() for a in assets]


@router.post("/projects/{project_id}/infra/assets")
def create_asset(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new asset."""
    import json
    a = Asset(
        tenant_id=current_tenant.id,
        name=body.get("name", ""),
        asset_type=body.get("asset_type", "other"),
        environment_id=body.get("environment_id"),
        project_id=body.get("project_id"),
        owner_id=body.get("owner_id", current_user.id),
        team=body.get("team"),
        status=body.get("status", "active"),
        metadata_json=json.dumps(body.get("metadata", {})) if body.get("metadata") else None,
        cost_monthly=body.get("cost_monthly"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.to_dict()


@router.put("/infra/assets/{asset_id}")
def update_asset(
    asset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update an asset."""
    a = db.query(Asset).filter(
        Asset.id == asset_id, Asset.tenant_id == current_tenant.id
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Asset not found")
    import json
    for field in ["name", "asset_type", "environment_id", "project_id", "owner_id", "team", "status", "cost_monthly"]:
        if field in body:
            setattr(a, field, body[field])
    if "metadata" in body:
        a.metadata_json = json.dumps(body["metadata"])
    db.commit()
    db.refresh(a)
    return a.to_dict()


@router.delete("/infra/assets/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete an asset."""
    a = db.query(Asset).filter(
        Asset.id == asset_id, Asset.tenant_id == current_tenant.id
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.delete(a)
    db.commit()
    return {"message": "Asset deleted"}


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/services")
def list_services(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all services for the current tenant."""
    services = db.query(InfraService).filter(InfraService.tenant_id == current_tenant.id).order_by(InfraService.name).all()
    return [s.to_dict() for s in services]


@router.post("/projects/{project_id}/infra/services")
def create_service(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new service."""
    import json
    s = InfraService(
        tenant_id=current_tenant.id,
        name=body.get("name", ""),
        service_type=body.get("service_type", "internal"),
        environment_id=body.get("environment_id"),
        owner_id=body.get("owner_id", current_user.id),
        status=body.get("status", "active"),
        documentation_url=body.get("documentation_url"),
        linked_secret_ids=json.dumps(body.get("linked_secret_ids", [])) if body.get("linked_secret_ids") else None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s.to_dict()


@router.put("/infra/services/{service_id}")
def update_service(
    service_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a service."""
    s = db.query(InfraService).filter(
        InfraService.id == service_id, InfraService.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Service not found")
    import json
    for field in ["name", "service_type", "environment_id", "owner_id", "status", "documentation_url"]:
        if field in body:
            setattr(s, field, body[field])
    if "linked_secret_ids" in body:
        s.linked_secret_ids = json.dumps(body["linked_secret_ids"])
    db.commit()
    db.refresh(s)
    return s.to_dict()


@router.delete("/infra/services/{service_id}")
def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a service."""
    s = db.query(InfraService).filter(
        InfraService.id == service_id, InfraService.tenant_id == current_tenant.id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Service not found")
    db.delete(s)
    db.commit()
    return {"message": "Service deleted"}


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/infra/databases")
def list_databases(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all databases for the current tenant."""
    databases = db.query(InfraDatabase).filter(InfraDatabase.tenant_id == current_tenant.id).order_by(InfraDatabase.name).all()
    return [d.to_dict() for d in databases]


@router.post("/projects/{project_id}/infra/databases")
def create_database(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new database record."""
    import json
    d = InfraDatabase(
        tenant_id=current_tenant.id,
        name=body.get("name", ""),
        db_type=body.get("db_type", "postgresql"),
        host=body.get("host"),
        port=body.get("port"),
        environment_id=body.get("environment_id"),
        owner_id=body.get("owner_id", current_user.id),
        backup_policy=body.get("backup_policy"),
        linked_secret_ids=json.dumps(body.get("linked_secret_ids", [])) if body.get("linked_secret_ids") else None,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d.to_dict()


@router.put("/infra/databases/{db_id}")
def update_database(
    db_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a database record."""
    d = db.query(InfraDatabase).filter(
        InfraDatabase.id == db_id, InfraDatabase.tenant_id == current_tenant.id
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Database not found")
    import json
    for field in ["name", "db_type", "host", "port", "environment_id", "owner_id", "backup_policy"]:
        if field in body:
            setattr(d, field, body[field])
    if "linked_secret_ids" in body:
        d.linked_secret_ids = json.dumps(body["linked_secret_ids"])
    db.commit()
    db.refresh(d)
    return d.to_dict()


@router.delete("/infra/databases/{db_id}")
def delete_database(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a database record."""
    d = db.query(InfraDatabase).filter(
        InfraDatabase.id == db_id, InfraDatabase.tenant_id == current_tenant.id
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Database not found")
    db.delete(d)
    db.commit()
    return {"message": "Database deleted"}
