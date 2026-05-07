"use client";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { streamSSE } from "@/lib/sse";
import { normalizeNFC } from "@/lib/nfc";
import type { Filters } from "./useFilters";
import type { Message } from "./useSessions";

export type ChatStatus = "idle" | "streaming" | "waiting" | "error";

export interface StreamingMessage {
  role: "assistant";
  content: string;
  sources: Record<string, unknown>[] | null;
  intent: string | null;
  isStreaming: boolean;
}

export function useChat(sessionId: string | null) {
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [streamingMsg, setStreamingMsg] = useState<StreamingMessage | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(sessionId);

  const send = useCallback(
    async (rawMessage: string, filters: Filters) => {
      if (status === "streaming") return;
      const message = normalizeNFC(rawMessage.trim());
      if (!message) return;

      abortRef.current = new AbortController();
      setStatus("streaming");
      setStreamingMsg({ role: "assistant", content: "", sources: null, intent: null, isStreaming: true });

      let sessionIdUsed = currentSessionId;

      try {
        const stream = streamSSE(
          "/api/chat/stream",
          { session_id: sessionIdUsed, message, filters },
          abortRef.current.signal,
        );

        let tokens = "";

        for await (const event of stream) {
          switch (event.type) {
            case "meta": {
              const sid = event.data.session_id as string;
              if (sid !== sessionIdUsed) {
                setCurrentSessionId(sid);
                sessionIdUsed = sid;
              }
              qc.invalidateQueries({ queryKey: ["sessions"] });
              break;
            }
            case "waiting":
              setStatus("waiting");
              break;
            case "intent":
              setStreamingMsg((prev) => prev ? { ...prev, intent: event.data.value as string } : prev);
              setStatus("streaming");
              break;
            case "sources":
              setStreamingMsg((prev) =>
                prev ? { ...prev, sources: event.data.items as Record<string, unknown>[] } : prev,
              );
              break;
            case "token":
              tokens += event.data.text as string;
              setStreamingMsg((prev) => prev ? { ...prev, content: tokens } : prev);
              break;
            case "done":
              setStreamingMsg((prev) => prev ? { ...prev, isStreaming: false } : prev);
              break;
            case "error":
              throw new Error(event.data.message as string);
          }
        }
      } catch (err: unknown) {
        if ((err as Error)?.name === "AbortError") {
          setStreamingMsg((prev) => prev ? { ...prev, content: prev.content || "(Đã dừng)", isStreaming: false } : prev);
        } else {
          const msg = (err as Error)?.message ?? "Lỗi không xác định";
          toast.error("Lỗi chat", { description: msg });
          setStatus("error");
          setStreamingMsg(null);
          console.error("Chat error:", err);
        }
      } finally {
        setStatus("idle");
        if (sessionIdUsed) {
          qc.invalidateQueries({ queryKey: ["messages", sessionIdUsed] });
          qc.invalidateQueries({ queryKey: ["sessions"] });
        }
        // Clear streaming message after persisted messages reload
        setTimeout(() => setStreamingMsg(null), 300);
      }
    },
    [status, currentSessionId, qc],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { send, stop, status, streamingMsg, currentSessionId };
}
