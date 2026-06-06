
import asyncio
from app.config import QDRANT_URL, QDRANT_API_KEY
from qdrant_client import AsyncQdrantClient
from app.rag.retrieval import retrieve_by_intent
from app.rag.intent import QueryIntent

async def main():
    client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    
    # Mock search
    res = await retrieve_by_intent(
        qdrant_client=client,
        query='Hai Anh Quan',
        intent=QueryIntent.RESTAURANT_SEARCH,
        filters=None,
        limit=2
    )
    from app.rag.pipeline import _format_context
    print('Context:')
    print(_format_context(res))

asyncio.run(main())

