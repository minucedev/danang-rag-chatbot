from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/health")
async def health():
    """Quick health check for demo — judges can verify the system is alive."""
    import torch
    from app.rag import pipeline as pl_module

    cuda = torch.cuda.is_available()
    model_name = None
    qdrant_ok = False

    pipeline = getattr(pl_module, "_pipeline_instance", None)
    reranker_ok = False
    if pipeline:
        model_name = type(pipeline.model).__name__
        reranker_ok = pipeline.reranker is not None
        try:
            await pipeline.client.get_collections()
            qdrant_ok = True
        except Exception:
            pass

    return JSONResponse({
        "status": "ok",
        "cuda": cuda,
        "model": model_name,
        "qdrant": "ok" if qdrant_ok else "error",
        "reranker": "ok" if reranker_ok else "not_loaded",
    })
