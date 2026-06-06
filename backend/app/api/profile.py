from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db import sessions as session_db
from app.db import profiles as profile_db
from app.rag.schemas import UserProfile

router = APIRouter()


async def _owned_or_404(session_id: str, user: dict) -> None:
    if not await session_db.session_owned_by(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found")


@router.get(
    "/api/profile/{session_id}",
    response_model=UserProfile,
    response_model_by_alias=True,
)
async def get_profile(session_id: str, user: dict = Depends(get_current_user)):
    await _owned_or_404(session_id, user)
    profile = await profile_db.get_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put(
    "/api/profile/{session_id}",
    response_model=UserProfile,
    response_model_by_alias=True,
)
async def upsert_profile(session_id: str, profile: UserProfile, user: dict = Depends(get_current_user)):
    await _owned_or_404(session_id, user)
    return await profile_db.upsert_profile(session_id, profile)


@router.delete("/api/profile/{session_id}")
async def delete_profile(session_id: str, user: dict = Depends(get_current_user)):
    await _owned_or_404(session_id, user)
    await profile_db.delete_profile(session_id)
    return {"ok": True}
