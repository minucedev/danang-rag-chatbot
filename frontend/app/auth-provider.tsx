"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { getToken, setToken, clearToken } from "@/lib/auth";

export interface AuthUser {
  id: string;
  username: string;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const PUBLIC_ROUTES = ["/login", "/register"];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  // null = chưa biết (trước khi mount đọc được localStorage) → tránh hydration mismatch.
  const [hasToken, setHasToken] = useState<boolean | null>(null);

  // Đọc token sau mount (localStorage chỉ có ở client). Defer qua microtask để không
  // setState đồng bộ trong effect body — cùng idiom với useProfileSession.
  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) setHasToken(!!getToken());
    });
    return () => {
      active = false;
    };
  }, []);

  const isPublic = PUBLIC_ROUTES.includes(pathname);

  const meQuery = useQuery<AuthUser>({
    queryKey: ["me"],
    queryFn: () => apiFetch<AuthUser>("/api/auth/me"),
    enabled: hasToken === true,
    retry: false,
    staleTime: 5 * 60_000,
  });

  // Guard 2 chiều (đã biết trạng thái token):
  // - CHƯA đăng nhập + route bảo vệ → /login.
  // - ĐÃ đăng nhập + đang ở trang public (/login, /register) → /chat (tách bạch luồng).
  useEffect(() => {
    if (hasToken === null) return;
    if (!hasToken && !isPublic) router.replace("/login");
    else if (hasToken && isPublic) router.replace("/chat");
  }, [hasToken, isPublic, router]);

  async function login(username: string, password: string) {
    const res = await apiFetch<{ token: string; user: AuthUser }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(res.token);
    setHasToken(true);
    qc.setQueryData(["me"], res.user);
    router.replace("/chat");
  }

  async function register(username: string, password: string) {
    const res = await apiFetch<{ token: string; user: AuthUser }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(res.token);
    setHasToken(true);
    qc.setQueryData(["me"], res.user);
    router.replace("/chat");
  }

  async function logout() {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // token có thể đã hết hạn — vẫn dọn phía client.
    }
    clearToken();
    setHasToken(false);
    qc.clear();
    router.replace("/login");
  }

  const value: AuthContextValue = {
    user: meQuery.data ?? null,
    isLoading: hasToken === null || (hasToken === true && meQuery.isLoading),
    login,
    register,
    logout,
  };

  // Chặn nháy nội dung trang cần đăng nhập khi auth chưa rõ / đang chuyển hướng.
  if (!isPublic && (hasToken === null || (hasToken === true && meQuery.isLoading))) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Đang tải…
      </div>
    );
  }
  if (!isPublic && !hasToken) return null; // đang redirect sang /login
  if (isPublic && hasToken === true) return null; // đã đăng nhập → đang redirect sang /chat

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth phải dùng bên trong <AuthProvider>");
  return ctx;
}
