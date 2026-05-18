"use client";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch, apiDelete } from "@/lib/api";

const messagesKey = (sessionId: string | null) => ["messages", sessionId] as const;

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
}

export function useSessionsQuery() {
  return useQuery<Session[]>({
    queryKey: ["sessions"],
    queryFn: () => apiFetch("/api/sessions"),
    staleTime: 30_000,
  });
}

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      apiFetch<Session>("/api/sessions", { method: "POST", body: JSON.stringify({ title }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useRenameSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiFetch<Session>(`/api/sessions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useMessagesQuery(sessionId: string | null) {
  return useQuery({
    queryKey: messagesKey(sessionId),
    queryFn: () => apiFetch<Message[]>(`/api/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}

export interface Message {
  id: number;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  sources: Record<string, unknown>[] | null;
  intent: string | null;
  created_at: number;
}

// Upsert a message into the cached list owned by useMessagesQuery, keyed by id.
// Replace-in-place when the id exists so repeat writes (e.g. abort after done)
// stay idempotent instead of appending duplicates.
export function upsertMessage(qc: QueryClient, sessionId: string, msg: Message) {
  qc.setQueryData<Message[]>(messagesKey(sessionId), (old) => {
    const list = old ?? [];
    const idx = list.findIndex((m) => m.id === msg.id);
    if (idx >= 0) {
      const next = [...list];
      next[idx] = msg;
      return next;
    }
    return [...list, msg];
  });
}
