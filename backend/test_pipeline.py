import asyncio
from app.rag.pipeline import RAGPipeline

async def main():
    pipeline = RAGPipeline()
    await pipeline.initialize()
    
    # Simulate itinerary search
    query = "lịch trình du lịch Đà Nẵng 3 ngày 2 đêm tự túc"
    
    print("Executing pipeline search...")
    async for msg in pipeline.search(query, history=[]):
        if msg["type"] == "sources":
            print(f"Found {msg['total']} sources")
            for item in msg["items"][:5]:
                print(f"- {item['entity_name'] or item['place_name']}: min={item.get('min_price')}, max={item.get('max_price')}")
        elif msg["type"] == "done":
            pass

asyncio.run(main())
