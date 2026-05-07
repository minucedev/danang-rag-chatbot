"use client";
import { use, Suspense } from "react";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
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

  return (
    <div className="flex flex-col h-full">
      <div className="border-b px-4 py-3 flex items-center justify-between shrink-0">
        <span className="font-semibold text-sm">Trợ lý du lịch Đà Nẵng</span>
        <FilterSidebar />
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
