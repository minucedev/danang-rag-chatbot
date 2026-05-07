import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { MapPin, Star, ExternalLink } from "lucide-react";
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

export function SourceCard({ source }: { source: Source }) {
  const name = getDisplayName(source);
  const rating = getRating(source);
  const addr = getAddress(source);

  return (
    <Card className="w-56 shrink-0 hover:shadow-md transition-shadow">
      <CardContent className="p-3 space-y-2">
        <div className="font-medium text-sm leading-tight line-clamp-2">{name}</div>
        <div className="flex flex-wrap gap-1">
          {source.district && (
            <Badge variant="outline" className="text-xs">{source.district}</Badge>
          )}
        </div>
        {rating !== undefined && (
          <div className="flex items-center gap-1 text-xs text-amber-600">
            <Star className="w-3 h-3 fill-amber-400 stroke-amber-400" />
            <span>{rating.toFixed(1)}/10</span>
            {source.review_count && (
              <span className="text-muted-foreground">({source.review_count.toLocaleString("vi-VN")})</span>
            )}
          </div>
        )}
        {source.min_price !== undefined && (
          <div className="text-xs text-muted-foreground">
            {source.max_price && source.max_price > source.min_price
              ? `${formatVND(source.min_price)} – ${formatVND(source.max_price)}`
              : formatVND(source.min_price)}
          </div>
        )}
        {addr && (
          <div className="flex items-start gap-1 text-xs text-muted-foreground">
            <MapPin className="w-3 h-3 mt-0.5 shrink-0" />
            <span className="line-clamp-2">{addr}</span>
          </div>
        )}
        <a
          href={getMapsUrl(source)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ExternalLink className="w-3 h-3" />
          Xem trên Maps
        </a>
      </CardContent>
    </Card>
  );
}
