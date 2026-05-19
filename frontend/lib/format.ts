const vndFormatter = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export function formatVND(amount: number): string {
  return vndFormatter.format(amount);
}

export const INTENT_LABELS: Record<string, string> = {
  hotel_search: "Khách sạn",
  restaurant_search: "Nhà hàng",
  place_search: "Địa điểm",
  review_search: "Đánh giá",
  room_search: "Phòng",
  price_search: "Giá",
  general: "Tổng quát",
  specific_search: "Địa điểm cụ thể",
};

export function intentLabel(value: string): string {
  return INTENT_LABELS[value] ?? value;
}

export function relativeDate(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 86400) return "Hôm nay";
  if (diff < 172800) return "Hôm qua";
  return new Date(ts * 1000).toLocaleDateString("vi-VN");
}
