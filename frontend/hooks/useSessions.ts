"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiDelete } from "@/lib/api";

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
    queryKey: ["messages", sessionId],
    queryFn: () => apiFetch<Message[]>(`/api/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
    staleTime: 0,
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
