"use client";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { streamSSE } from "@/lib/sse";
import { normalizeNFC } from "@/lib/nfc";
import type { Filters } from "./useFilters";
import { upsertMessage } from "./useSessions";

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
      let userMsgId: number | undefined;
      let asstMsgId: number | undefined;
      let curIntent: string | null = null;
      let curSources: Record<string, unknown>[] | null = null;
      let tokens = "";

      // The stream is the source of truth — write it straight into the query
      // cache so a remount/refetch can't blank the message before the backend
      // commits it. Ids come from the backend `meta` event (always present).
      const seedUserMessage = (sid: string) => {
        if (userMsgId == null) return;
        upsertMessage(qc, sid, {
          id: userMsgId,
          session_id: sid,
          role: "user",
          content: message,
          sources: null,
          intent: null,
          created_at: Date.now(),
        });
      };

      const writeAssistant = (finalContent: string) => {
        if (!sessionIdUsed || asstMsgId == null) return;
        upsertMessage(qc, sessionIdUsed, {
          id: asstMsgId,
          session_id: sessionIdUsed,
          role: "assistant",
          content: finalContent,
          sources: curSources,
          intent: curIntent,
          created_at: Date.now(),
        });
      };

      try {
        const stream = streamSSE(
          "/api/chat/stream",
          { session_id: sessionIdUsed, message, filters },
          abortRef.current.signal,
        );

        for await (const event of stream) {
          switch (event.type) {
            case "meta": {
              const sid = event.data.session_id as string;
              userMsgId = event.data.user_message_id as number | undefined;
              asstMsgId = event.data.assistant_message_id as number | undefined;
              if (sid !== sessionIdUsed) {
                setCurrentSessionId(sid);
                sessionIdUsed = sid;
              }
              seedUserMessage(sid);
              qc.invalidateQueries({ queryKey: ["sessions"] });
              break;
            }
            case "waiting":
              setStatus("waiting");
              break;
            case "intent":
              curIntent = event.data.value as string;
              setStreamingMsg((prev) => prev ? { ...prev, intent: curIntent } : prev);
              setStatus("streaming");
              break;
            case "sources":
              curSources = event.data.items as Record<string, unknown>[];
              setStreamingMsg((prev) => prev ? { ...prev, sources: curSources } : prev);
              break;
            case "token":
              tokens += event.data.text as string;
              setStreamingMsg((prev) => prev ? { ...prev, content: tokens } : prev);
              break;
            case "done":
              writeAssistant(tokens);
              setStreamingMsg(null);
              break;
            case "error":
              throw new Error(event.data.message as string);
          }
        }
      } catch (err: unknown) {
        if ((err as Error)?.name === "AbortError") {
          writeAssistant(tokens || "(Đã dừng)");
          setStreamingMsg(null);
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
          qc.invalidateQueries({ queryKey: ["sessions"] });
        }
      }
    },
    [status, currentSessionId, qc],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { send, stop, status, streamingMsg, currentSessionId };
}
