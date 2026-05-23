from fastapi import APIRouter, HTTPException

from app.db import sessions as session_db
from app.db import profiles as profile_db
from app.rag.schemas import UserProfile

router = APIRouter()


@router.get(
    "/api/profile/{session_id}",
    response_model=UserProfile,
    response_model_by_alias=True,
)
async def get_profile(session_id: str):
    profile = await profile_db.get_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put(
    "/api/profile/{session_id}",
    response_model=UserProfile,
    response_model_by_alias=True,
)
async def upsert_profile(session_id: str, profile: UserProfile):
    session = await session_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return await profile_db.upsert_profile(session_id, profile)


@router.delete("/api/profile/{session_id}")
async def delete_profile(session_id: str):
    await profile_db.delete_profile(session_id)
    return {"ok": True}
