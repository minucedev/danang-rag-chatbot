// Danh sách lựa chọn hồ sơ cho UI. Đây là BẢN SAO TAY của literal Python
// (backend/app/rag/schemas.py: Interest/Companions/BudgetLevel/Language) — KHÔNG có cơ chế
// ép đồng bộ. Khi thêm/đổi giá trị phải sửa cả 3 nơi: file này, schemas.py, và map
// dịch `_*_VI` trong backend/app/rag/pipeline.py. Component không hardcode → đổi nhãn chỉ sửa đây.

export interface Option<T extends string> {
  value: T;
  label: string;
  icon: string; // Material Symbols name
}

export type Interest =
  | "beach" | "food" | "cafe" | "culture" | "nightlife" | "family" | "adventure" | "shopping";
export type Companions = "solo" | "couple" | "family" | "friends" | "business";
export type BudgetLevel = "low" | "mid" | "high";
export type Language = "vi" | "en";

export const INTERESTS: Option<Interest>[] = [
  { value: "beach", label: "Biển", icon: "beach_access" },
  { value: "food", label: "Ẩm thực", icon: "restaurant" },
  { value: "cafe", label: "Cà phê", icon: "local_cafe" },
  { value: "culture", label: "Văn hoá", icon: "temple_buddhist" },
  { value: "nightlife", label: "Về đêm", icon: "nightlife" },
  { value: "family", label: "Gia đình", icon: "family_restroom" },
  { value: "adventure", label: "Phiêu lưu", icon: "hiking" },
  { value: "shopping", label: "Mua sắm", icon: "shopping_bag" },
];

export const COMPANIONS: Option<Companions>[] = [
  { value: "solo", label: "Một mình", icon: "person" },
  { value: "couple", label: "Cặp đôi", icon: "favorite" },
  { value: "family", label: "Gia đình", icon: "family_restroom" },
  { value: "friends", label: "Bạn bè", icon: "groups" },
  { value: "business", label: "Công tác", icon: "work" },
];

export const BUDGET_LEVELS: Option<BudgetLevel>[] = [
  { value: "low", label: "Tiết kiệm", icon: "savings" },
  { value: "mid", label: "Trung bình", icon: "payments" },
  { value: "high", label: "Cao cấp", icon: "diamond" },
];

export const LANGUAGES: Option<Language>[] = [
  { value: "vi", label: "Tiếng Việt", icon: "translate" },
  { value: "en", label: "English", icon: "translate" },
];
