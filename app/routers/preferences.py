"""Per-user UI preferences — GET/PUT /api/me/preferences.

Stores widget order and view modes as JSON strings, one row per user per key
(unique). Keys are allow-listed so the surface stays predictable.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_preference import UserPreference

router = APIRouter(prefix="/api", tags=["preferences"])

# Allow-listed keys — add new surfaces here explicitly
ALLOWED_KEYS = ["dashboard_widgets", "task_view_mode"]


class PreferenceUpdate(BaseModel):
    key: str
    value: object  # any JSON value; stored as a JSON string


@router.get("/me/preferences")
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All preferences for the current user as {key: decoded_value}."""
    rows = db.query(UserPreference).filter(UserPreference.user_id == current_user.id).all()
    result = {}
    for row in rows:
        try:
            result[row.key] = json.loads(row.value) if row.value else None
        except ValueError:
            result[row.key] = row.value
    return result


@router.put("/me/preferences")
def put_preference(
    pref: PreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert one preference. Unknown keys 400; value is stored as JSON."""
    if pref.key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown preference key. Allowed: {ALLOWED_KEYS}")
    row = db.query(UserPreference).filter(
        UserPreference.user_id == current_user.id, UserPreference.key == pref.key
    ).first()
    value_str = json.dumps(pref.value)
    if row:
        row.value = value_str
    else:
        row = UserPreference(user_id=current_user.id, key=pref.key, value=value_str)
        db.add(row)
    db.commit()
    return {"key": pref.key, "value": pref.value}
