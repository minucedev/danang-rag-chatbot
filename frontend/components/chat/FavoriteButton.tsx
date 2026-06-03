"use client";
import { toast } from "sonner";
import { useFavoritesQuery, useAddFavorite, useRemoveFavorite } from "@/hooks/useFavorites";
import type { Source } from "@/lib/sourceAdapter";

// Nút tim lưu/bỏ lưu 1 địa điểm. Cần source có point_id + collection (chat SSE & recommend đều có).
export function FavoriteButton({ source }: { source: Source }) {
  const { data } = useFavoritesQuery();
  const add = useAddFavorite();
  const remove = useRemoveFavorite();

  const pointId = source.point_id;
  const collection = source.collection;
  if (!pointId || !collection) return null;

  const existing = data?.items.find(
    (f) => f.pointId === pointId && f.collection === collection,
  );
  const isFav = !!existing;
  const busy = add.isPending || remove.isPending;

  async function toggle(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    try {
      if (existing) {
        await remove.mutateAsync(existing.id);
        toast.success("Đã bỏ lưu");
      } else {
        await add.mutateAsync({ pointId: pointId!, collection: collection!, snapshot: source });
        toast.success("Đã lưu vào yêu thích");
      }
    } catch {
      toast.error("Thao tác thất bại");
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-label={isFav ? "Bỏ lưu" : "Lưu"}
      aria-pressed={isFav}
      className="flex items-center justify-center w-7 h-7 rounded-full bg-white/90 backdrop-blur-sm shadow-sm hover:bg-white transition-colors disabled:opacity-50"
    >
      <span
        className={`material-symbols-outlined text-base ${isFav ? "text-error" : "text-on-surface-variant"}`}
        style={isFav ? { fontVariationSettings: "'FILL' 1" } : undefined}
      >
        favorite
      </span>
    </button>
  );
}
