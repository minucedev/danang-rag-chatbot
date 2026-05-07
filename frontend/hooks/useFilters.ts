"use client";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useCallback } from "react";

export interface Filters {
  district?: string;
  min_rating?: number;
  max_price?: number;
}

export function useFilters() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const filters: Filters = {
    district: params.get("district") ?? undefined,
    min_rating: params.has("min_rating") ? Number(params.get("min_rating")) : undefined,
    max_price: params.has("max_price") ? Number(params.get("max_price")) : undefined,
  };

  const setFilters = useCallback(
    (next: Partial<Filters>) => {
      const sp = new URLSearchParams(params.toString());
      Object.entries(next).forEach(([k, v]) => {
        if (v === undefined || v === null || v === "") sp.delete(k);
        else sp.set(k, String(v));
      });
      router.replace(`${pathname}?${sp.toString()}`, { scroll: false });
    },
    [params, router, pathname],
  );

  const resetFilters = useCallback(() => {
    router.replace(pathname, { scroll: false });
  }, [router, pathname]);

  return { filters, setFilters, resetFilters };
}
