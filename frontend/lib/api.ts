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

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) throw new ApiError(path, res.status);
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(path, res.status);
}
