"""Pin behavior cho `_violates_dietary` sau khi fix substring false-positive bug.

Regression catchers (cases CŨ trả True nhưng giờ phải False):
- "Bảo tàng Ngà Voi" + chay: 'gà' ở giữa 'ngà' → word boundary chặn.
- "Bò bía chay" + chay: có 'chay' trong tên → trust label.
- "Quán chay BBQ" + chay: có 'chay' → trust label.
"""
from __future__ import annotations

import pytest

from app.rag.recommend import _violates_dietary
from app.rag.schemas import SearchResultSchema


def _r(name: str = "", cuisine: str | None = None, restaurant_type: str | None = None):
    return SearchResultSchema(
        point_id="x",
        collection="restaurants_danang",
        score=0.0,
        entity_name=name,
        cuisine=cuisine,
        restaurant_type=restaurant_type,
    )


def test_returns_false_when_dietary_is_none():
    assert _violates_dietary(_r("Quán Bò Né"), None) is False


def test_returns_false_when_dietary_not_vegetarian():
    assert _violates_dietary(_r("Quán Bò Né"), "halal") is False


def test_flags_meat_for_chay():
    assert _violates_dietary(_r("Quán Bò Né Tư Béo"), "chay") is True


def test_flags_meat_for_vegan_and_vegetarian_keywords():
    # Tất cả 3 keyword đều trigger pattern
    assert _violates_dietary(_r("Quán Bò Né"), "vegan") is True
    assert _violates_dietary(_r("Quán Bò Né"), "VEGETARIAN") is True
    assert _violates_dietary(_r("Quán Bò Né"), "Tôi ăn chay trường") is True


def test_does_not_match_meat_token_inside_other_word():
    # REGRESSION: cũ 'gà' substring-match trong 'ngà' → True. Giờ word-boundary → False.
    assert _violates_dietary(_r("Bảo tàng Ngà Voi"), "chay") is False


def test_chay_in_entity_name_overrides_meat_token():
    # REGRESSION: "Bò bía chay" cũ trả True vì 'bò' khớp. Giờ có \bchay\b → trust label.
    assert _violates_dietary(_r("Bò bía chay Cô Ba"), "chay") is False
    assert _violates_dietary(_r("Quán chay BBQ"), "chay") is False


def test_flags_hai_san():
    assert _violates_dietary(_r("Quán Hải Sản Tươi"), "chay") is True


def test_checks_cuisine_and_restaurant_type_fields():
    assert _violates_dietary(_r(name="", cuisine="Hải sản"), "chay") is True
    assert _violates_dietary(_r(name="", restaurant_type="BBQ"), "chay") is True
