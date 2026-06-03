"use client";
import { useState } from "react";
import Link from "next/link";
import { SourceCard } from "@/components/chat/SourceCard";
import { FavoriteButton } from "@/components/chat/FavoriteButton";
import { recommendItemToSource } from "@/lib/sourceAdapter";
import { useProfileSession } from "@/hooks/useProfile";
import { useRecommendQuery } from "@/hooks/useRecommend";
import { DISTRICTS } from "@/constants/districts";

const NOTE_LABELS: Record<string, string> = {
  no_profile: "Bạn chưa có hồ sơ — kết quả là gợi ý chung. Điền hồ sơ để cá nhân hoá.",
  relaxed_interests: "Đã mở rộng theo sở thích để có thêm kết quả.",
  relaxed_rating: "Đã nới tiêu chí đánh giá để có thêm kết quả.",
  relaxed_price: "Đã nới tiêu chí giá để có thêm kết quả.",
};

export default function RecommendPage() {
  const sessionId = useProfileSession();
  const [district, setDistrict] = useState<string>("");
  const [includeHotels, setIncludeHotels] = useState(false);

  const { data, isLoading, isError } = useRecommendQuery({
    sessionId,
    district: district || undefined,
    includeHotels,
  });

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-on-surface">Gợi ý cho bạn</h1>
        <p className="text-sm text-on-surface-variant mt-1">
          Dựa trên{" "}
          <Link href="/profile" className="text-primary underline">hồ sơ du lịch</Link>{" "}
          của bạn.
        </p>
      </div>

      {/* Bộ lọc */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          className="rounded-lg border border-outline-variant/40 bg-surface-container-lowest px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40"
          value={district}
          onChange={(e) => setDistrict(e.target.value)}
        >
          <option value="">Tất cả quận</option>
          {DISTRICTS.map((d) => (
            <option key={d.slug} value={d.slug}>{d.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setIncludeHotels((v) => !v)}
          className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm border transition-colors ${
            includeHotels
              ? "bg-primary-container text-on-primary-container border-primary"
              : "border-outline-variant/40 text-on-surface-variant hover:border-primary/40"
          }`}
        >
          <span className="material-symbols-outlined text-base">hotel</span>
          Gồm khách sạn
        </button>
      </div>

      {/* Notes / relaxed */}
      {data?.notes?.length ? (
        <div className="space-y-1.5">
          {data.notes.map((note) => (
            <div
              key={note}
              className="flex items-start gap-2 rounded-lg bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-surface-variant"
            >
              <span className="material-symbols-outlined text-base text-secondary shrink-0">info</span>
              <span>{NOTE_LABELS[note] ?? note}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Kết quả */}
      {isLoading ? (
        <p className="text-sm text-on-surface-variant">Đang tải gợi ý…</p>
      ) : isError ? (
        <p className="text-sm text-error">Không tải được gợi ý. Thử lại sau.</p>
      ) : !data?.items.length ? (
        <div className="text-center py-12 text-on-surface-variant">
          <span className="material-symbols-outlined text-5xl opacity-40">travel_explore</span>
          <p className="mt-2 text-sm">Chưa có gợi ý. Hãy điền hồ sơ để nhận đề xuất phù hợp.</p>
          <Link href="/profile" className="inline-block mt-3 text-sm text-primary underline">
            Điền hồ sơ →
          </Link>
        </div>
      ) : (
        <div className="flex flex-wrap gap-3">
          {data.items.map((item) => {
            const src = recommendItemToSource(item);
            return (
              <SourceCard
                key={item.placeId}
                source={src}
                priceDisplay={item.priceDisplay}
                action={<FavoriteButton source={src} />}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
