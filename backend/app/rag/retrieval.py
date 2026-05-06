from __future__ import annotations
import asyncio
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
                tags=payload.get("tags"),
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
    if intent is None:
        intent = QueryIntent.detect(q)

    collections = CollectionRegistry.get_collections_by_intent(intent)

    # Encode in executor (SentenceTransformer.encode is synchronous)
    loop = asyncio.get_running_loop()
    query_vector: List[float] = await loop.run_in_executor(
        None,
        lambda: encoder.encode([q], normalize_embeddings=True)[0].tolist(),
    )

    # Retrieve from all collections in parallel
    tasks = [
        retrieve_from_collection(col, query_vector, client, top_k_per_collection, filters, score_threshold)
        for col in collections
    ]
    results_nested = await asyncio.gather(*tasks)

    # Flatten + dedup by (collection, point_id)
    seen: set[tuple[str, str]] = set()
    all_results: List[SearchResultSchema] = []
    for batch in results_nested:
        for r in batch:
            key = (r.collection, r.point_id)
            if key not in seen:
                seen.add(key)
                all_results.append(r)

    return all_results[:max_total]
