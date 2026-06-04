from qdrant_client import QdrantClient
from dotenv import load_dotenv
import os
import json

load_dotenv()
url = os.getenv('QDRANT_URL', 'http://localhost:6333')
api_key = os.getenv('QDRANT_API_KEY')
client = QdrantClient(url=url, api_key=api_key)

targets = [
    "Suối Hoa",
    "Làng Mê",
    "Thác Ba Đờ Phọt"
]

results = []

for coll in ['places_danang', 'restaurants_danang']:
    records = client.scroll(collection_name=coll, limit=1000, with_payload=True)[0]
    for r in records:
        name = r.payload.get("name") or r.payload.get("place_name") or r.payload.get("entity_name") or ""
        for t in targets:
            if t.lower() in name.lower():
                results.append({
                    "collection": coll,
                    "name": name,
                    "rating": r.payload.get("rating"),
                    "min_price": r.payload.get("min_price_vnd"),
                    "max_price": r.payload.get("max_price_vnd")
                })

with open('qdrant_target_prices2.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
