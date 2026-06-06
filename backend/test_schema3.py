
from app.rag.schemas import SearchResultSchema
from app.rag.retrieval import _float

payload = {'min_price_vnd': 400000, 'max_price_vnd': 1800000}
min_price = _float(payload.get('min_price_vnd') or payload.get('price_min_vnd'))
max_price = _float(payload.get('max_price_vnd') or payload.get('price_max_vnd'))
r = SearchResultSchema(point_id='1', collection='test', score=1.0, min_price=min_price, max_price=max_price)
print('Hai Anh Quan:', r.get_price_display())

payload2 = {'price_range_raw': '25.000 - 45.000d/to', 'price_min_vnd': 25000, 'price_max_vnd': 45000, 'price_level': 'budget'}
min_price2 = _float(payload2.get('min_price_vnd') or payload2.get('price_min_vnd'))
max_price2 = _float(payload2.get('max_price_vnd') or payload2.get('price_max_vnd'))
r2 = SearchResultSchema(point_id='2', collection='test', score=1.0, min_price=min_price2, max_price=max_price2, price_range_raw=payload2.get('price_range_raw'), price_level=payload2.get('price_level'))
print('Ba Hung:', r2.get_price_display())

