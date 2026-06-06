
from app.rag.schemas import SearchResultSchema
from app.rag.retrieval import _float

# 1. Accommodation
payload1 = {
    'min_price_vnd': 1068797,
    'max_price_vnd': 2466458,
    'price_level': 'mid',
    'price_currency': 'VND'
}
r1 = SearchResultSchema(
    point_id='1', collection='place', score=1.0,
    min_price=_float(payload1.get('min_price_vnd') or payload1.get('price_min_vnd')),
    max_price=_float(payload1.get('max_price_vnd') or payload1.get('price_max_vnd')),
    price_level=payload1.get('price_level')
)
print('Accommodation:', r1.get_price_display())

# 2. dia_diem_du_lich
payload2 = {
    'price_range_raw': '25.000 - 45.000d/tô',
    'price_min_vnd': 25000,
    'price_max_vnd': 45000,
    'price_level': 'budget'
}
r2 = SearchResultSchema(
    point_id='2', collection='place', score=1.0,
    min_price=_float(payload2.get('min_price_vnd') or payload2.get('price_min_vnd')),
    max_price=_float(payload2.get('max_price_vnd') or payload2.get('price_max_vnd')),
    price_range_raw=payload2.get('price_range_raw'),
    price_level=payload2.get('price_level')
)
print('dia_diem_du_lich:', r2.get_price_display())

