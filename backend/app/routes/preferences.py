from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.backend import current_user
from ..auth.models import User
from ..database import get_db
from ..model import UserPreference
from ..schemas import PreferencesRead, PreferencesUpdate

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesRead)
def read_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PreferencesRead:
    preference = db.get(UserPreference, user.id)
    return PreferencesRead(theme=preference.theme if preference else None)


@router.put("", response_model=PreferencesRead)
def save_preferences(
    payload: PreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PreferencesRead:
    preference = db.get(UserPreference, user.id)
    if preference:
        preference.theme = payload.theme
    else:
        db.add(UserPreference(user_id=user.id, theme=payload.theme))
    db.commit()
    return PreferencesRead(theme=payload.theme)
