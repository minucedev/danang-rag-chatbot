// Quyền sở hữu favorites/itineraries giờ suy từ token đăng nhập (xem lib/auth.ts) — KHÔNG
// còn client_id ẩn danh. File này chỉ còn giữ "profile session" ghim cho Profile/Recommend.
const PROFILE_SESSION_KEY = "ppbl_profile_session_id";

// Profile/Recommend backend keyed theo session_id. Ta ghim 1 session "hồ sơ" cố định
// trong localStorage để hồ sơ không mất khi mở chat mới.
export function getStoredProfileSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(PROFILE_SESSION_KEY);
}

export function setStoredProfileSessionId(id: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(PROFILE_SESSION_KEY, id);
}
