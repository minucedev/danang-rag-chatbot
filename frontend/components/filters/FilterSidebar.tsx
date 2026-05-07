"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { SlidersHorizontal, X } from "lucide-react";
import { DISTRICTS } from "@/constants/districts";
import { useFilters } from "@/hooks/useFilters";
import { formatVND } from "@/lib/format";
import { cn } from "@/lib/utils";

export function FilterSidebar() {
  const { filters, setFilters, resetFilters } = useFilters();
  const [open, setOpen] = useState(false);

  const activeCount =
    (filters.district ? 1 : 0) +
    (filters.min_rating ? 1 : 0) +
    (filters.max_price ? 1 : 0);

  return (
    <div className="relative">
      {/* Toggle button */}
      <Button
        variant="outline"
        size="sm"
        className="gap-2 relative"
        onClick={() => setOpen((v) => !v)}
      >
        <SlidersHorizontal className="w-4 h-4" />
        Bộ lọc
        {activeCount > 0 && (
          <Badge className="absolute -top-2 -right-2 w-5 h-5 p-0 flex items-center justify-center text-xs">
            {activeCount}
          </Badge>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-10 z-20 w-72 rounded-xl border bg-background shadow-lg p-4 space-y-5">
          <div className="flex items-center justify-between">
            <span className="font-medium text-sm">Bộ lọc tìm kiếm</span>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setOpen(false)}>
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* District chips */}
          <div>
            <p className="text-xs text-muted-foreground mb-2">Quận / Huyện</p>
            <div className="flex flex-wrap gap-1.5">
              {DISTRICTS.map((d) => (
                <button
                  key={d.slug}
                  onClick={() => setFilters({ district: filters.district === d.slug ? undefined : d.slug })}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                    filters.district === d.slug
                      ? "bg-blue-600 text-white border-blue-600"
                      : "hover:bg-accent",
                  )}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {/* Min rating */}
          <div>
            <p className="text-xs text-muted-foreground mb-2">
              Đánh giá tối thiểu: <span className="font-medium text-foreground">{filters.min_rating ?? 0}/10</span>
            </p>
            <Slider
              min={0} max={10} step={0.5}
              value={[filters.min_rating ?? 0]}
              onValueChange={([v]) => setFilters({ min_rating: v > 0 ? v : undefined })}
            />
          </div>

          {/* Max price */}
          <div>
            <p className="text-xs text-muted-foreground mb-2">
              Giá tối đa:{" "}
              <span className="font-medium text-foreground">
                {filters.max_price ? formatVND(filters.max_price) : "Không giới hạn"}
              </span>
            </p>
            <Slider
              min={0} max={10_000_000} step={100_000}
              value={[filters.max_price ?? 0]}
              onValueChange={([v]) => setFilters({ max_price: v > 0 ? v : undefined })}
            />
          </div>

          <Button variant="outline" size="sm" className="w-full" onClick={resetFilters}>
            Xóa bộ lọc
          </Button>
        </div>
      )}
    </div>
  );
}
