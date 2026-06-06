"""Ingest CSV crawl → Qdrant (UPSERT, không recreate).

Port từ qdrant-etl.ipynb (helpers + build_* + ensure/upsert), chỉnh:
- recreate=False (chỉ tạo collection khi thiếu, KHÔNG xoá → giữ places/dữ liệu cũ);
- đọc CSV từ backend/crawl_data/{foody,traveloka,booking};
- embed bge-m3 (lazy, CPU); Qdrant client sync.
Phạm vi: restaurants (Foody) + accommodation hotels/rooms/reviews (Traveloka+Booking).
"""
from __future__ import annotations
import hashlib
import logging
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, PayloadSchemaType, PointStruct, VectorParams,
)

from app.crawl_admin import config

_ws_re = re.compile(r"\s+")
_embedder = None


# ─── Helpers (port từ notebook ETL qdrant-etl.ipynb của người dùng) ───────────
def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text).strip()
    text = unicodedata.normalize("NFKC", text)
    return _ws_re.sub(" ", text)


def strip_accents(text):
    text = clean_text(text).replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_key(text):
    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return _ws_re.sub(" ", s).strip()


def stable_uuid(parts):
    raw = "||".join([clean_text(p) for p in parts])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest))


def safe_float(v):
    try:
        return None if pd.isna(v) else float(v)
    except Exception:
        return None


def safe_int(v):
    try:
        return None if pd.isna(v) else int(float(v))
    except Exception:
        return None


def parse_price_number(v):
    if pd.isna(v):
        return None
    s = re.sub(r"[^0-9]", "", clean_text(v))
    try:
        return int(s) if s else None
    except Exception:
        return None


def price_level_hotel(min_price_vnd):
    if min_price_vnd is None:
        return "unknown"
    if min_price_vnd < 400_000:
        return "budget"
    if min_price_vnd < 1_200_000:
        return "mid"
    if min_price_vnd < 3_000_000:
        return "high"
    return "luxury"


def price_level_place(min_price_vnd):
    if min_price_vnd is None:
        return "unknown"
    if min_price_vnd < 50_000:
        return "budget"
    if min_price_vnd < 200_000:
        return "mid"
    if min_price_vnd < 500_000:
        return "high"
    return "luxury"


def parse_datetime(value, dayfirst=False):
    if pd.isna(value):
        return None, None
    dt = pd.to_datetime(value, errors="coerce", utc=True, dayfirst=dayfirst)
    if pd.isna(dt):
        return None, None
    return dt.isoformat(), int(dt.timestamp())


_DISTRICTS = ["hai chau", "son tra", "thanh khe", "ngu hanh son", "cam le", "hoa vang", "lien chieu"]


def extract_district(address_text, fallback_district=""):
    if clean_text(fallback_district):
        return normalize_key(fallback_district)
    s = normalize_key(address_text)
    for d in _DISTRICTS:
        if d in s:
            return d
    return ""


def _norm_col_name(name):
    return re.sub(r"[\s_]+", "", str(name).strip().lower())


def resolve_col(df, candidates, required=False):
    norm_to_real = {_norm_col_name(c): c for c in df.columns}
    for c in candidates:
        hit = norm_to_real.get(_norm_col_name(c))
        if hit is not None:
            return hit
    if required:
        raise KeyError(f"Missing column {candidates}; have {list(df.columns)}")
    return None


def dedupe_docs(docs):
    seen, out = set(), []
    for d in docs:
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        out.append(d)
    return out


# ─── Builders (port) ──────────────────────────────────────────────────────────
def build_restaurant_entities(df):
    docs = []
    c_name = resolve_col(df, ["Name", "name", "place_name"])
    c_address = resolve_col(df, ["Address", "address"])
    c_avg = resolve_col(df, ["Avg Score", "avg_score"])
    c_price_score = resolve_col(df, ["Price score", "price_score"])
    c_quality = resolve_col(df, ["Quality score", "quality_score"])
    c_service = resolve_col(df, ["Service score", "service_score"])
    c_space = resolve_col(df, ["Space score", "space_score"])
    c_location = resolve_col(df, ["Location score", "location_score"])
    c_total = resolve_col(df, ["Total review", "total_review", "review_count"])
    c_cuisine = resolve_col(df, ["Cuisine", "cuisine"])
    c_type = resolve_col(df, ["Type", "type"])
    c_open = resolve_col(df, ["Time open", "time_open"])
    c_close = resolve_col(df, ["Time close", "time_close"])
    c_pmin = resolve_col(df, ["Price min", "price_min"])
    c_pmax = resolve_col(df, ["Price max", "price_max"])
    c_category = resolve_col(df, ["Category", "category"])
    c_url = resolve_col(df, ["URL", "url"])
    c_pavg = resolve_col(df, ["Price avg", "price_avg"])

    for row in df.to_dict("records"):
        name = clean_text(row.get(c_name, "")) if c_name else ""
        if not name:
            continue
        source_url = clean_text(row.get(c_url, "")) if c_url else ""
        address = clean_text(row.get(c_address, "")) if c_address else ""
        min_price = parse_price_number(row.get(c_pmin, None)) if c_pmin else None
        max_price = parse_price_number(row.get(c_pmax, None)) if c_pmax else None
        avg_rating = safe_float(row.get(c_avg, None)) if c_avg else None

        entity_id = (stable_uuid(["restaurant_entity", source_url]) if source_url
                     else stable_uuid(["restaurant_entity", normalize_key(name), normalize_key(address)]))
        text = clean_text(
            f"Nha hang: {name}. Dia chi: {address}. "
            f"Danh gia TB: {avg_rating}. Gia min: {min_price}. Gia max: {max_price}. "
            f"Cuisine: {clean_text(row.get(c_cuisine, '')) if c_cuisine else ''}. "
            f"Loai: {clean_text(row.get(c_type, '')) if c_type else ''}."
        )
        if len(text) < 20:
            continue
        payload = {
            "domain": "restaurant", "source_type": "restaurant_entity",
            "source_platform": "foody_dataset", "entity_name": name, "place_name": name,
            "source_place_id": source_url, "source_url": source_url, "address": address,
            "district": extract_district(address), "rating": avg_rating,
            "price_score": safe_float(row.get(c_price_score, None)) if c_price_score else None,
            "quality_score": safe_float(row.get(c_quality, None)) if c_quality else None,
            "service_score": safe_float(row.get(c_service, None)) if c_service else None,
            "space_score": safe_float(row.get(c_space, None)) if c_space else None,
            "location_score": safe_float(row.get(c_location, None)) if c_location else None,
            "review_count": safe_int(row.get(c_total, None)) if c_total else None,
            "cuisine": clean_text(row.get(c_cuisine, "")) if c_cuisine else "",
            "restaurant_type": clean_text(row.get(c_type, "")) if c_type else "",
            "time_open": clean_text(row.get(c_open, "")) if c_open else "",
            "time_close": clean_text(row.get(c_close, "")) if c_close else "",
            "min_price_vnd": min_price, "max_price_vnd": max_price,
            "price_avg_vnd": parse_price_number(row.get(c_pavg, None)) if c_pavg else None,
            "price_level": price_level_place(min_price),
            "category": clean_text(row.get(c_category, "")) if c_category else "",
        }
        docs.append({"id": entity_id, "text": text, "payload": payload})
    return dedupe_docs(docs)


def build_restaurant_reviews(df, url_to_entity):
    """Review nhà hàng (Foody) → docs. Link parent qua url_to_entity (url → entity_id)."""
    docs = []
    if df.empty:
        return docs
    c_url = resolve_col(df, ["url", "URL"])
    c_user = resolve_col(df, ["username", "reviewer_name", "author"])
    c_score = resolve_col(df, ["score", "rating", "review_rating"])
    c_content = resolve_col(df, ["clean_content", "content", "review_text"])
    c_time_raw = resolve_col(df, ["time", "review_time"])
    c_time_parsed = resolve_col(df, ["parsed_time", "review_date"])
    c_recency = resolve_col(df, ["recency_score"])
    if c_content is None:
        return docs
    for row in df.to_dict("records"):
        text = clean_text(row.get(c_content, ""))
        if len(text) < 8:
            continue
        source_url = clean_text(row.get(c_url, "")) if c_url else ""
        parent_id = url_to_entity.get(source_url) if source_url else None
        if not parent_id:
            continue
        user = clean_text(row.get(c_user, "")) if c_user else ""
        time_raw = clean_text(row.get(c_time_raw, "")) if c_time_raw else ""
        time_val = row.get(c_time_parsed, None) if c_time_parsed else row.get(c_time_raw, None)
        iso_dt, unix_ts = parse_datetime(time_val, dayfirst=True)
        doc_id = stable_uuid(["restaurant_review", source_url, user, time_raw, text[:120]])
        payload = {
            "domain": "restaurant", "source_type": "restaurant_review",
            "source_platform": "foody_dataset", "parent_entity_id": parent_id,
            "source_place_id": source_url, "author": user,
            "rating": safe_float(row.get(c_score, None)) if c_score else None,
            "timestamp_raw": time_raw, "timestamp_norm": iso_dt, "timestamp_unix": unix_ts,
            "recency_score": safe_float(row.get(c_recency, None)) if c_recency else None,
        }
        docs.append({"id": doc_id, "text": text, "payload": payload})
    return dedupe_docs(docs)


def build_image_summary(df):
    if df.empty:
        return {}
    c_hotel = resolve_col(df, ["hotel_id"])
    c_url = resolve_col(df, ["image_url", "url"])
    if not c_hotel or not c_url:
        return {}
    out = {}
    for row in df.to_dict("records"):
        hid, url = clean_text(row.get(c_hotel, "")), clean_text(row.get(c_url, ""))
        if not hid or not url:
            continue
        hit = out.setdefault(hid, {"image_count": 0, "sample_image_urls": []})
        hit["image_count"] += 1
        if len(hit["sample_image_urls"]) < 3:
            hit["sample_image_urls"].append(url)
    return out


def build_policy_summary(df):
    if df.empty:
        return {}
    c_hotel = resolve_col(df, ["hotel_id"])
    c_ptype = resolve_col(df, ["policy_type"])
    c_pval = resolve_col(df, ["policy_value"])
    if not c_hotel or not c_ptype or not c_pval:
        return {}
    out = {}
    for row in df.to_dict("records"):
        hid = clean_text(row.get(c_hotel, ""))
        ptype = normalize_key(row.get(c_ptype, ""))
        pval = clean_text(row.get(c_pval, ""))[:600]
        if not hid or not ptype or not pval:
            continue
        out.setdefault(hid, {}).setdefault(ptype, pval)
    return out


def build_price_summaries(df):
    hotel_summary, room_summary = {}, {}
    if df.empty:
        return hotel_summary, room_summary
    c_hotel = resolve_col(df, ["hotel_id"])
    c_room = resolve_col(df, ["room_id"])
    c_price = resolve_col(df, ["price"])
    c_cur = resolve_col(df, ["currency"])
    c_date = resolve_col(df, ["date"])
    c_disc = resolve_col(df, ["is_discount"])
    if not c_hotel or not c_price:
        return hotel_summary, room_summary
    for row in df.to_dict("records"):
        hid = clean_text(row.get(c_hotel, ""))
        rid = clean_text(row.get(c_room, "")) if c_room else ""
        price = parse_price_number(row.get(c_price, None))
        if not hid or price is None:
            continue
        iso_dt, unix_ts = parse_datetime(row.get(c_date, None)) if c_date else (None, None)
        currency = clean_text(row.get(c_cur, "VND")) if c_cur else "VND"
        disc = (clean_text(row.get(c_disc, "")) if c_disc else "").lower() in {"true", "1", "yes"}
        h = hotel_summary.setdefault(hid, {
            "min_price_vnd": price, "max_price_vnd": price, "price_currency": currency,
            "price_snapshot_date": iso_dt, "price_snapshot_unix": unix_ts, "has_discount": disc})
        h["min_price_vnd"] = min(h["min_price_vnd"], price)
        h["max_price_vnd"] = max(h["max_price_vnd"], price)
        if iso_dt and (h.get("price_snapshot_unix") is None or unix_ts > h.get("price_snapshot_unix", 0)):
            h["price_snapshot_date"], h["price_snapshot_unix"] = iso_dt, unix_ts
        h["has_discount"] = h["has_discount"] or disc
        if rid:
            r = room_summary.setdefault(f"{hid}::{rid}", {
                "min_price_vnd": price, "max_price_vnd": price, "price_currency": currency})
            r["min_price_vnd"] = min(r["min_price_vnd"], price)
            r["max_price_vnd"] = max(r["max_price_vnd"], price)
    return hotel_summary, room_summary


def build_room_stats(df):
    stats = {}
    if df.empty:
        return stats
    c_hotel = resolve_col(df, ["hotel_id"])
    c_cap = resolve_col(df, ["capacity"])
    if not c_hotel:
        return stats
    for row in df.to_dict("records"):
        hid = clean_text(row.get(c_hotel, ""))
        if not hid:
            continue
        cap = safe_int(row.get(c_cap, None)) if c_cap else None
        hit = stats.setdefault(hid, {"room_count": 0, "max_capacity": None})
        hit["room_count"] += 1
        if cap is not None:
            hit["max_capacity"] = cap if hit["max_capacity"] is None else max(hit["max_capacity"], cap)
    return stats


def build_hotels(df, img_sum, pol_sum, price_sum, room_stats):
    docs, hotel_to_entity = [], {}
    c_hotel = resolve_col(df, ["hotel_id"])
    c_name = resolve_col(df, ["name"])
    c_rating = resolve_col(df, ["rating"])
    c_review = resolve_col(df, ["review_count"])
    c_prop = resolve_col(df, ["property_type", "category"])
    c_addr = resolve_col(df, ["full_address", "address"])
    c_link = resolve_col(df, ["link", "website"])
    c_desc = resolve_col(df, ["description"])
    c_star = resolve_col(df, ["star_rating"])
    for row in df.to_dict("records"):
        hid = clean_text(row.get(c_hotel, "")) if c_hotel else ""
        name = clean_text(row.get(c_name, "")) if c_name else ""
        if not hid or not name:
            continue
        p = price_sum.get(hid, {})
        img = img_sum.get(hid, {})
        pol = pol_sum.get(hid, {})
        rs = room_stats.get(hid, {})
        address = clean_text(row.get(c_addr, "")) if c_addr else ""
        rating = safe_float(row.get(c_rating, None)) if c_rating else None
        entity_id = stable_uuid(["accommodation_hotel", hid])
        text = clean_text(
            f"Khach san: {name}. Dia chi: {address}. Danh gia: {rating}. "
            f"So phong: {rs.get('room_count')}. Gia thap nhat: {p.get('min_price_vnd')}. "
            f"Loai gia: {price_level_hotel(p.get('min_price_vnd'))}. "
            f"Mo ta: {clean_text(row.get(c_desc, '')) if c_desc else ''}")
        if len(text) < 20:
            continue
        payload = {
            "domain": "accommodation", "source_type": "accommodation_hotel",
            "source_platform": "travel_dataset", "entity_name": name, "place_name": name,
            "source_place_id": hid, "category": clean_text(row.get(c_prop, "")) if c_prop else "",
            "address": address, "district": extract_district(address), "rating": rating,
            "review_count": safe_int(row.get(c_review, None)) if c_review else None,
            "star_rating": safe_float(row.get(c_star, None)) if c_star else None,
            "link": clean_text(row.get(c_link, "")) if c_link else "",
            "min_price_vnd": p.get("min_price_vnd"), "max_price_vnd": p.get("max_price_vnd"),
            "price_level": price_level_hotel(p.get("min_price_vnd")),
            "price_currency": p.get("price_currency"),
            "price_snapshot_date": p.get("price_snapshot_date"),
            "price_snapshot_unix": p.get("price_snapshot_unix"), "has_discount": p.get("has_discount"),
            "room_count": rs.get("room_count"), "max_capacity": rs.get("max_capacity"),
            "image_count": img.get("image_count", 0), "sample_image_urls": img.get("sample_image_urls", []),
            "check_in_time": pol.get("check in time") or pol.get("check_in_time"),
            "check_out_time": pol.get("check out time") or pol.get("check_out_time"),
            "cancellation_policy": pol.get("cancellation policy") or pol.get("cancellation_policy"),
            "children_policy": pol.get("children policy") or pol.get("children_policy"),
        }
        docs.append({"id": entity_id, "text": text, "payload": payload})
        hotel_to_entity[hid] = entity_id
    return dedupe_docs(docs), hotel_to_entity


def build_rooms(df, hotel_to_entity, room_price):
    docs = []
    if df.empty:
        return docs
    c_room = resolve_col(df, ["room_id"])
    c_hotel = resolve_col(df, ["hotel_id"])
    c_name = resolve_col(df, ["room_name", "name"])
    c_cap = resolve_col(df, ["capacity"])
    c_bed = resolve_col(df, ["bed_type"])
    c_area = resolve_col(df, ["area"])
    c_view = resolve_col(df, ["view"])
    c_amen = resolve_col(df, ["amenities_room", "amenities"])
    if c_hotel is None:
        return docs
    for row in df.to_dict("records"):
        hid = clean_text(row.get(c_hotel, ""))
        parent_id = hotel_to_entity.get(hid)
        if not parent_id:
            continue
        room_name = clean_text(row.get(c_name, "")) if c_name else ""
        rid = clean_text(row.get(c_room, "")) if c_room else ""
        if not room_name:
            continue
        p = room_price.get(f"{hid}::{rid}", {})
        doc_id = stable_uuid(["accommodation_room", hid, rid])
        text = clean_text(
            f"Phong: {room_name}. Suc chua: {safe_int(row.get(c_cap, None)) if c_cap else None}. "
            f"Loai giuong: {clean_text(row.get(c_bed, '')) if c_bed else ''}. "
            f"Dien tich: {safe_float(row.get(c_area, None)) if c_area else None} m2. "
            f"Huong phong: {clean_text(row.get(c_view, '')) if c_view else ''}. "
            f"Gia thap nhat: {p.get('min_price_vnd')}.")
        payload = {
            "domain": "accommodation", "source_type": "accommodation_room",
            "source_platform": "travel_dataset", "parent_entity_id": parent_id,
            "source_place_id": hid, "source_room_id": rid, "room_name": room_name,
            "capacity": safe_int(row.get(c_cap, None)) if c_cap else None,
            "bed_type": clean_text(row.get(c_bed, "")) if c_bed else "",
            "area_m2": safe_float(row.get(c_area, None)) if c_area else None,
            "room_view": clean_text(row.get(c_view, "")) if c_view else "",
            "amenities_room": clean_text(row.get(c_amen, ""))[:1200] if c_amen else "",
            "min_price_vnd": p.get("min_price_vnd"), "max_price_vnd": p.get("max_price_vnd"),
            "price_level": price_level_hotel(p.get("min_price_vnd")), "price_currency": p.get("price_currency"),
        }
        docs.append({"id": doc_id, "text": text, "payload": payload})
    return dedupe_docs(docs)


def build_acc_reviews(df, hotel_to_entity):
    docs = []
    if df.empty:
        return docs
    c_rid = resolve_col(df, ["review_id"])
    c_hotel = resolve_col(df, ["hotel_id"])
    c_reviewer = resolve_col(df, ["reviewer_name", "author"])
    c_text = resolve_col(df, ["review_text", "text", "review_content"])
    c_rating = resolve_col(df, ["review_rating", "rating"])
    c_date = resolve_col(df, ["review_date", "date"])
    if c_text is None or c_hotel is None:
        return docs
    for row in df.to_dict("records"):
        text = clean_text(row.get(c_text, ""))
        if len(text) < 10:
            continue
        hid = clean_text(row.get(c_hotel, ""))
        parent_id = hotel_to_entity.get(hid)
        if not parent_id:
            continue
        rid = clean_text(row.get(c_rid, "")) if c_rid else ""
        reviewer = clean_text(row.get(c_reviewer, "")) if c_reviewer else ""
        rdate = clean_text(row.get(c_date, "")) if c_date else ""
        iso_dt, unix_ts = parse_datetime(row.get(c_date, None)) if c_date else (None, None)
        doc_id = stable_uuid(["accommodation_review", hid, rid, reviewer, rdate, text[:120]])
        payload = {
            "domain": "accommodation", "source_type": "accommodation_review",
            "source_platform": "travel_dataset", "parent_entity_id": parent_id,
            "source_place_id": hid, "source_review_id": rid, "author": reviewer,
            "rating": safe_float(row.get(c_rating, None)) if c_rating else None,
            "timestamp_raw": rdate, "timestamp_norm": iso_dt, "timestamp_unix": unix_ts,
        }
        docs.append({"id": doc_id, "text": text, "payload": payload})
    return dedupe_docs(docs)


# ─── Qdrant ops ───────────────────────────────────────────────────────────────
def ensure_collection(client, name, vector_size, recreate=False):
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def ensure_payload_indexes(client, name):
    plan = [
        ("rating", PayloadSchemaType.FLOAT), ("min_price_vnd", PayloadSchemaType.INTEGER),
        ("max_price_vnd", PayloadSchemaType.INTEGER), ("timestamp_unix", PayloadSchemaType.INTEGER),
        ("district", PayloadSchemaType.KEYWORD), ("price_level", PayloadSchemaType.KEYWORD),
        ("source_type", PayloadSchemaType.KEYWORD), ("parent_entity_id", PayloadSchemaType.KEYWORD),
        ("star_rating", PayloadSchemaType.FLOAT),
    ]
    for field, schema in plan:
        try:
            client.create_payload_index(collection_name=name, field_name=field, field_schema=schema, wait=True)
        except Exception as exc:
            msg = str(exc).lower()
            # "đã tồn tại" là bình thường (idempotent); lỗi khác (type conflict, auth) cần thấy.
            if "already exists" not in msg and "conflict" not in msg and "same name" not in msg:
                print(f"[ingest] index {name}.{field} lỗi: {type(exc).__name__}: {exc}")


def upsert_docs(client, name, embedder, docs, log, batch_size=64, encode_batch=32):
    """Upsert docs vào Qdrant. Khi OOM thì giảm encode_batch_size rồi retry. Dọn GC mỗi batch.
    Một batch lỗi (encode non-OOM, hoặc upsert) được log và BỎ QUA — không làm hỏng cả collection."""
    import gc
    if not docs:
        return 0
    total = 0
    failed = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        texts = [d["text"] for d in batch]
        try:
            vectors = embedder.encode(texts, normalize_embeddings=True,
                                      show_progress_bar=False, batch_size=min(encode_batch, len(texts)))
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and encode_batch > 8:
                smaller = max(8, encode_batch // 2)
                log(f"  ⚠ OOM khi encode {name} — retry với encode_batch={smaller}")
                return total + upsert_docs(
                    client, name, embedder, docs[i:], log,
                    batch_size=batch_size, encode_batch=smaller,
                )
            failed += len(batch)
            log(f"  ⚠ Bỏ batch {name}[{i}:{i+len(batch)}] — encode lỗi: {type(e).__name__}: {e}")
            gc.collect()
            continue
        except Exception as e:
            failed += len(batch)
            log(f"  ⚠ Bỏ batch {name}[{i}:{i+len(batch)}] — encode lỗi: {type(e).__name__}: {e}")
            gc.collect()
            continue
        try:
            points = [PointStruct(id=d["id"], vector=v.tolist(),
                                  payload={**d["payload"], "content": d["text"]})
                      for d, v in zip(batch, vectors)]
            client.upsert(collection_name=name, points=points)
            total += len(points)
            log(f"  {name}: {total}/{len(docs)}")
        except Exception as e:
            failed += len(batch)
            log(f"  ⚠ Bỏ batch {name}[{i}:{i+len(batch)}] — upsert lỗi: {type(e).__name__}: {e}")
        finally:
            gc.collect()
    if failed:
        log(f"  ⚠ {name}: {failed}/{len(docs)} doc bị bỏ do lỗi batch (collection vẫn upsert phần còn lại)")
    return total


def _read_csv(path: Path) -> pd.DataFrame:
    """Đọc CSV. File KHÔNG tồn tại → DataFrame rỗng (bỏ qua êm). File tồn tại nhưng đọc
    LỖI → raise (để run bị đánh dấu 'error' thay vì im lặng mất cả 1 collection)."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip", engine="python")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except Exception as exc:
        raise RuntimeError(f"Đọc {path.name} lỗi: {type(exc).__name__}: {exc}") from exc


def _concat(dirs: list[str], fname: str) -> pd.DataFrame:
    frames = [_read_csv(Path(d) / fname) for d in dirs]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def set_shared_embedder(model) -> None:
    """App chính inject embedder BGE-M3 đã nạp sẵn để KHÔNG nạp model lần 2 (~2GB RAM)."""
    global _embedder
    _embedder = model


def _get_embedder():
    """Ưu tiên: (1) embedder được inject/cache; (2) embedder của RAGPipeline đang chạy
    (khi crawl-admin chạy chung process với chatbot); (3) fallback nạp mới cho test/CLI."""
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        import app.rag.pipeline as pl_module
        pipeline = getattr(pl_module, "_pipeline_instance", None)
        if pipeline is not None and getattr(pipeline, "encoder", None) is not None:
            _embedder = pipeline.encoder
            return _embedder
    except Exception as exc:
        # Không nuốt im lặng: nếu tra encoder của pipeline lỗi thì bước fallback dưới sẽ
        # nạp BGE-M3 lần 2 (~2GB) — đúng thứ merge muốn tránh. Log để còn lần ra.
        logging.warning("[crawl-admin] tra shared embedder lỗi: %s: %s",
                        type(exc).__name__, exc)
    # Trong process backend đã gộp, set_shared_embedder() chạy lúc startup nên KHÔNG bao giờ
    # tới đây. Tới đây = (CLI/test) hoặc misconfig → cảnh báo vì sắp nạp model thứ 2.
    logging.warning("[crawl-admin] chưa có shared embedder — nạp MỚI %s (~2GB CPU). "
                    "Trong backend gộp điều này không nên xảy ra (kiểm tra set_shared_embedder).",
                    config.EMBED_MODEL_NAME)
    from sentence_transformers import SentenceTransformer
    _embedder = SentenceTransformer(config.EMBED_MODEL_NAME, device="cpu")
    return _embedder


def run_ingest_blocking(log: Callable[[str], None]) -> dict:
    """Chạy SYNC (trong thread). log(line) để stream tiến độ. Trả {collection: count}."""
    if not config.QDRANT_URL:
        raise RuntimeError("Thiếu QDRANT_URL (đặt trong backend/.env).")
    log("Nạp embedder bge-m3 (CPU, có thể vài chục giây)…")
    embedder = _get_embedder()
    vec_size = embedder.get_sentence_embedding_dimension()
    log(f"Kết nối Qdrant ({config.QDRANT_URL[:40]}…)")
    client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, timeout=120)
    recreate = config.INGEST_RECREATE
    counts: dict = {}
    try:
        # ── Restaurants (Foody) ──
        df_r = _read_csv(Path(config.DATA_FOODY) / "restaurant_detail.csv")
        if not df_r.empty:
            docs = build_restaurant_entities(df_r)
            ensure_collection(client, config.COLLECTION_RESTAURANTS, vec_size, recreate)
            ensure_payload_indexes(client, config.COLLECTION_RESTAURANTS)
            counts[config.COLLECTION_RESTAURANTS] = upsert_docs(
                client, config.COLLECTION_RESTAURANTS, embedder, docs, log, config.INGEST_BATCH)
            log(f"Nhà hàng: {counts[config.COLLECTION_RESTAURANTS]} doc")

            # ── Restaurant reviews (Foody) — link parent qua url của entity vừa build ──
            url_to_entity = {
                d["payload"]["source_url"]: d["id"]
                for d in docs if d["payload"].get("source_url")
            }
            # Ưu tiên reviews_cleaned.csv (đã tiền xử lý), fallback reviews_output.csv
            _rv_cleaned = Path(config.DATA_FOODY) / "reviews_cleaned.csv"
            _rv_raw = Path(config.DATA_FOODY) / "reviews_output.csv"
            _rv_path = _rv_cleaned if _rv_cleaned.exists() else _rv_raw
            df_rv = _read_csv(_rv_path)
            if df_rv.empty:
                log("Không có reviews CSV — bỏ qua review nhà hàng.")
            elif not url_to_entity:
                # CSV có dữ liệu nhưng không nhà hàng nào có URL để liên kết → log đúng nguyên nhân
                log(f"Có {len(df_rv)} dòng review nhưng không nhà hàng nào có URL để liên kết — bỏ qua.")
            else:
                rv_docs = build_restaurant_reviews(df_rv, url_to_entity)
                ensure_collection(client, config.COLLECTION_RESTAURANT_REVIEWS, vec_size, recreate)
                ensure_payload_indexes(client, config.COLLECTION_RESTAURANT_REVIEWS)
                counts[config.COLLECTION_RESTAURANT_REVIEWS] = upsert_docs(
                    client, config.COLLECTION_RESTAURANT_REVIEWS, embedder, rv_docs, log, config.INGEST_BATCH)
                # log cả số dòng CSV để thấy ngay nếu phần lớn review bị loại (orphan/ngắn)
                log(f"Review nhà hàng: {counts[config.COLLECTION_RESTAURANT_REVIEWS]} doc (từ {len(df_rv)} dòng CSV)")
        else:
            log("Không có restaurant_detail.csv — bỏ qua nhà hàng.")

        # ── Accommodation (Traveloka + Booking) ──
        dirs = [config.DATA_TRAVELOKA, config.DATA_BOOKING]
        df_hotels = _concat(dirs, "hotels.csv")
        if not df_hotels.empty:
            img = build_image_summary(_concat(dirs, "images.csv"))
            pol = build_policy_summary(_concat(dirs, "policies.csv"))
            hotel_price, room_price = build_price_summaries(_concat(dirs, "prices.csv"))
            df_rooms = _concat(dirs, "rooms.csv")
            room_stats = build_room_stats(df_rooms)
            hotel_docs, hotel_to_entity = build_hotels(df_hotels, img, pol, hotel_price, room_stats)
            room_docs = build_rooms(df_rooms, hotel_to_entity, room_price)
            review_docs = build_acc_reviews(_concat(dirs, "reviews.csv"), hotel_to_entity)
            for col, docs in [
                (config.COLLECTION_ACCOMMODATION_HOTELS, hotel_docs),
                (config.COLLECTION_ACCOMMODATION_ROOMS, room_docs),
                (config.COLLECTION_ACCOMMODATION_REVIEWS, review_docs),
            ]:
                ensure_collection(client, col, vec_size, recreate)
                ensure_payload_indexes(client, col)
                counts[col] = upsert_docs(client, col, embedder, docs, log, config.INGEST_BATCH)
                log(f"{col}: {counts[col]} doc")
        else:
            log("Không có hotels.csv — bỏ qua khách sạn.")
    finally:
        client.close()
    log(f"Ingest xong: {counts}")
    return counts
