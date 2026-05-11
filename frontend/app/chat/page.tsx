"use client";
import { useEffect, useState, Suspense } from "react";
import { useRouter } from "next/navigation";
import { MessageSquare } from "lucide-react";
import { QuickReplies } from "@/components/chat/QuickReplies";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
import { useChat } from "@/hooks/useChat";
import { useFilters } from "@/hooks/useFilters";
import { useMessagesQuery } from "@/hooks/useSessions";

function NewChatView() {
  const router = useRouter();
  const { filters } = useFilters();
  const { send, stop, status, streamingMsg, currentSessionId } = useChat(null);
  const { data: messages = [] } = useMessagesQuery(currentSessionId);
  const [hasSent, setHasSent] = useState(false);

  const handleSend = (text: string) => {
    setHasSent(true);
    send(text, filters);
  };

  useEffect(() => {
    if (hasSent && status === "idle" && currentSessionId) {
      router.replace(`/chat/${currentSessionId}`);
    }
  }, [hasSent, status, currentSessionId, router]);

  const showWelcome = !hasSent;

  return (
    <div className="flex flex-col h-full">
      <div className="border-b px-4 py-3 flex items-center justify-between shrink-0">
        <span className="font-semibold text-sm">Trợ lý du lịch Đà Nẵng</span>
        <FilterSidebar />
      </div>

      <div className="flex-1 overflow-y-auto">
        {showWelcome ? (
          <div className="flex flex-col items-center justify-center h-full gap-6 p-8">
            <div className="text-center space-y-2">
              <MessageSquare className="w-12 h-12 text-blue-600 mx-auto" />
              <h2 className="text-xl font-semibold">Xin chào!</h2>
              <p className="text-muted-foreground text-sm">
                Tôi là trợ lý du lịch Đà Nẵng. Bạn cần tìm gì hôm nay?
              </p>
            </div>
            <div className="w-full max-w-2xl">
              <QuickReplies onSelect={handleSend} />
            </div>
          </div>
        ) : (
          <MessageList messages={messages} streamingMsg={streamingMsg} />
        )}
      </div>

      <ChatInput status={status} onSend={handleSend} onStop={stop} />
    </div>
  );
}

export default function NewChatPage() {
  return (
    <Suspense>
      <NewChatView />
    </Suspense>
  );
}
