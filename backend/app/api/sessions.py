from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.db import sessions as db
from app.rag.schemas import SessionEntity, MessageEntity

router = APIRouter()


class RenameBody(BaseModel):
    title: str


@router.get("/api/sessions", response_model=list[SessionEntity])
async def list_sessions(limit: int = 50, offset: int = 0):
    return await db.list_sessions(limit=limit, offset=offset)


@router.post("/api/sessions", response_model=SessionEntity)
async def create_session(body: RenameBody):
    sid = await db.create_session(body.title)
    session = await db.get_session(sid)
    return session


@router.get("/api/sessions/{session_id}", response_model=SessionEntity)
async def get_session(session_id: str):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/api/sessions/{session_id}/messages", response_model=list[MessageEntity])
async def get_messages(session_id: str):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return await db.get_messages(session_id)


@router.patch("/api/sessions/{session_id}", response_model=SessionEntity)
async def rename_session(session_id: str, body: RenameBody):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.rename_session(session_id, body.title)
    return await db.get_session(session_id)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete_session(session_id)
    return {"ok": True}
