"use client";
import { useState } from "react";
import { SourceCard } from "./SourceCard";
import { FavoriteButton } from "./FavoriteButton";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { Source } from "@/lib/sourceAdapter";

interface Props {
  sources: Record<string, unknown>[];
}

const VISIBLE = 5;

export function SourceCardList({ sources }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (!sources.length) return null;

  const shown = expanded ? sources : sources.slice(0, VISIBLE);

  return (
    <div className="mt-2 space-y-2">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {shown.map((s, i) => (
          <SourceCard
            key={i}
            source={s as Source}
            action={<FavoriteButton source={s as Source} />}
          />
        ))}
      </div>
      {sources.length > VISIBLE && (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 text-xs gap-1"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? <><ChevronUp className="w-3 h-3" />Thu gọn</> : <><ChevronDown className="w-3 h-3" />Xem thêm {sources.length - VISIBLE} kết quả</>}
        </Button>
      )}
    </div>
  );
}
