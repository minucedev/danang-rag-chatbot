
from app.rag.schemas import SearchResultSchema

def _float(v):
    try:
        return float(v) if v is not None else None
    except:
        return None

payload2 = {'price_range_raw': '50.000 - 100.000d/to', 'price_min_vnd': 50000, 'price_max_vnd': 100000}
min_price2 = _float(payload2.get('min_price_vnd') or payload2.get('price_min_vnd'))
max_price2 = _float(payload2.get('max_price_vnd') or payload2.get('price_max_vnd'))
r2 = SearchResultSchema(point_id='2', collection='place', score=1.0, min_price=min_price2, max_price=max_price2, price_range_raw=payload2.get('price_range_raw'))
print('Result:', r2.get_price_display())

