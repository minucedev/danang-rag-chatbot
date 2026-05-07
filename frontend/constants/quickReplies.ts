export interface QuickReply {
  icon: string;
  text: string;
}

export const QUICK_REPLIES: QuickReply[] = [
  { icon: "🏨", text: "Khách sạn 4 sao gần biển Mỹ Khê" },
  { icon: "🍜", text: "Quán mì Quảng ngon ở Hải Châu" },
  { icon: "📍", text: "Điểm tham quan miễn phí ở Sơn Trà" },
  { icon: "⭐", text: "Đánh giá khách sạn Mường Thanh Sông Hàn" },
  { icon: "💰", text: "Phòng khách sạn dưới 1 triệu mỗi đêm" },
  { icon: "🗺️", text: "Lịch trình du lịch Đà Nẵng 3 ngày 2 đêm" },
];
