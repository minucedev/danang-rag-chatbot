"use client";
import { useEffect, useState, Suspense } from "react";
import { useRouter } from "next/navigation";
import { QuickReplies } from "@/components/chat/QuickReplies";
import { SuggestedEvents } from "@/components/chat/SuggestedEvents";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";
import { useFilters } from "@/hooks/useFilters";
import { useMessagesQuery } from "@/hooks/useSessions";

const WELCOME_QUICK_ACTIONS = [
  '"Khách sạn gần biển"',
  '"Dưới 1.5M VND"',
  '"Có hồ bơi"',
];

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
      <div className="flex-1 overflow-y-auto">
        {showWelcome ? (
          <div className="max-w-4xl mx-auto px-4 py-10 space-y-10">
            {/* Greeting section */}
            <section className="flex flex-col items-center text-center space-y-5">
              <div className="relative">
                <div className="w-24 h-24 bg-primary text-on-primary rounded-2xl flex items-center justify-center shadow-lg hover:scale-105 transition-transform duration-300">
                  <span
                    className="material-symbols-outlined text-5xl"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    smart_toy
                  </span>
                </div>
                <div className="absolute -bottom-1 -right-1 w-8 h-8 bg-secondary-container rounded-full border-4 border-background flex items-center justify-center shadow-sm">
                  <span className="material-symbols-outlined text-sm text-on-surface">bolt</span>
                </div>
              </div>
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-primary tracking-tight">
                  Xin chào! Tôi là trợ lý du lịch Đà Nẵng.
                </h2>
                <p className="text-on-surface-variant text-base">Bạn cần tìm gì hôm nay?</p>
              </div>
            </section>

            {/* Suggested events */}
            <SuggestedEvents onSelect={handleSend} />

            {/* Quick reply grid */}
            <QuickReplies onSelect={handleSend} />
          </div>
        ) : (
          <MessageList messages={messages} streamingMsg={streamingMsg} />
        )}
      </div>

      <ChatInput
        status={status}
        onSend={handleSend}
        onStop={stop}
        quickActions={showWelcome ? WELCOME_QUICK_ACTIONS : undefined}
      />
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
