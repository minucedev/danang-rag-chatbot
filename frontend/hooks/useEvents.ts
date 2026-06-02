"use client";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

export interface EventItem {
  id: number;
  title: string;
  venue_name?: string | null;
  address?: string | null;
  district?: string | null;
  start_time?: number | null;
  time_display: string;
  url?: string | null;
  image_url?: string | null;
  description?: string | null;
}

export function useEventsQuery() {
  return useQuery<{ items: EventItem[]; total: number }>({
    queryKey: ["events"],
    queryFn: () => apiFetch("/api/events?days=60&limit=12"),
    staleTime: 5 * 60_000,
  });
}
