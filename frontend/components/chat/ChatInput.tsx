"use client";
import { useRef, useState, KeyboardEvent } from "react";
import type { ChatStatus } from "@/hooks/useChat";

interface Props {
  status: ChatStatus;
  onSend: (message: string) => void;
  onStop: () => void;
  quickActions?: string[];
}

export function ChatInput({ status, onSend, onStop, quickActions }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isStreaming = status === "streaming" || status === "waiting";

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === "Escape" && isStreaming) onStop();
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }

  return (
    <div className="shrink-0 bg-surface/90 backdrop-blur-lg border-t border-outline-variant/20 px-4 py-3">
      <div className="max-w-4xl mx-auto space-y-3">
        {/* Quick action chips */}
        {quickActions && quickActions.length > 0 && (
          <div className="flex gap-2 overflow-x-auto hide-scrollbar pb-0.5">
            {quickActions.map((q) => (
              <button
                key={q}
                onClick={() => { setValue(q); textareaRef.current?.focus(); }}
                className="flex-none px-4 py-1.5 bg-surface-container-lowest border border-outline-variant/30 rounded-full text-xs text-primary hover:bg-primary-fixed transition-colors shadow-sm"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {/* Input row */}
        <div className="flex items-end gap-3">
          <div className="flex-1 bg-surface-container-high rounded-2xl flex items-end px-4 py-2 gap-2 shadow-inner focus-within:ring-2 focus-within:ring-primary/30 focus-within:bg-white transition-all">
            <textarea
              ref={textareaRef}
              placeholder="Nhập câu hỏi của bạn về Đà Nẵng..."
              value={value}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              rows={1}
              className="flex-1 resize-none bg-transparent border-none outline-none text-sm text-on-surface placeholder:text-on-surface-variant/60 min-h-[36px] max-h-32 py-1 leading-relaxed"
            />
          </div>

          {isStreaming ? (
            <button
              onClick={onStop}
              title="Dừng (Esc)"
              className="p-3 bg-error text-on-error rounded-xl shadow-md hover:shadow-lg active:scale-90 transition-all flex items-center justify-center shrink-0"
            >
              <span className="material-symbols-outlined text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                stop
              </span>
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!value.trim()}
              title="Gửi (Enter)"
              className="p-3 bg-primary text-on-primary rounded-xl shadow-md hover:shadow-lg active:scale-90 transition-all flex items-center justify-center shrink-0 disabled:opacity-40 disabled:shadow-none disabled:scale-100"
            >
              <span className="material-symbols-outlined text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                send
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
