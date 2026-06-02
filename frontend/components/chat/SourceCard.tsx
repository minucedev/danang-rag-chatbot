import { formatVND } from "@/lib/format";

interface Source {
  entity_name?: string;
  parent_entity_name?: string;
  place_name?: string;
  district?: string;
  rating?: number;
  parent_rating?: number;
  review_count?: number;
  min_price?: number;
  max_price?: number;
  address?: string;
  parent_address?: string;
  content?: string;
  collection?: string;
}

function getDisplayName(s: Source): string {
  return s.parent_entity_name || s.entity_name || s.place_name || "Không rõ tên";
}

function getAddress(s: Source): string {
  return s.parent_address || s.address || "";
}

function getRating(s: Source): number | undefined {
  return s.parent_rating ?? s.rating;
}

function getMapsUrl(s: Source): string {
  const addr = getAddress(s);
  const name = getDisplayName(s);
  const q = encodeURIComponent(`${name}${addr ? ", " + addr : ""}, Đà Nẵng`);
  return `https://www.google.com/maps/search/?api=1&query=${q}`;
}

function getCategoryIcon(collection?: string): string {
  if (!collection) return "place";
  if (collection.includes("hotel") || collection.includes("accommodation")) return "hotel";
  if (collection.includes("restaurant")) return "restaurant";
  if (collection.includes("review")) return "rate_review";
  if (collection.includes("room")) return "king_bed";
  return "place";
}

function getCategoryLabel(collection?: string): string {
  if (!collection) return "Địa điểm";
  if (collection.includes("hotel") || collection.includes("accommodation")) return "Khách sạn";
  if (collection.includes("restaurant")) return "Nhà hàng";
  if (collection.includes("review")) return "Đánh giá";
  if (collection.includes("room")) return "Phòng";
  return "Địa điểm";
}

export function SourceCard({ source }: { source: Source }) {
  const name = getDisplayName(source);
  const rating = getRating(source);
  const addr = getAddress(source);
  const icon = getCategoryIcon(source.collection);
  const categoryLabel = getCategoryLabel(source.collection);

  return (
    <div className="w-64 shrink-0 bg-surface-container-lowest rounded-xl border border-outline-variant/10 shadow-sm hover:shadow-md transition-shadow overflow-hidden group">
      {/* Icon placeholder header */}
      <div className="h-24 bg-primary-fixed flex items-center justify-center relative">
        <span
          className="material-symbols-outlined text-5xl text-primary opacity-40"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {icon}
        </span>
        {rating !== undefined && (
          <div className="absolute top-2 left-2 flex items-center gap-1 bg-white/90 backdrop-blur-sm rounded-full px-2 py-0.5 shadow-sm">
            <span
              className="material-symbols-outlined text-secondary text-sm"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              star
            </span>
            <span className="text-xs font-bold text-on-surface">
              {rating.toFixed(1)}/10
            </span>
          </div>
        )}
      </div>

      {/* Card body */}
      <div className="p-3 space-y-2.5">
        <div>
          <p className="font-semibold text-sm text-on-surface leading-tight line-clamp-2">{name}</p>
          {addr && (
            <div className="flex items-start gap-1 mt-1">
              <span className="material-symbols-outlined text-base text-on-surface-variant shrink-0 leading-tight">
                location_on
              </span>
              <span className="text-xs text-on-surface-variant line-clamp-1">{addr}</span>
            </div>
          )}
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5">
          <span className="px-2 py-0.5 bg-tertiary-fixed text-on-tertiary-fixed-variant rounded-lg text-[11px] font-bold uppercase tracking-wide">
            {categoryLabel}
          </span>
          {source.district && (
            <span className="px-2 py-0.5 bg-surface-container text-on-surface-variant rounded-lg text-[11px] font-medium">
              {source.district}
            </span>
          )}
          {source.review_count && (
            <span className="px-2 py-0.5 bg-surface-container text-on-surface-variant rounded-lg text-[11px] font-medium">
              {source.review_count.toLocaleString("vi-VN")} đánh giá
            </span>
          )}
        </div>

        {/* Price + Maps */}
        <div className="flex items-center justify-between pt-1 border-t border-outline-variant/30">
          {source.min_price !== undefined ? (
            <span className="text-sm font-bold text-primary">
              {source.max_price && source.max_price > source.min_price
                ? `${formatVND(source.min_price)} – ${formatVND(source.max_price)}`
                : formatVND(source.min_price)}
            </span>
          ) : (
            <span className="text-xs text-on-surface-variant">—</span>
          )}
          <a
            href={getMapsUrl(source)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-primary border border-primary/20 px-2.5 py-1 rounded-lg text-xs hover:bg-primary-container/10 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">map</span>
            Maps
          </a>
        </div>
      </div>
    </div>
  );
}
