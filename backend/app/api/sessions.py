from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user, owned_session_or_404
from app.db import sessions as db
from app.rag.schemas import SessionEntity, MessageEntity

router = APIRouter()


class RenameBody(BaseModel):
    title: str


@router.get("/api/sessions", response_model=list[SessionEntity])
async def list_sessions(limit: int = 50, offset: int = 0, user: dict = Depends(get_current_user)):
    return await db.list_sessions(user["id"], limit=limit, offset=offset)


@router.post("/api/sessions", response_model=SessionEntity)
async def create_session(body: RenameBody, user: dict = Depends(get_current_user)):
    sid = await db.create_session(body.title, user_id=user["id"])
    return await db.get_session(sid)


@router.get("/api/sessions/{session_id}", response_model=SessionEntity)
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    await owned_session_or_404(session_id, user)
    return await db.get_session(session_id)


@router.get("/api/sessions/{session_id}/messages", response_model=list[MessageEntity])
async def get_messages(session_id: str, user: dict = Depends(get_current_user)):
    await owned_session_or_404(session_id, user)
    return await db.get_messages(session_id)


@router.patch("/api/sessions/{session_id}", response_model=SessionEntity)
async def rename_session(session_id: str, body: RenameBody, user: dict = Depends(get_current_user)):
    await owned_session_or_404(session_id, user)
    await db.rename_session(session_id, body.title)
    return await db.get_session(session_id)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    await owned_session_or_404(session_id, user)
    await db.delete_session(session_id)
    return {"ok": True}
