"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/app/auth-provider";

// Dashboard quản trị do backend phục vụ (cùng host với API), mở tab mới — chỉ hiện với role admin.
const ADMIN_URL = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/admin`;

const TABS = [
  { href: "/chat", label: "Chat", icon: "chat_bubble", match: (p: string) => p.startsWith("/chat") },
  { href: "/recommend", label: "Gợi ý", icon: "recommend", match: (p: string) => p.startsWith("/recommend") },
  { href: "/saved", label: "Đã lưu", icon: "bookmark", match: (p: string) => p.startsWith("/saved") || p.startsWith("/itineraries") },
  { href: "/profile", label: "Hồ sơ", icon: "account_circle", match: (p: string) => p.startsWith("/profile") },
];

export function MobileBottomNav() {
  const pathname = usePathname() ?? "";
  const { user } = useAuth();

  return (
    <nav className="md:hidden shrink-0 flex justify-around items-center px-4 pb-safe h-16 bg-surface/95 backdrop-blur-lg border-t border-outline-variant/30">
      {TABS.map((tab) => {
        const active = tab.match(pathname);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-col items-center justify-center gap-0.5 p-2 rounded-full transition-all ${
              active
                ? "bg-primary-container text-on-primary-container"
                : "text-on-surface-variant hover:text-primary"
            }`}
          >
            <span
              className="material-symbols-outlined text-2xl"
              style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
            >
              {tab.icon}
            </span>
            <span className="text-[10px] font-semibold">{tab.label}</span>
          </Link>
        );
      })}
      {user?.role === "admin" && (
        <a
          href={ADMIN_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex flex-col items-center justify-center gap-0.5 p-2 rounded-full text-on-surface-variant hover:text-primary transition-all"
        >
          <span className="material-symbols-outlined text-2xl">shield_person</span>
          <span className="text-[10px] font-semibold">Admin</span>
        </a>
      )}
    </nav>
  );
}
