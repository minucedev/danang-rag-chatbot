"use client";
import { useEffect, useRef } from "react";
import { UserBubble, AssistantBubble } from "./MessageBubble";
import type { Message } from "@/hooks/useSessions";
import type { StreamingMessage } from "@/hooks/useChat";

interface Props {
  messages: Message[];
  streamingMsg: StreamingMessage | null;
}

export function MessageList({ messages, streamingMsg }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamingMsg?.content]);

  return (
    <div className="flex flex-col gap-4 py-4 px-4">
      {messages.map((m) =>
        m.role === "user" ? (
          <UserBubble key={m.id} content={m.content} />
        ) : (
          <AssistantBubble
            key={m.id}
            content={m.content}
            sources={m.sources}
            intent={m.intent}
          />
        ),
      )}
      {streamingMsg && (
        <AssistantBubble
          content={streamingMsg.content}
          sources={streamingMsg.sources}
          intent={streamingMsg.intent}
          isStreaming={streamingMsg.isStreaming}
        />
      )}
      <div ref={bottomRef} />
    </div>
  );
}
