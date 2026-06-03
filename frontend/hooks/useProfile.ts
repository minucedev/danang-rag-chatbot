"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiDelete, ApiError } from "@/lib/api";
import { useCreateSession } from "@/hooks/useSessions";
import { getStoredProfileSessionId, setStoredProfileSessionId } from "@/lib/clientId";
import type { Interest, Companions, BudgetLevel, Language } from "@/constants/profileOptions";

// Khớp UserProfile (camelCase, by_alias) ở backend/app/rag/schemas.py
export interface TripDates {
  start: string; // yyyy-mm-dd
  end: string;
}

export interface UserProfile {
  displayName?: string | null;
  tripDates?: TripDates | null;
  durationDays?: number | null;
  companions?: Companions | null;
  budgetLevel?: BudgetLevel | null;
  interests: Interest[];
  dietary?: string | null;
  language: Language;
}

const profileKey = (sessionId: string | null) => ["profile", sessionId] as const;

export function useProfileQuery(sessionId: string | null) {
  return useQuery<UserProfile | null>({
    queryKey: profileKey(sessionId),
    queryFn: async () => {
      try {
        return await apiFetch<UserProfile>(`/api/profile/${sessionId}`);
      } catch (e) {
        // 404 = chưa có hồ sơ → null (không phải lỗi). Các lỗi khác vẫn ném.
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}

export function useUpsertProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, profile }: { sessionId: string; profile: UserProfile }) =>
      apiFetch<UserProfile>(`/api/profile/${sessionId}`, {
        method: "PUT",
        body: JSON.stringify(profile),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: profileKey(vars.sessionId) });
      qc.invalidateQueries({ queryKey: ["recommend", vars.sessionId] });
    },
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => apiDelete(`/api/profile/${sessionId}`),
    onSuccess: (_data, sessionId) => {
      qc.invalidateQueries({ queryKey: profileKey(sessionId) });
      qc.invalidateQueries({ queryKey: ["recommend", sessionId] });
    },
  });
}

// Ghim 1 session "hồ sơ" ổn định (localStorage) để Profile + Recommend dùng chung,
// tạo mới nếu chưa có. Trả null cho tới khi sẵn sàng.
export function useProfileSession(): string | null {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const create = useCreateSession();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // setState trong callback async (không đồng bộ trong effect body) + chạy sau mount
    // → tránh hydration mismatch khi đọc localStorage.
    Promise.resolve(getStoredProfileSessionId()).then((stored) => {
      if (stored) {
        setSessionId(stored);
        return;
      }
      return create.mutateAsync("Hồ sơ của tôi").then((s) => {
        setStoredProfileSessionId(s.id);
        setSessionId(s.id);
      });
    });
  }, [create]);

  return sessionId;
}
