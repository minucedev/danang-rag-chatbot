"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiDelete } from "@/lib/api";
import type { Source } from "@/lib/sourceAdapter";

export interface Favorite {
  id: number;
  pointId: string;
  collection: string;
  snapshot: Source;
  createdAt: number;
}

export function useFavoritesQuery() {
  return useQuery<{ items: Favorite[]; total: number }>({
    queryKey: ["favorites"],
    queryFn: () => apiFetch(`/api/favorites`),
    staleTime: 30_000,
  });
}

export function useAddFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { pointId: string; collection: string; snapshot: Source }) =>
      apiFetch("/api/favorites", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["favorites"] }),
  });
}

export function useRemoveFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (favoriteId: number) =>
      apiDelete(`/api/favorites/${favoriteId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["favorites"] }),
  });
}
