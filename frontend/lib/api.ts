import { getToken, clearToken } from "@/lib/auth";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Lỗi API mang theo HTTP status để caller phân biệt 404 vs lỗi khác.
export class ApiError extends Error {
  status: number;
  constructor(path: string, status: number) {
    super(`API ${path} → ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

// Gắn Authorization: Bearer nếu đã đăng nhập.
function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}`, ...extra } : { ...extra };
}

// 401 ở mọi endpoint (TRỪ form login/register) = token thiếu/hết hạn → dọn token + về /login.
// CHÚ Ý: KHÔNG bỏ qua /api/auth/me — 401 ở đó nghĩa là phiên đã chết, phải dọn token + redirect,
// nếu không user kẹt ở trạng thái đã-đăng-nhập-nhưng-token-hỏng.
function handle401(path: string): void {
  // Chỉ 2 form tự hiện lỗi (sai mật khẩu / trùng tên), không tự redirect.
  if (path.startsWith("/api/auth/login") || path.startsWith("/api/auth/register")) return;
  clearToken();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: authHeaders({ "Content-Type": "application/json", ...init?.headers }),
  });
  if (res.status === 401) handle401(path);
  if (!res.ok) throw new ApiError(path, res.status);
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE", headers: authHeaders() });
  if (res.status === 401) handle401(path);
  if (!res.ok) throw new ApiError(path, res.status);
}
