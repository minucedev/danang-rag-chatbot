from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx
from qdrant_client.http.models import PointStruct

from app import config
from app.rag.intent import QueryIntent
from app.utils.slugify_vn import slugify_vn
from app.db.missed_queries import (
    get_pending_queries, mark_resolved, increment_retry, MissedQueryEntity
)

_SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

# Intent → collection để upsert
_INTENT_TO_COLLECTION: dict[str, str] = {
    QueryIntent.HOTEL_SEARCH.value: config.COLLECTION_ACCOMMODATION_HOTELS,
    QueryIntent.RESTAURANT_SEARCH.value: config.COLLECTION_RESTAURANTS,
    QueryIntent.PLACE_SEARCH.value: config.COLLECTION_PLACES,
    QueryIntent.SPECIFIC_SEARCH.value: config.COLLECTION_PLACES,  # fallback
}

# SerpAPI type keyword → collection
_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("hotel", config.COLLECTION_ACCOMMODATION_HOTELS),
    ("resort", config.COLLECTION_ACCOMMODATION_HOTELS),
    ("hostel", config.COLLECTION_ACCOMMODATION_HOTELS),
    ("restaurant", config.COLLECTION_RESTAURANTS),
    ("cafe", config.COLLECTION_RESTAURANTS),
    ("coffee", config.COLLECTION_RESTAURANTS),
    ("food", config.COLLECTION_RESTAURANTS),
    ("eatery", config.COLLECTION_RESTAURANTS),
]

# Queries định kỳ cho new_places_crawl
NEW_PLACES_QUERIES: list[tuple[str, str]] = [
    ("nhà hàng Đà Nẵng", QueryIntent.RESTAURANT_SEARCH.value),
    ("khách sạn Đà Nẵng", QueryIntent.HOTEL_SEARCH.value),
    ("địa điểm du lịch Đà Nẵng", QueryIntent.PLACE_SEARCH.value),
    ("quán cafe Đà Nẵng", QueryIntent.RESTAURANT_SEARCH.value),
]

# Ánh xạ district từ địa chỉ
_DISTRICT_KEYWORDS: list[tuple[str, str]] = [
    ("hai chau", "hai chau"),
    ("son tra", "son tra"),
    ("ngu hanh son", "ngu hanh son"),
    ("cam le", "cam le"),
    ("lien chieu", "lien chieu"),
    ("thanh khe", "thanh khe"),
    ("hoa vang", "hoa vang"),
]


@dataclass
class PlaceCrawlResult:
    inserted: int = 0
    updated: int = 0
    resolved_misses: int = 0
    errors: list[str] = field(default_factory=list)


def _infer_collection_from_type(place_type: str | None) -> str:
    if not place_type:
        return config.COLLECTION_PLACES
    t = place_type.lower()
    for keyword, collection in _TYPE_KEYWORDS:
        if keyword in t:
            return collection
    return config.COLLECTION_PLACES


def _infer_district(address: str | None) -> str | None:
    if not address:
        return None
    slug = slugify_vn(address)
    for keyword_slug, district in _DISTRICT_KEYWORDS:
        if keyword_slug in slug:
            return district
    return None


def _make_point_id(name: str, address: str) -> str:
    """Deterministic UUID từ tên + địa chỉ — stable across re-crawl."""
    raw = f"{name.lower().strip()}|{address.lower().strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _make_content(item: dict) -> str:
    """Tạo text để embed từ dữ liệu SerpAPI local result."""
    name = item.get("title", "")
    place_type = item.get("type", "")
    address = item.get("address", "")
    rating = item.get("rating")
    reviews = item.get("reviews")
    description = item.get("description") or item.get("snippet", "")

    parts = [name]
    if place_type:
        parts.append(f"Loại: {place_type}")
    if address:
        parts.append(f"Địa chỉ: {address}")
    if rating is not None:
        rating_str = f"Đánh giá: {rating:.1f}/5"
        if reviews:
            rating_str += f" ({reviews:,} đánh giá)"
        parts.append(rating_str)
    if description:
        parts.append(description[:400])
    return ". ".join(parts)


async def _fetch_local_results(query: str, num: int = 10) -> list[dict]:
    """Gọi SerpAPI google_local engine cho địa điểm tại Đà Nẵng."""
    if not config.SERPAPI_KEY:
        print("[places-crawler] SERPAPI_KEY not configured — skipping")
        return []
    params = {
        "engine": "google_local",
        "q": query,
        "location": "Da Nang, Vietnam",
        "hl": "vi",
        "gl": "vn",
        "api_key": config.SERPAPI_KEY,
        "num": num,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_SERPAPI_ENDPOINT, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            raise RuntimeError(f"SerpAPI returned HTTP {e.response.status_code}: {body}") from e
        payload = resp.json()
    return payload.get("local_results", [])


def _get_pipeline_components():
    """Lấy encoder và qdrant client từ pipeline instance đã khởi tạo."""
    from app.rag import pipeline as pl_module
    inst = pl_module._pipeline_instance
    if inst is None:
        raise RuntimeError("Pipeline chưa được khởi tạo")
    return inst.encoder, inst.client


async def _upsert_places_to_qdrant(
    items: list[dict],
    collection: str,
    encoder,
    qdrant_client,
) -> tuple[int, int]:
    """Embed và upsert danh sách địa điểm vào một collection Qdrant.
    Trả về (inserted, updated) ước tính dựa trên xem point đã tồn tại chưa.
    """
    if not items:
        return (0, 0)

    loop = asyncio.get_running_loop()

    contents = [_make_content(item) for item in items]
    vectors = await loop.run_in_executor(
        None,
        lambda: encoder.encode(contents, normalize_embeddings=True).tolist(),
    )

    point_ids = [_make_point_id(it.get("title", ""), it.get("address", "")) for it in items]

    # Kiểm tra tồn tại để phân loại inserted vs updated
    try:
        existing_points = await qdrant_client.retrieve(
            collection_name=collection,
            ids=point_ids,
            with_payload=False,
        )
        existing_ids = {str(p.id) for p in existing_points}
    except Exception as exc:
        print(
            f"[places-crawler] retrieve existing IDs failed for '{collection}': "
            f"{type(exc).__name__}: {exc} — counts may be inaccurate"
        )
        existing_ids = set()

    points = []
    for item, vector, pid in zip(items, vectors, point_ids):
        district = _infer_district(item.get("address"))
        raw_rating = item.get("rating")
        # Google Maps dùng thang 5; nhân 2 để về thang 10 (khớp dữ liệu hiện có)
        rating_normalized = round(raw_rating * 2, 1) if raw_rating is not None else None
        payload = {
            "entity_name": item.get("title", ""),
            "place_name": item.get("title", ""),
            "address": item.get("address", ""),
            "district": district or "",
            "rating": rating_normalized,
            "review_count": item.get("reviews"),
            "content": _make_content(item),
            "source": "serpapi_local",
        }
        if item.get("type"):
            payload["restaurant_type"] = item["type"]
        if item.get("phone"):
            payload["phone"] = item["phone"]
        if item.get("website"):
            payload["website"] = item["website"]
        points.append(PointStruct(id=pid, vector=vector, payload=payload))

    await qdrant_client.upsert(collection_name=collection, points=points)

    inserted = sum(1 for pid in point_ids if pid not in existing_ids)
    updated = len(point_ids) - inserted
    return (inserted, updated)


async def run_place_crawl(
    missed_ids: Optional[list[int]] = None,
) -> PlaceCrawlResult:
    """Crawl địa điểm cho danh sách missed_queries IDs.

    Lấy pending queries từ DB, search SerpAPI, upsert Qdrant, cập nhật status.
    """
    result = PlaceCrawlResult()
    print("[places-crawler] starting missed-place crawl")

    try:
        encoder, qdrant_client = _get_pipeline_components()
    except RuntimeError as e:
        result.errors.append(str(e))
        return result

    try:
        if missed_ids is not None:
            all_pending = await get_pending_queries(
                limit=len(missed_ids) + 50, max_retry=config.MAX_PLACE_RETRY
            )
            pending = [q for q in all_pending if q.id in set(missed_ids)]
        else:
            pending = await get_pending_queries(
                limit=config.PLACE_CRAWL_BATCH, max_retry=config.MAX_PLACE_RETRY
            )
    except Exception as exc:
        result.errors.append(f"get_pending_queries failed: {type(exc).__name__}: {exc}")
        return result

    if not pending:
        print("[places-crawler] no pending missed queries")
        return result

    print(f"[places-crawler] processing {len(pending)} missed queries")

    for mq in pending:
        search_q = (mq.rewritten_query or mq.query)
        # Thêm "Đà Nẵng" nếu chưa có để hẹp kết quả địa lý
        if "đà nẵng" not in search_q.lower() and "da nang" not in search_q.lower():
            search_q = f"{search_q} Đà Nẵng"

        intent_str = mq.intent or QueryIntent.PLACE_SEARCH.value
        collection = _INTENT_TO_COLLECTION.get(intent_str, config.COLLECTION_PLACES)

        try:
            items = await _fetch_local_results(search_q, num=5)
            if not items:
                print(f"[places-crawler] no results for '{search_q}' — incrementing retry")
                try:
                    await increment_retry(mq.id, max_retry=config.MAX_PLACE_RETRY)
                except Exception as inc_exc:
                    result.errors.append(
                        f"miss#{mq.id}: increment_retry failed: {type(inc_exc).__name__}: {inc_exc}"
                    )
                continue

            inferred = _infer_collection_from_type(items[0].get("type"))
            if inferred != config.COLLECTION_PLACES:
                collection = inferred

            ins, upd = await _upsert_places_to_qdrant(items, collection, encoder, qdrant_client)
            result.inserted += ins
            result.updated += upd
            result.resolved_misses += 1
            await mark_resolved(mq.id)
            print(f"[places-crawler] resolved miss #{mq.id} '{mq.query}' → {ins}i/{upd}u in {collection}")

        except Exception as exc:
            msg = f"miss#{mq.id} '{mq.query}': {type(exc).__name__}: {exc}"
            print(f"[places-crawler] error — {msg}")
            result.errors.append(msg)
            try:
                await increment_retry(mq.id, max_retry=config.MAX_PLACE_RETRY)
            except Exception as inc_exc:
                result.errors.append(
                    f"miss#{mq.id}: increment_retry failed: {type(inc_exc).__name__}: {inc_exc}"
                )

    return result


async def run_new_places_crawl() -> PlaceCrawlResult:
    """Crawl định kỳ địa điểm mới theo category queries."""
    result = PlaceCrawlResult()
    print("[places-crawler] starting new-places crawl")

    try:
        encoder, qdrant_client = _get_pipeline_components()
    except RuntimeError as e:
        result.errors.append(str(e))
        return result

    for query, intent_str in NEW_PLACES_QUERIES:
        collection = _INTENT_TO_COLLECTION.get(intent_str, config.COLLECTION_PLACES)
        try:
            items = await _fetch_local_results(query, num=20)
            if not items:
                print(f"[places-crawler] no SerpAPI results for '{query}'")
                continue
            ins, upd = await _upsert_places_to_qdrant(items, collection, encoder, qdrant_client)
            result.inserted += ins
            result.updated += upd
            print(f"[places-crawler] '{query}' → {ins}i/{upd}u in {collection}")
        except Exception as exc:
            msg = f"new_places '{query}': {type(exc).__name__}: {exc}"
            print(f"[places-crawler] error — {msg}")
            result.errors.append(msg)

    return result
