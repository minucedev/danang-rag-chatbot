"use client";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { UserProfile } from "@/hooks/useProfile";

// Khớp RecommendItem (camelCase, by_alias) ở backend/app/rag/schemas.py
export interface RecommendItem {
  placeId: string;
  name: string;
  collection: string;
  district: string;
  rating?: number | null;
  ratingDisplay: string;
  priceDisplay: string;
  address: string;
  recommendScore: number;
  matchedInterests: string[];
}

export interface RecommendResponse {
  items: RecommendItem[];
  profileUsed: UserProfile;
  relaxed: boolean;
  notes: string[];
}

export function useRecommendQuery(params: {
  sessionId: string | null;
  district?: string;
  includeHotels?: boolean;
  limit?: number;
}) {
  const { sessionId, district, includeHotels = false, limit = 12 } = params;
  return useQuery<RecommendResponse>({
    queryKey: ["recommend", sessionId, district ?? null, includeHotels, limit],
    queryFn: () =>
      apiFetch("/api/recommend", {
        method: "POST",
        body: JSON.stringify({ sessionId, district, includeHotels, limit }),
      }),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}
