"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { X } from "lucide-react";
import { DISTRICTS } from "@/constants/districts";
import { useFilters } from "@/hooks/useFilters";
import { formatVND } from "@/lib/format";
import { cn } from "@/lib/utils";

interface FilterChipsProps {
  onOpenFilter: () => void;
}

/** Inline filter chips bar — dùng trong [sessionId]/page.tsx */
export function FilterChips({ onOpenFilter }: FilterChipsProps) {
  const { filters, resetFilters } = useFilters();

  const districtLabel = DISTRICTS.find((d) => d.slug === filters.district)?.label;
  const activeCount =
    (filters.district ? 1 : 0) +
    (filters.min_rating ? 1 : 0) +
    (filters.min_price ? 1 : 0) +
    (filters.max_price ? 1 : 0);

  const chipBase =
    "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors border shrink-0";
  const chipInactive =
    "bg-surface-container-lowest border-outline-variant text-on-surface-variant hover:bg-surface-container-high";
  const chipActive =
    "bg-primary-fixed border-primary/40 text-primary";

  return (
    <div className="sticky top-0 z-30 bg-surface/90 backdrop-blur-md border-b border-outline-variant/20 px-4 py-2.5">
      <div className="flex items-center gap-2 overflow-x-auto hide-scrollbar max-w-4xl mx-auto">
        <button
          onClick={onOpenFilter}
          className={cn(chipBase, filters.district ? chipActive : chipInactive)}
        >
          <span className="material-symbols-outlined text-base">location_on</span>
          {districtLabel ?? "Quận"}
          <span className="material-symbols-outlined text-base">expand_more</span>
        </button>

        <button
          onClick={onOpenFilter}
          className={cn(chipBase, filters.min_rating ? chipActive : chipInactive)}
        >
          <span className="material-symbols-outlined text-base">star</span>
          {filters.min_rating ? `${filters.min_rating}★+` : "Đánh giá"}
        </button>

        <button
          onClick={onOpenFilter}
          className={cn(chipBase, (filters.min_price || filters.max_price) ? chipActive : chipInactive)}
        >
          <span className="material-symbols-outlined text-base">payments</span>
          {filters.max_price ? `≤ ${formatVND(filters.max_price)}` : "Giá"}
          <span className="material-symbols-outlined text-base">expand_more</span>
        </button>

        {activeCount > 0 && (
          <>
            <div className="h-5 w-px bg-outline-variant/50 mx-0.5 shrink-0" />
            <button
              onClick={resetFilters}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-on-primary rounded-full text-xs font-medium shadow-sm hover:bg-primary/90 transition-colors shrink-0"
            >
              <X className="w-3 h-3" />
              Xóa bộ lọc
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/** Popup panel bộ lọc */
export function FilterSidebar() {
  const { filters, setFilters, resetFilters } = useFilters();
  const [open, setOpen] = useState(false);

  const activeCount =
    (filters.district ? 1 : 0) +
    (filters.min_rating ? 1 : 0) +
    (filters.min_price ? 1 : 0) +
    (filters.max_price ? 1 : 0);

  return (
    <div className="relative">
      {/* Compact trigger button — dùng ở nơi không có FilterChips */}
      <button
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors border",
          activeCount > 0
            ? "bg-primary-fixed border-primary/40 text-primary"
            : "bg-surface-container-lowest border-outline-variant text-on-surface-variant hover:bg-surface-container-high",
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="material-symbols-outlined text-base">tune</span>
        Bộ lọc
        {activeCount > 0 && (
          <span className="w-4 h-4 bg-primary text-on-primary rounded-full text-[10px] font-bold flex items-center justify-center">
            {activeCount}
          </span>
        )}
      </button>

      {open && <FilterPanel onClose={() => setOpen(false)} />}
    </div>
  );
}

/** Controlled popup — có thể dùng từ FilterChips */
export function FilterPanel({ onClose }: { onClose: () => void }) {
  const { filters, setFilters, resetFilters } = useFilters();

  return (
    <div className="absolute right-0 top-10 z-40 w-72 rounded-2xl border border-outline-variant/20 bg-surface-container-lowest shadow-xl p-4 space-y-5">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-sm text-on-surface">Bộ lọc tìm kiếm</span>
        <button
          className="p-1 rounded-lg hover:bg-surface-container-high transition-colors text-on-surface-variant"
          onClick={onClose}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* District chips */}
      <div>
        <p className="text-xs font-medium text-on-surface-variant mb-2">Quận / Huyện</p>
        <div className="flex flex-wrap gap-1.5">
          {DISTRICTS.map((d) => (
            <button
              key={d.slug}
              onClick={() => setFilters({ district: filters.district === d.slug ? undefined : d.slug })}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                filters.district === d.slug
                  ? "bg-primary text-on-primary border-primary"
                  : "border-outline-variant text-on-surface-variant hover:bg-surface-container-high",
              )}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {/* Min rating */}
      <div>
        <p className="text-xs font-medium text-on-surface-variant mb-2">
          Đánh giá tối thiểu:{" "}
          <span className="text-on-surface font-semibold">{filters.min_rating ?? 0}/10</span>
        </p>
        <Slider
          min={0} max={10} step={0.5}
          value={[filters.min_rating ?? 0]}
          onValueChange={([v]) => setFilters({ min_rating: v > 0 ? v : undefined })}
        />
      </div>

      {/* Min price */}
      <div>
        <p className="text-xs font-medium text-on-surface-variant mb-2">
          Giá tối thiểu:{" "}
          <span className="text-on-surface font-semibold">
            {filters.min_price ? formatVND(filters.min_price) : "Không giới hạn"}
          </span>
        </p>
        <Slider
          min={0} max={10_000_000} step={100_000}
          value={[filters.min_price ?? 0]}
          onValueChange={([v]) => setFilters({ min_price: v > 0 ? v : undefined })}
        />
      </div>

      {/* Max price */}
      <div>
        <p className="text-xs font-medium text-on-surface-variant mb-2">
          Giá tối đa:{" "}
          <span className="text-on-surface font-semibold">
            {filters.max_price ? formatVND(filters.max_price) : "Không giới hạn"}
          </span>
        </p>
        <Slider
          min={0} max={10_000_000} step={100_000}
          value={[filters.max_price ?? 0]}
          onValueChange={([v]) => setFilters({ max_price: v > 0 ? v : undefined })}
        />
      </div>

      <Button variant="outline" size="sm" className="w-full" onClick={() => { resetFilters(); onClose(); }}>
        Xóa bộ lọc
      </Button>
    </div>
  );
}
