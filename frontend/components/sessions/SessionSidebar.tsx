"use client";
import { useParams } from "next/navigation";
import { useSessionsQuery } from "@/hooks/useSessions";
import { relativeDate } from "@/lib/format";
import { NewChatButton } from "./NewChatButton";
import { SessionItem } from "./SessionItem";
import { Separator } from "@/components/ui/separator";
import { MessageSquare } from "lucide-react";

export function SessionSidebar() {
  const { data: sessions = [] } = useSessionsQuery();
  const params = useParams();
  const activeId = params?.sessionId as string | undefined;

  // Group by day
  const groups: Record<string, typeof sessions> = {};
  for (const s of sessions) {
    const label = relativeDate(s.updated_at);
    (groups[label] ??= []).push(s);
  }

  return (
    <aside className="flex flex-col h-full w-64 border-r bg-background px-3 py-4 gap-4">
      <div className="flex items-center gap-2 px-1">
        <MessageSquare className="w-5 h-5 text-blue-600" />
        <span className="font-semibold text-sm">Đà Nẵng Travel</span>
      </div>
      <NewChatButton />
      <Separator />
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {Object.entries(groups).map(([label, items]) => (
          <div key={label}>
            <p className="text-xs text-muted-foreground px-2 mb-1">{label}</p>
            <div className="space-y-0.5">
              {items.map((s) => (
                <SessionItem key={s.id} session={s} isActive={s.id === activeId} />
              ))}
            </div>
          </div>
        ))}
        {sessions.length === 0 && (
          <p className="text-xs text-muted-foreground px-2">Chưa có cuộc hội thoại nào.</p>
        )}
      </div>
    </aside>
  );
}
