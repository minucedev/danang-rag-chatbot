import type { RecommendItem } from "@/hooks/useRecommend";

// Shape dùng chung cho SourceCard. Nguồn từ SSE `sources` (snake_case) đã đúng shape này;
// favorites lưu nguyên dict nên cũng khớp. Recommend trả camelCase phẳng → cần adapter bên dưới.
export interface Source {
  point_id?: string;
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

// Khớp nối DUY NHẤT biết mapping RecommendItem → Source. Recommend schema đổi → chỉ sửa đây.
export function recommendItemToSource(item: RecommendItem): Source {
  return {
    point_id: item.placeId,
    entity_name: item.name,
    collection: item.collection,
    district: item.district,
    rating: item.rating ?? undefined,
    address: item.address,
  };
}
