"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { SourceCard } from "@/components/chat/SourceCard";
import { FavoriteButton } from "@/components/chat/FavoriteButton";
import { Button } from "@/components/ui/button";
import { useFavoritesQuery } from "@/hooks/useFavorites";
import { useItinerariesQuery, useDeleteItinerary } from "@/hooks/useItineraries";
import { relativeDate } from "@/lib/format";

type Tab = "places" | "itineraries";

export default function SavedPage() {
  const [tab, setTab] = useState<Tab>("places");
  const favs = useFavoritesQuery();
  const itins = useItinerariesQuery();
  const delItin = useDeleteItinerary();

  async function handleDeleteItinerary(id: number) {
    try {
      await delItin.mutateAsync(id);
      toast.success("Đã xoá lịch trình");
    } catch {
      toast.error("Xoá thất bại");
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <h1 className="text-xl font-bold text-on-surface">Đã lưu</h1>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-outline-variant/20">
        {([
          { key: "places", label: "Địa điểm", icon: "favorite" },
          { key: "itineraries", label: "Lịch trình", icon: "map" },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? "border-primary text-primary font-semibold"
                : "border-transparent text-on-surface-variant hover:text-primary"
            }`}
          >
            <span className="material-symbols-outlined text-base">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Places */}
      {tab === "places" &&
        (favs.isLoading ? (
          <p className="text-sm text-on-surface-variant">Đang tải…</p>
        ) : favs.isError ? (
          <p className="text-sm text-error">Không tải được danh sách đã lưu. Thử lại sau.</p>
        ) : !favs.data?.items.length ? (
          <Empty icon="favorite" text="Chưa lưu địa điểm nào. Bấm tim trên thẻ kết quả để lưu." />
        ) : (
          <div className="flex flex-wrap gap-3">
            {favs.data.items.map((f) => (
              <SourceCard
                key={f.id}
                source={f.snapshot}
                action={<FavoriteButton source={f.snapshot} />}
              />
            ))}
          </div>
        ))}

      {/* Itineraries */}
      {tab === "itineraries" &&
        (itins.isLoading ? (
          <p className="text-sm text-on-surface-variant">Đang tải…</p>
        ) : itins.isError ? (
          <p className="text-sm text-error">Không tải được danh sách đã lưu. Thử lại sau.</p>
        ) : !itins.data?.items.length ? (
          <Empty icon="map" text="Chưa lưu lịch trình nào. Hỏi 'lịch trình 3 ngày…' rồi bấm Lưu." />
        ) : (
          <div className="space-y-2">
            {itins.data.items.map((it) => (
              <div
                key={it.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-outline-variant/20 bg-surface-container-lowest px-4 py-3"
              >
                <Link href={`/itineraries/${it.id}`} className="min-w-0 flex-1">
                  <p className="font-medium text-sm text-on-surface truncate">{it.title}</p>
                  <p className="text-xs text-on-surface-variant">{relativeDate(it.updatedAt)}</p>
                </Link>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 text-error"
                  onClick={() => handleDeleteItinerary(it.id)}
                  disabled={delItin.isPending}
                >
                  <span className="material-symbols-outlined text-base">delete</span>
                </Button>
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}

function Empty({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="text-center py-12 text-on-surface-variant">
      <span className="material-symbols-outlined text-5xl opacity-40">{icon}</span>
      <p className="mt-2 text-sm">{text}</p>
    </div>
  );
}
