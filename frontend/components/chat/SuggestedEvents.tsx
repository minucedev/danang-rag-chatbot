"use client";
import { ExternalLink } from "lucide-react";
import { useEventsQuery, type EventItem } from "@/hooks/useEvents";

export function SuggestedEvents({ onSelect }: { onSelect: (text: string) => void }) {
  const { data, isLoading } = useEventsQuery();
  const events = data?.items ?? [];

  if (isLoading || events.length === 0) return null;

  return (
    <div className="px-4 py-2">
      <div className="flex items-center justify-between mb-3 px-1">
        <h3 className="text-sm font-semibold text-primary flex items-center gap-2">
          <span className="material-symbols-outlined text-base text-secondary">local_activity</span>
          Sự kiện nổi bật
        </h3>
        <button className="text-xs font-bold text-primary hover:underline">Xem tất cả</button>
      </div>
      <div className="flex gap-4 overflow-x-auto hide-scrollbar pb-2 -mx-4 px-4">
        {events.map((ev) => (
          <EventCard key={ev.id} ev={ev} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}

function EventCard({ ev, onSelect }: { ev: EventItem; onSelect: (text: string) => void }) {
  return (
    <div className="flex-none w-64 bg-surface-container-lowest rounded-xl border border-outline-variant/10 shadow-sm hover:shadow-md transition-all overflow-hidden group">
      {ev.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={ev.image_url}
          alt={ev.title}
          className="h-36 w-full object-cover group-hover:scale-105 transition-transform duration-300"
        />
      ) : (
        <div className="h-36 bg-primary-fixed flex items-center justify-center">
          <span
            className="material-symbols-outlined text-5xl text-primary opacity-40"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            celebration
          </span>
        </div>
      )}

      <button
        type="button"
        onClick={() => onSelect(`Thông tin về sự kiện "${ev.title}"`)}
        className="w-full text-left p-3 space-y-2"
      >
        {ev.district && (
          <span className="text-xs font-bold text-primary uppercase tracking-wide">
            {ev.district}
          </span>
        )}
        <p className="font-semibold text-sm text-on-surface leading-tight line-clamp-2">
          {ev.title}
        </p>
        {ev.time_display && (
          <div className="flex items-center gap-1.5 text-on-surface-variant">
            <span className="material-symbols-outlined text-sm">calendar_today</span>
            <span className="text-xs">{ev.time_display}</span>
          </div>
        )}
      </button>

      {ev.url && (
        <div className="px-3 pb-3">
          <a
            href={ev.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <ExternalLink className="w-3 h-3" />
            Chi tiết
          </a>
        </div>
      )}
    </div>
  );
}
