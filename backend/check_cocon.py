import asyncio
import os
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

load_dotenv()

async def main():
    client = AsyncQdrantClient(os.getenv('QDRANT_URL'), api_key=os.getenv('QDRANT_API_KEY'))
    res = await client.scroll(
        collection_name='places_danang',
        limit=100
    )
    for r in res[0]:
        name = r.payload.get('place_name') or r.payload.get('entity_name') or r.payload.get('display_name')
        if name and 'Chợ Cồn' in name:
            print("time_open:", r.payload.get("time_open"))
            print("time_close:", r.payload.get("time_close"))
            print("opening_hours:", repr(r.payload.get("opening_hours")))
            return

if __name__ == "__main__":
    asyncio.run(main())
