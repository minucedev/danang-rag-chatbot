from __future__ import annotations
import asyncio
import re
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


def _parse_number_token(token: str) -> Optional[float]:
    raw = token.strip()
    if not raw:
        return None

    # Handle common VN/EN numeric formats: 1.000.000 / 1,000,000 / 1,2
    if "." in raw and "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1 or raw.count(",") > 1:
        raw = raw.replace(".", "").replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")

    try:
        return float(raw)
    except ValueError:
        return None


def _extract_max_price_from_query(query: str) -> Optional[float]:
    """Extract upper budget (VND) from phrases like 'dưới 1 triệu', '< 1tr'."""
    q = normalize_nfc(query).lower()

    pattern = re.compile(
        r"(?:duoi|dưới|<|<=|khong\s+qua|không\s+quá|toi\s+da|tối\s+đa|max|tro\s+xuong|trở\s+xuống)\s*"
        r"([0-9]+(?:[\.,][0-9]+)*)\s*"
        r"(trieu|triệu|tr|m|nghin|nghìn|ngan|ngàn|k)?"
    )
    m = pattern.search(q)
    if not m:
        return None

    value = _parse_number_token(m.group(1))
    if value is None:
        return None

    unit = (m.group(2) or "").strip()
    if unit in {"trieu", "triệu", "tr", "m"}:
        return value * 1_000_000
    if unit in {"nghin", "nghìn", "ngan", "ngàn", "k"}:
        return value * 1_000

    # No explicit unit: if big enough, assume already VND.
    if value >= 100_000:
        return value
    return None


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

    effective_filters = dict(filters or {})
    detected_max_price = _extract_max_price_from_query(q)
    if detected_max_price is not None:
        current_max = effective_filters.get("max_price")
        if current_max is None:
            effective_filters["max_price"] = detected_max_price
        else:
            effective_filters["max_price"] = min(float(current_max), detected_max_price)

    # District/rating auto-detected from free text are SOFT signals only —
    # applied via rerank district/rating boosts, not as hard Qdrant filters.
    # Only explicit sidebar filters (in `filters`) hard-filter here.

    collections = CollectionRegistry.get_collections_by_intent(intent)

    # Encode in executor (SentenceTransformer.encode is synchronous)
    loop = asyncio.get_running_loop()
    query_vector: List[float] = await loop.run_in_executor(
        None,
        lambda: encoder.encode([q], normalize_embeddings=True)[0].tolist(),
    )

    # Retrieve from all collections in parallel
    tasks = [
        retrieve_from_collection(col, query_vector, client, top_k_per_collection, effective_filters, score_threshold)
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

    # Fallback price filter: Qdrant Range silently skips records lacking the field.
    # Asymmetry is intentional: an unknown price passes max_price (don't hide a
    # possibly-cheap-enough result) but fails min_price (can't confirm the floor).
    max_p = effective_filters.get("max_price")
    if max_p is not None:
        all_results = [r for r in all_results if r.min_price is None or r.min_price <= max_p]

    min_p = effective_filters.get("min_price")
    if min_p is not None:
        all_results = [r for r in all_results if r.min_price is not None and r.min_price >= min_p]

    return all_results[:max_total]
