
from app.rag.schemas import SearchResultSchema
from app.rag.retrieval import _float

payload = {
    'entity_name': 'Helio Center & Bubble Park',
    'min_price_vnd': None,
    'price_min_vnd': 0,
    'price_avg_vnd': None,
    'price_range_raw': 'Mi?n phí vào; an u?ng 30.000-150.000d',
    'price_level': 'budget'
}
init_kwargs = {
    'point_id': '1',
    'collection': 'places_danang',
    'score': 1.0,
    'entity_name': payload['entity_name'],
    'min_price': _float(payload.get('min_price_vnd') or payload.get('price_min_vnd'))
}
for k, v in payload.items():
    if k not in ['min_price_vnd', 'max_price_vnd', 'entity_name', 'place_name', 'address', 'content', 'tags']:
        if k not in init_kwargs:
            init_kwargs[k] = v

r = SearchResultSchema(**init_kwargs)
print(r.get_price_display())

