import { QUICK_REPLIES } from "@/constants/quickReplies";

interface Props {
  onSelect: (text: string) => void;
}

export function QuickReplies({ onSelect }: Props) {
  return (
    <div className="px-4 py-2">
      <p className="text-xs text-muted-foreground mb-3">Gợi ý câu hỏi:</p>
      <div className="grid grid-cols-2 gap-2">
        {QUICK_REPLIES.map((q) => (
          <button
            key={q.text}
            onClick={() => onSelect(q.text)}
            className="flex items-start gap-2 rounded-xl border p-3 text-left text-sm hover:bg-muted transition-colors"
          >
            <span className="text-lg leading-none">{q.icon}</span>
            <span className="line-clamp-2">{q.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
