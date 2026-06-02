"use client";
import { useParams, useRouter } from "next/navigation";
import { useSessionsQuery } from "@/hooks/useSessions";
import { relativeDate } from "@/lib/format";
import { SessionItem } from "./SessionItem";

export function SessionSidebar() {
  const { data: sessions = [] } = useSessionsQuery();
  const params = useParams();
  const router = useRouter();
  const activeId = params?.sessionId as string | undefined;

  // Group by day
  const groups: Record<string, typeof sessions> = {};
  for (const s of sessions) {
    const label = relativeDate(s.updated_at);
    (groups[label] ??= []).push(s);
  }

  return (
    <aside className="hidden md:flex flex-col h-full w-72 shrink-0 bg-surface-container-low border-r border-outline-variant/20">
      {/* Header */}
      <div className="px-6 pt-6 pb-4">
        <h2 className="text-lg font-bold text-primary tracking-tight">Travel History</h2>
        <p className="text-xs text-on-surface-variant mt-0.5">Your Da Nang Journeys</p>
      </div>

      {/* New Trip button */}
      <div className="px-4 mb-2">
        <button
          onClick={() => router.push("/chat")}
          className="w-full flex items-center gap-3 px-4 py-3 bg-primary-container text-on-primary-container rounded-xl font-medium text-sm hover:brightness-105 transition-all active:scale-[0.98]"
        >
          <span className="material-symbols-outlined text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
            add_circle
          </span>
          New Trip
        </button>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto px-4 space-y-1 pb-4">
        {Object.entries(groups).map(([label, items]) => (
          <div key={label} className="mb-3">
            <p className="text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider px-3 py-1.5">
              {label}
            </p>
            {items.map((s) => (
              <SessionItem key={s.id} session={s} isActive={s.id === activeId} />
            ))}
          </div>
        ))}
        {sessions.length === 0 && (
          <p className="text-xs text-on-surface-variant px-3 py-2 opacity-70">
            Chưa có cuộc hội thoại nào.
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-outline-variant/30 p-4 space-y-1">
        <button className="w-full flex items-center gap-3 px-3 py-2.5 text-on-surface-variant hover:bg-surface-container-highest rounded-xl text-sm transition-colors">
          <span className="material-symbols-outlined text-xl">help</span>
          Help
        </button>
        <button className="w-full flex items-center gap-3 px-3 py-2.5 text-on-surface-variant hover:bg-surface-container-highest rounded-xl text-sm transition-colors">
          <span className="material-symbols-outlined text-xl">settings</span>
          Settings
        </button>
      </div>
    </aside>
  );
}
