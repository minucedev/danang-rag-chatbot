"use client";
import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/app/auth-provider";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

export default function RegisterPage() {
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (username.trim().length < 3) {
      setError("Tài khoản tối thiểu 3 ký tự");
      return;
    }
    if (password.length < 6) {
      setError("Mật khẩu tối thiểu 6 ký tự");
      return;
    }
    if (password !== confirm) {
      setError("Mật khẩu nhập lại không khớp");
      return;
    }
    setSubmitting(true);
    try {
      await register(username.trim(), password);
      // register() tự đăng nhập + chuyển hướng /chat khi thành công.
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 409
            ? "Tên đăng nhập đã tồn tại"
            : "Máy chủ gặp lỗi, vui lòng thử lại sau",
        );
      } else {
        setError("Không kết nối được máy chủ, kiểm tra mạng và thử lại");
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-8">
        <h1 className="text-xl font-bold">Đăng ký</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tạo tài khoản để dùng trợ lý du lịch Đà Nẵng.
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="space-y-1">
            <label htmlFor="username" className="text-sm font-medium">
              Tài khoản
            </label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="password" className="text-sm font-medium">
              Mật khẩu
            </label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="confirm" className="text-sm font-medium">
              Nhập lại mật khẩu
            </label>
            <Input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Đang tạo tài khoản…" : "Đăng ký"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-muted-foreground">
          Đã có tài khoản?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Đăng nhập
          </Link>
        </p>
      </Card>
    </div>
  );
}
