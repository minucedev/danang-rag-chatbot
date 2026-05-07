import { Badge } from "@/components/ui/badge";
import { intentLabel } from "@/lib/format";

export function IntentBadge({ value }: { value: string }) {
  return (
    <Badge variant="secondary" className="text-xs font-normal gap-1">
      <span className="animate-pulse w-1.5 h-1.5 rounded-full bg-blue-400 inline-block" />
      Đang tìm: {intentLabel(value)}
    </Badge>
  );
}
