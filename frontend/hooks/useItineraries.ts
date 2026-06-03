"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiDelete } from "@/lib/api";
import { getClientId } from "@/lib/clientId";

export interface ItineraryListItem {
  id: number;
  title: string;
  createdAt: number;
  updatedAt: number;
}

export interface Itinerary {
  id: number;
  title: string;
  contentMd: string;
  sessionId?: string | null;
  createdAt: number;
  updatedAt: number;
}

export function useItinerariesQuery() {
  return useQuery<{ items: ItineraryListItem[]; total: number }>({
    queryKey: ["itineraries"],
    queryFn: () =>
      apiFetch(`/api/itineraries?clientId=${encodeURIComponent(getClientId())}`),
    staleTime: 30_000,
  });
}

export function useItineraryQuery(id: number | null) {
  return useQuery<Itinerary>({
    queryKey: ["itinerary", id],
    queryFn: () =>
      apiFetch(`/api/itineraries/${id}?clientId=${encodeURIComponent(getClientId())}`),
    enabled: id != null,
  });
}

export function useCreateItinerary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { title: string; contentMd: string; sessionId?: string | null }) =>
      apiFetch<Itinerary>("/api/itineraries", {
        method: "POST",
        body: JSON.stringify({ clientId: getClientId(), ...input }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["itineraries"] }),
  });
}

export function useDeleteItinerary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiDelete(`/api/itineraries/${id}?clientId=${encodeURIComponent(getClientId())}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["itineraries"] }),
  });
}
