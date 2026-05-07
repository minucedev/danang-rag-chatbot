"use client";
import { useRouter } from "next/navigation";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useRenameSession, useDeleteSession, type Session } from "@/hooks/useSessions";
import { cn } from "@/lib/utils";

interface Props {
  session: Session;
  isActive: boolean;
}

export function SessionItem({ session, isActive }: Props) {
  const router = useRouter();
  const rename = useRenameSession();
  const del = useDeleteSession();
  const [showMenu, setShowMenu] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [newTitle, setNewTitle] = useState(session.title);

  return (
    <>
      <div
        className={cn(
          "group flex items-center justify-between rounded-lg px-2 py-1.5 cursor-pointer hover:bg-accent text-sm",
          isActive && "bg-accent font-medium",
        )}
        onClick={() => router.push(`/chat/${session.id}`)}
      >
        <span className="truncate flex-1">{session.title}</span>
        <button
          className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-muted"
          onClick={(e) => { e.stopPropagation(); setShowMenu((v) => !v); }}
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
        </button>
      </div>

      {showMenu && (
        <div className="ml-2 flex flex-col gap-0.5">
          <button
            className="flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-accent"
            onClick={() => { setRenameOpen(true); setShowMenu(false); }}
          >
            <Pencil className="w-3 h-3" /> Đổi tên
          </button>
          <button
            className="flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-destructive/10 text-destructive"
            onClick={() => { setDeleteOpen(true); setShowMenu(false); }}
          >
            <Trash2 className="w-3 h-3" /> Xóa
          </button>
        </div>
      )}

      {/* Rename dialog */}
      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Đổi tên cuộc hội thoại</DialogTitle></DialogHeader>
          <input
            className="w-full border rounded px-3 py-2 text-sm"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && rename.mutate({ id: session.id, title: newTitle }, { onSuccess: () => setRenameOpen(false) })}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>Hủy</Button>
            <Button onClick={() => rename.mutate({ id: session.id, title: newTitle }, { onSuccess: () => setRenameOpen(false) })}>Lưu</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Xóa cuộc hội thoại?</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">Thao tác này không thể hoàn tác.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>Hủy</Button>
            <Button variant="destructive" onClick={() => del.mutate(session.id, { onSuccess: () => { setDeleteOpen(false); if (isActive) router.push("/chat"); } })}>Xóa</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
