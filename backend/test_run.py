
import asyncio
from app.config import QDRANT_URL, QDRANT_API_KEY
from qdrant_client import AsyncQdrantClient
from app.rag.pipeline import RAGPipeline
from app.rag.llm import QwenHF
from app.rag.encoder import Encoder

async def main():
    client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    encoder = Encoder()
    llm = QwenHF()
    pipeline = RAGPipeline(qdrant_client=client, encoder=encoder, llm=llm)
    
    async for chunk in pipeline.generate('len lich trinh da nang 3 ngay 2 dem', history=[]):
        pass

asyncio.run(main())

