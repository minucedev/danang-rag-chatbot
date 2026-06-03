"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/chat", label: "Chat", match: (p: string) => p.startsWith("/chat") },
  { href: "/recommend", label: "Gợi ý", match: (p: string) => p.startsWith("/recommend") },
  { href: "/saved", label: "Đã lưu", match: (p: string) => p.startsWith("/saved") || p.startsWith("/itineraries") },
];

export function TopAppBar() {
  const pathname = usePathname() ?? "";

  return (
    <header className="h-16 shrink-0 bg-surface/80 backdrop-blur-md shadow-sm border-b border-outline-variant/10 z-50">
      <div className="flex items-center justify-between h-full px-6 max-w-screen-xl mx-auto">
        {/* Logo */}
        <Link href="/chat" className="flex items-center gap-3">
          <span
            className="material-symbols-outlined text-3xl text-primary"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            explore
          </span>
          <span className="text-lg font-bold text-primary tracking-tight">
            Da Nang AI Concierge
          </span>
        </Link>

        {/* Nav tabs — desktop only */}
        <nav className="hidden md:flex items-center gap-6">
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={
                  active
                    ? "text-primary font-semibold border-b-2 border-primary pb-0.5 text-sm"
                    : "text-on-surface-variant text-sm hover:text-primary transition-colors"
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right actions — desktop only */}
        <div className="hidden md:flex items-center gap-2">
          <Link
            href="/profile"
            aria-label="Hồ sơ"
            className="w-9 h-9 rounded-full bg-primary-fixed border-2 border-primary-container flex items-center justify-center ml-1 hover:border-primary transition-colors"
          >
            <span className="text-xs font-bold text-primary">DN</span>
          </Link>
        </div>

        {/* Profile shortcut — mobile only */}
        <Link href="/profile" className="md:hidden p-2 text-on-surface-variant" aria-label="Hồ sơ">
          <span className="material-symbols-outlined text-2xl">account_circle</span>
        </Link>
      </div>
    </header>
  );
}
