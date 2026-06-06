import asyncio
from app.rag.pipeline import RAGPipeline
from app.db import sessions as db
import app.config as config
from unittest.mock import MagicMock
from dotenv import load_dotenv

load_dotenv()

async def test():
    await db.init_db()
    pl = RAGPipeline.__new__(RAGPipeline)
    from app.rag.llm import load_llm
    pl.llm = load_llm()
    print('Testing Qwen planner (sync)...')
    res = pl._run_itinerary_planner('du lịch Đà Nẵng 3 ngày 2 đêm')
    print('Plan length:', len(res))
    for d in res:
        print('Day:', d.get('day'))

asyncio.run(test())
