
from app.rag.schemas import SearchResultSchema
r4 = SearchResultSchema(point_id='4', collection='place', score=1.0, price_level='')
print('price_level is:', r4.price_level)
print('getattr:', getattr(r4, 'price_level', None))
print('get_price_display:', r4.get_price_display())

