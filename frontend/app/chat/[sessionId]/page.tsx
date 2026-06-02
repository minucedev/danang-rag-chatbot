"use client";
import { use, useState, Suspense } from "react";
import { FilterChips, FilterPanel } from "@/components/filters/FilterSidebar";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";
import { useFilters } from "@/hooks/useFilters";
import { useMessagesQuery } from "@/hooks/useSessions";

interface Props {
  params: Promise<{ sessionId: string }>;
}

function SessionView({ sessionId }: { sessionId: string }) {
  const { filters } = useFilters();
  const { send, stop, status, streamingMsg } = useChat(sessionId);
  const { data: messages = [] } = useMessagesQuery(sessionId);
  const [filterOpen, setFilterOpen] = useState(false);

  return (
    <div className="flex flex-col h-full">
      {/* Filter chips bar */}
      <div className="relative">
        <FilterChips onOpenFilter={() => setFilterOpen((v) => !v)} />
        {filterOpen && (
          <div className="absolute right-4 top-full mt-1 z-40">
            <FilterPanel onClose={() => setFilterOpen(false)} />
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} streamingMsg={streamingMsg} />
      </div>

      <ChatInput
        status={status}
        onSend={(text) => send(text, filters)}
        onStop={stop}
      />
    </div>
  );
}

export default function ChatSessionPage({ params }: Props) {
  const { sessionId } = use(params);
  return (
    <Suspense>
      <SessionView sessionId={sessionId} />
    </Suspense>
  );
}
