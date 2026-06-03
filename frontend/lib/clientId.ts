// Định danh ẩn danh phía client (KHÔNG phải auth) — chỉ là khoá ổn định lưu trong
// localStorage để "yêu thích" và "lịch trình đã lưu" sống sót qua các cuộc hội thoại.
// Sau này gắn auth thật thì chỉ cần đổi 1 nơi này.
const CLIENT_KEY = "ppbl_client_id";
const PROFILE_SESSION_KEY = "ppbl_profile_session_id";

export function getClientId(): string {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem(CLIENT_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(CLIENT_KEY, id);
  }
  return id;
}

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
