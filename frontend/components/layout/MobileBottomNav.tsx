"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function MobileBottomNav() {
  const pathname = usePathname();
  const isChat = pathname?.startsWith("/chat") ?? false;

  return (
    <nav className="md:hidden shrink-0 flex justify-around items-center px-4 pb-safe h-16 bg-surface/95 backdrop-blur-lg border-t border-outline-variant/30">
      <Link
        href="/chat"
        className={`flex flex-col items-center justify-center gap-0.5 p-2 rounded-full transition-all ${
          isChat
            ? "bg-primary-container text-on-primary-container"
            : "text-on-surface-variant hover:text-primary"
        }`}
      >
        <span
          className="material-symbols-outlined text-2xl"
          style={isChat ? { fontVariationSettings: "'FILL' 1" } : undefined}
        >
          chat_bubble
        </span>
        <span className="text-[10px] font-semibold">Chat</span>
      </Link>

      <button className="flex flex-col items-center justify-center gap-0.5 p-2 text-on-surface-variant opacity-50 cursor-not-allowed">
        <span className="material-symbols-outlined text-2xl">explore</span>
        <span className="text-[10px] font-semibold">Explore</span>
      </button>

      <button className="flex flex-col items-center justify-center gap-0.5 p-2 text-on-surface-variant opacity-50 cursor-not-allowed">
        <span className="material-symbols-outlined text-2xl">event_note</span>
        <span className="text-[10px] font-semibold">Plan</span>
      </button>

      <button className="flex flex-col items-center justify-center gap-0.5 p-2 text-on-surface-variant opacity-50 cursor-not-allowed">
        <span className="material-symbols-outlined text-2xl">account_circle</span>
        <span className="text-[10px] font-semibold">Profile</span>
      </button>
    </nav>
  );
}
