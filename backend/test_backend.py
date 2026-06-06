
import asyncio
from app.config import QDRANT_URL, QDRANT_API_KEY
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from app.rag.schemas import SearchResultSchema

async def main():
    client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    res = await client.scroll(
        collection_name='places_danang',
        limit=5
    )
    from app.rag.retrieval import _float, _int, _norm_tags, _bool
    
    for point in res[0]:
        payload = point.payload or {}
        # Simulate retrieval mapping
        init_kwargs = {
            'point_id': str(point.id),
            'collection': 'places_danang',
            'score': 1.0,
            'entity_name': payload.get('entity_name', ''),
            'min_price': _float(payload.get('min_price_vnd') or payload.get('price_min_vnd')),
            'max_price': _float(payload.get('max_price_vnd') or payload.get('price_max_vnd'))
        }
        for k, v in payload.items():
            if k not in ['min_price_vnd', 'max_price_vnd', 'entity_name', 'place_name', 'address', 'content', 'tags']:
                if k not in init_kwargs:
                    init_kwargs[k] = v
        r = SearchResultSchema(**init_kwargs)
        print('Name:', r.entity_name, '| Price:', r.get_price_display())

asyncio.run(main())

