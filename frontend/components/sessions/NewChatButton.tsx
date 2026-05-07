import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

export function NewChatButton() {
  const router = useRouter();
  return (
    <Button
      variant="outline"
      className="w-full justify-start gap-2"
      onClick={() => router.push("/chat")}
    >
      <Plus className="w-4 h-4" />
      Cuộc hội thoại mới
    </Button>
  );
}
