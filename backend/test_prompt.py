
from app.rag.pipeline import _build_messages, QueryIntent, SearchResultSchema
import json

results = [
    SearchResultSchema(id='1', collection='restaurant', payload={'restaurant_name': 'Sushi Boat', 'address': '60 Ung Van Khiem', 'price_level': None}),
    SearchResultSchema(id='2', collection='place', payload={'place_name': 'C?u Sông Hàn', 'address': 'Sông Hàn', 'min_price_vnd': None})
]
messages = _build_messages('Lên l?ch trình 2 ngày dà n?ng', results, [], QueryIntent.ITINERARY_SEARCH)
for m in messages:
    print('ROLE:', m['role'])
    print(m['content'])
    print('---')

