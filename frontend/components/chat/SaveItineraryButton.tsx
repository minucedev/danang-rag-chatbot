"use client";
import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useCreateItinerary } from "@/hooks/useItineraries";

// Lấy tiêu đề mặc định từ heading/dòng đầu của markdown.
function defaultTitle(content: string): string {
  const firstLine = content.split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  return firstLine.replace(/^#+\s*/, "").replace(/[*_`]/g, "").slice(0, 80) || "Lịch trình của tôi";
}

export function SaveItineraryButton({
  content,
  sessionId,
}: {
  content: string;
  sessionId?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const create = useCreateItinerary();

  function onOpenChange(next: boolean) {
    if (next) setTitle(defaultTitle(content));
    setOpen(next);
  }

  async function handleSave() {
    const t = title.trim();
    if (!t) {
      toast.error("Nhập tiêu đề lịch trình.");
      return;
    }
    try {
      await create.mutateAsync({ title: t, contentMd: content, sessionId });
      toast.success("Đã lưu lịch trình");
      setOpen(false);
    } catch {
      toast.error("Lưu lịch trình thất bại");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 gap-1 text-xs w-fit">
          <span className="material-symbols-outlined text-sm">bookmark_add</span>
          Lưu lịch trình
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Lưu lịch trình</DialogTitle>
        </DialogHeader>
        <input
          className="w-full rounded-lg border border-outline-variant/40 bg-surface-container-lowest px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Tiêu đề lịch trình"
          maxLength={200}
          autoFocus
        />
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Huỷ</Button>
          <Button onClick={handleSave} disabled={create.isPending}>
            {create.isPending ? "Đang lưu…" : "Lưu"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
