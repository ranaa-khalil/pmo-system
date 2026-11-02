"""ItemType vocabulary API — tenant-scoped item types with labels and colors.

New tenants are seeded with the standardized vocabulary on first read;
admins can add custom types. backlog_items.item_type stores the key.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.item_type import DEFAULT_ITEM_TYPES, ITEM_TYPE_COLORS, ItemType
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.item_type import ItemTypeCreate, ItemTypeUpdate
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/item-types", tags=["item-types"])


def _seed_if_empty(db: Session, tenant_id: int) -> None:
    """Seed the standardized vocabulary for a tenant with no item types."""
    existing = db.query(ItemType).filter(ItemType.tenant_id == tenant_id).count()
    if existing:
        return
    for order, spec in enumerate(DEFAULT_ITEM_TYPES):
        db.add(ItemType(
            tenant_id=tenant_id,
            key=spec["key"],
            label=spec["label"],
            color=spec["color"],
            sort_order=order,
        ))
    db.commit()


def _payload(t: ItemType) -> dict:
    return {
        "id": t.id,
        "key": t.key,
        "label": t.label,
        "description": t.description,
        "color": t.color,
        "is_active": t.is_active,
        "sort_order": t.sort_order,
    }


@router.get("")
def list_item_types(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The tenant's vocabulary, seeded from the standardized defaults on first read."""
    _seed_if_empty(db, current_tenant.id)
    query = db.query(ItemType).filter(ItemType.tenant_id == current_tenant.id)
    if not include_inactive:
        query = query.filter(ItemType.is_active.is_(True))
    rows = query.order_by(ItemType.sort_order, ItemType.id).all()
    return [_payload(t) for t in rows]


@router.post("", status_code=201)
def create_item_type(
    body: ItemTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Add a custom type to the tenant's vocabulary."""
    _seed_if_empty(db, current_tenant.id)
    key = body.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Type key is required")
    existing = db.query(ItemType).filter(
        ItemType.tenant_id == current_tenant.id, ItemType.key == key
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Type '{key}' already exists")
    if body.color not in ITEM_TYPE_COLORS:
        raise HTTPException(status_code=400, detail=f"color must be one of: {sorted(ITEM_TYPE_COLORS)}")
    row = ItemType(
        tenant_id=current_tenant.id,
        key=key,
        label=body.label.strip(),
        description=body.description,
        color=body.color,
        sort_order=body.sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _payload(row)


@router.put("/{type_id}")
def update_item_type(
    type_id: int,
    body: ItemTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    row = db.query(ItemType).filter(
        ItemType.id == type_id, ItemType.tenant_id == current_tenant.id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item type not found")
    if body.color is not None and body.color not in ITEM_TYPE_COLORS:
        raise HTTPException(status_code=400, detail=f"color must be one of: {sorted(ITEM_TYPE_COLORS)}")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(row, field, val)
    db.commit()
    db.refresh(row)
    return _payload(row)


@router.delete("/{type_id}")
def delete_item_type(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    row = db.query(ItemType).filter(
        ItemType.id == type_id, ItemType.tenant_id == current_tenant.id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item type not found")
    db.delete(row)
    db.commit()
    return {"detail": "Item type deleted"}
