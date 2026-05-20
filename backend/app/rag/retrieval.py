from __future__ import annotations
import asyncio
import time
from typing import List, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer

from app import config
from app.rag.intent import QueryIntent, CollectionRegistry
from app.rag.schemas import SearchResultSchema
from app.utils.nfc import normalize_nfc
from app.utils.slugify_vn import slugify_vn

# Per-request parent entity cache — reset between pipeline instances
_parent_cache: dict[str, dict] = {}


async def _fetch_parent_entity(
    parent_id: str,
    collection_name: str,
    client: AsyncQdrantClient,
) -> Optional[dict]:
    if not parent_id or parent_id in ("None", "", "null"):
        return None
    if parent_id in _parent_cache:
        return _parent_cache[parent_id]

    if "accommodation" in collection_name or "hotel" in collection_name:
        parent_col = config.COLLECTION_ACCOMMODATION_HOTELS
    elif "restaurant" in collection_name:
        parent_col = config.COLLECTION_RESTAURANTS
    elif "place" in collection_name:
        parent_col = config.COLLECTION_PLACES
    else:
        return None

    try:
        points = await client.retrieve(
            collection_name=parent_col,
            ids=[parent_id],
            with_payload=True,
        )
        if points:
            p = points[0].payload or {}
            result = {
                "name": p.get("entity_name") or p.get("place_name"),
                "rating": p.get("rating"),
                "address": p.get("address"),
                "district": p.get("district"),
            }
            _parent_cache[parent_id] = result
            return result
    except Exception:
        pass
    return None


def _norm_tags(v):
    if v is None:
        return None
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [t.strip() for t in v.split(";") if t.strip()]
    return None


def _build_filter(filters: Optional[dict]) -> Optional[Filter]:
    if not filters:
        return None
    conditions = []
    if filters.get("district"):
        slug = slugify_vn(filters["district"])
        conditions.append(FieldCondition(key="district", match=MatchValue(value=slug)))
    if filters.get("min_rating"):
        conditions.append(FieldCondition(key="rating", range=Range(gte=float(filters["min_rating"]))))
    if filters.get("max_price"):
        conditions.append(FieldCondition(key="min_price_vnd", range=Range(lte=float(filters["max_price"]))))
    if filters.get("min_price"):
        conditions.append(FieldCondition(key="min_price_vnd", range=Range(gte=float(filters["min_price"]))))
    return Filter(must=conditions) if conditions else None


async def retrieve_from_collection(
    collection_name: str,
    query_vector: List[float],
    client: AsyncQdrantClient,
    top_k: int = 5,
    filters: Optional[dict] = None,
    score_threshold: float = 0.3,
) -> List[SearchResultSchema]:
    try:
        q_filter = _build_filter(filters)
        result = await client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=q_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        points = result.points if hasattr(result, "points") else result

        results = []
        for point in points:
            score = point.score if hasattr(point, "score") else 0.0
            if score < score_threshold:
                continue
            payload = point.payload or {}

            # Lọc thủ công (Đã tối ưu hóa logic khoảng giá)
            skip = False
            if filters:
                min_price = payload.get("min_price_vnd")
                max_price = payload.get("max_price_vnd")

                # CHẶN TRẦN GIÁ (max_price)
                if filters.get("max_price"):
                    # Nếu giá thấp nhất của quán còn cao hơn cả mức khách chịu chi -> LOẠI thẳng
                    if min_price and min_price > filters["max_price"]:
                        skip = True
                        print(f"  [DEBUG] {collection_name}: LOẠI {payload.get('entity_name') or payload.get('place_name')} - giá thấp nhất {min_price:,.0f} > trần {filters['max_price']:,.0f}")
                    # [NÂNG CẤP AN TOÀN]: Nếu quán có giá tối đa vượt quá 1.5 lần mức khách muốn,
                    # cũng loại luôn để tránh giới thiệu những nơi quá đắt đỏ so với túi tiền của họ.
                    elif max_price and max_price > (filters["max_price"] * 1.5):
                        skip = True
                        print(f"  [DEBUG] {collection_name}: LOẠI {payload.get('entity_name') or payload.get('place_name')} - giá cao nhất {max_price:,.0f} quá cao so với trần {filters['max_price']:,.0f}")

                # CHẶN SÀN GIÁ (min_price)
                if filters.get("min_price") and not skip:
                    # Nếu có giá cao nhất mà giá cao nhất lại thấp hơn mức sàn khách yêu cầu -> LOẠI
                    if max_price and max_price < filters["min_price"]:
                        skip = True
                    # Hoặc nếu không có giá cao nhất, nhưng giá thấp nhất thấp hơn mức sàn -> LOẠI
                    elif min_price and min_price < filters["min_price"]:
                        skip = True

            if skip:
                continue

            def _float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            def _int(v):
                try:
                    return int(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            r = SearchResultSchema(
                point_id=str(point.id),
                collection=collection_name,
                score=score,
                entity_name=payload.get("entity_name", ""),
                place_name=payload.get("place_name", ""),
                district=payload.get("district", ""),
                rating=_float(payload.get("rating")),
                min_price=_float(payload.get("min_price_vnd")),
                max_price=_float(payload.get("max_price_vnd")),
                address=payload.get("address", ""),
                content=payload.get("content", ""),
                parent_entity_name=payload.get("parent_entity_name"),
                parent_entity_id=payload.get("parent_entity_id"),
                room_name=payload.get("room_name"),
                capacity=_int(payload.get("capacity")),
                bed_type=payload.get("bed_type"),
                area_m2=_float(payload.get("area_m2")),
                room_view=payload.get("room_view"),
                cuisine=payload.get("cuisine"),
                restaurant_type=payload.get("restaurant_type"),
                check_in_time=payload.get("check_in_time"),
                check_out_time=payload.get("check_out_time"),
                time_open=payload.get("time_open"),
                time_close=payload.get("time_close"),
                tags=_norm_tags(payload.get("tags")),
                review_count=_int(payload.get("review_count")),
                star_rating=_float(payload.get("star_rating")),
                price_level=payload.get("price_level"),
                price_currency=payload.get("price_currency"),
            )

            # Enrich reviews with parent entity data
            review_collections = {
                config.COLLECTION_ACCOMMODATION_REVIEWS,
                config.COLLECTION_RESTAURANT_REVIEWS,
                config.COLLECTION_PLACE_REVIEWS,
            }
            if collection_name in review_collections:
                parent = await _fetch_parent_entity(r.parent_entity_id or "", collection_name, client)
                if parent:
                    if parent.get("name") and parent["name"] not in ("None", "", "null"):
                        r.parent_entity_name = parent["name"]
                    r.parent_rating = _float(parent.get("rating"))
                    if parent.get("address"):
                        r.parent_address = parent["address"]
                    if parent.get("district") and not r.district:
                        r.district = parent["district"]

            results.append(r)
        return results

    except Exception as e:
        print(f"Warning: retrieve_from_collection({collection_name}): {e}")
        return []


async def retrieve_by_intent(
    query: str,
    client: AsyncQdrantClient,
    encoder: SentenceTransformer,
    intent: Optional[QueryIntent] = None,
    top_k_per_collection: int = 5,
    max_total: int = 20,
    filters: Optional[dict] = None,
    score_threshold: float = 0.3,
) -> List[SearchResultSchema]:
    q = normalize_nfc(query)
    # Filter/giá suy luận đã do LLMQueryAnalyzer lo (pipeline truyền `filters`).
    if intent is None:
        intent = QueryIntent.GENERAL

    collections = CollectionRegistry.get_collections_by_intent(intent)

    # Encode in executor (SentenceTransformer.encode is synchronous)
    loop = asyncio.get_running_loop()
    t_enc_start = time.perf_counter()
    query_vector: List[float] = await loop.run_in_executor(
        None,
        lambda: encoder.encode([q], normalize_embeddings=True)[0].tolist(),
    )
    t_enc = time.perf_counter()
    print(f"[TIMING]   encoder.encode: {(t_enc - t_enc_start)*1000:.0f}ms "
          f"(device={getattr(encoder, 'device', 'unknown')})")

    # Retrieve from all collections in parallel
    tasks = [
        retrieve_from_collection(col, query_vector, client, top_k_per_collection, filters, score_threshold)
        for col in collections
    ]
    t_qd_start = time.perf_counter()
    results_nested = await asyncio.gather(*tasks)
    t_qd = time.perf_counter()
    total_hits = sum(len(b) for b in results_nested)
    print(f"[TIMING]   qdrant.gather: {(t_qd - t_qd_start)*1000:.0f}ms "
          f"({len(collections)} cols, {total_hits} raw hits)")

    # Flatten + dedup by (collection, point_id)
    seen: set[tuple[str, str]] = set()
    all_results: List[SearchResultSchema] = []
    for batch in results_nested:
        for r in batch:
            key = (r.collection, r.point_id)
            if key not in seen:
                seen.add(key)
                all_results.append(r)

    # Fallback price filter: Qdrant Range silently skips records lacking the field.
    # Asymmetry is intentional: an unknown price passes max_price (don't hide a
    # possibly-cheap-enough result) but fails min_price (can't confirm the floor).
    # Defense-in-depth trên manual skip ở từng collection — vẫn enforce min_price.
    fdict = filters or {}
    max_p = fdict.get("max_price")
    if max_p is not None:
        all_results = [r for r in all_results if r.min_price is None or r.min_price <= max_p]

    min_p = fdict.get("min_price")
    if min_p is not None:
        all_results = [r for r in all_results if r.min_price is not None and r.min_price >= min_p]

    return all_results[:max_total]
