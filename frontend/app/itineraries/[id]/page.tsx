"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { useItineraryQuery } from "@/hooks/useItineraries";
import { downloadMarkdown } from "@/lib/exportItinerary";

export default function ItineraryDetailPage() {
  const params = useParams();
  const id = Number(params?.id);
  const { data, isLoading, isError } = useItineraryQuery(Number.isFinite(id) ? id : null);

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
      {/* Thanh hành động — ẩn khi in */}
      <div className="flex items-center gap-2 print:hidden">
        <Link href="/saved">
          <Button variant="ghost" size="sm" className="h-8 gap-1">
            <span className="material-symbols-outlined text-base">arrow_back</span>
            Đã lưu
          </Button>
        </Link>
        {data && (
          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1"
              onClick={() => downloadMarkdown(data.title, data.contentMd)}
            >
              <span className="material-symbols-outlined text-base">download</span>
              Tải .md
            </Button>
            <Button size="sm" className="h-8 gap-1" onClick={() => window.print()}>
              <span className="material-symbols-outlined text-base">print</span>
              In / PDF
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <p className="text-sm text-on-surface-variant">Đang tải…</p>
      ) : isError || !data ? (
        <p className="text-sm text-error">Không tìm thấy lịch trình.</p>
      ) : (
        <article className="prose prose-sm max-w-none">
          <h1>{data.title}</h1>
          <ReactMarkdown>{data.contentMd}</ReactMarkdown>
        </article>
      )}
    </div>
  );
}
