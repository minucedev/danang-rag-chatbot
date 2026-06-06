// Lưu token đăng nhập (opaque, từ /api/auth/login) trong localStorage. Gửi kèm mọi request
// dưới dạng `Authorization: Bearer <token>` (xem lib/api.ts). Đây LÀ auth thật, thay client_id cũ.
const TOKEN_KEY = "ppbl_auth_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  // Profile session ghim ở localStorage thuộc về user vừa đăng xuất → bỏ để user sau không
  // kế thừa (backend sẽ 404 vì không sở hữu, nhưng dọn để tránh trạng thái lỗi).
  localStorage.removeItem("ppbl_profile_session_id");
}
