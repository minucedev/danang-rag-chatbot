import uuid

from fastapi import APIRouter, HTTPException

from app.db import sessions as session_db
from app.db import profiles as profile_db
from app.rag.recommend import recommend_for_profile
from app.rag.schemas import RecommendRequest, RecommendResponse, UserProfile

router = APIRouter()


def _get_qdrant_client():
    from app.rag import pipeline as pl_module
    # `getattr` để an toàn nếu module chưa hoàn tất import (test fixture có thể hit
    # recommend.py trước khi main.py chạy xong) — chưa ready thì 503.
    pipeline = getattr(pl_module, "_pipeline_instance", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not ready")
    return pipeline.client


@router.post(
    "/api/recommend",
    response_model=RecommendResponse,
    response_model_by_alias=True,
)
async def recommend(req: RecommendRequest):
    session = await session_db.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    profile = await profile_db.get_profile(req.session_id)
    notes_prefix: list[str] = []
    if profile is None:
        profile = UserProfile()
        notes_prefix.append("no_profile")

    client = _get_qdrant_client()
    try:
        response = await recommend_for_profile(
            profile=profile,
            client=client,
            limit=req.limit,
            district=req.district,
            include_hotels=req.include_hotels,
        )
    except Exception as e:
        # Tracked 500: trả về error_id cho user, log đầy đủ type+message phía server.
        err_id = uuid.uuid4().hex[:8]
        print(f"[recommend] error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500, detail=f"recommend failed (id={err_id})"
        )

    if notes_prefix:
        response.notes = notes_prefix + response.notes

    return response
