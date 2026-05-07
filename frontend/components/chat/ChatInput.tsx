"use client";
import { useRef, useState, KeyboardEvent } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Send, Square } from "lucide-react";
import type { ChatStatus } from "@/hooks/useChat";

interface Props {
  status: ChatStatus;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function ChatInput({ status, onSend, onStop }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isStreaming = status === "streaming" || status === "waiting";

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
    textareaRef.current?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === "Escape" && isStreaming) onStop();
  }

  return (
    <div className="flex gap-2 items-end p-4 border-t bg-background">
      <Textarea
        ref={textareaRef}
        placeholder="Hỏi về khách sạn, nhà hàng, địa điểm tại Đà Nẵng..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isStreaming}
        rows={1}
        className="resize-none flex-1 min-h-[40px] max-h-32 py-2"
      />
      {isStreaming ? (
        <Button variant="destructive" size="icon" onClick={onStop} title="Dừng (Esc)">
          <Square className="w-4 h-4" />
        </Button>
      ) : (
        <Button size="icon" onClick={handleSend} disabled={!value.trim()} title="Gửi (Enter)">
          <Send className="w-4 h-4" />
        </Button>
      )}
    </div>
  );
}
