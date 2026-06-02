import { QUICK_REPLIES } from "@/constants/quickReplies";

// Map emoji icons to Material Symbols
const ICON_MAP: Record<string, string> = {
  "🏨": "hotel",
  "🍜": "restaurant",
  "📍": "map",
  "⭐": "star",
  "💰": "payments",
  "🗺️": "route",
};

interface Props {
  onSelect: (text: string) => void;
}

export function QuickReplies({ onSelect }: Props) {
  return (
    <div className="px-4 py-2">
      <p className="text-sm font-semibold text-primary mb-3 px-1">Gợi ý tìm kiếm</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {QUICK_REPLIES.map((q) => {
          const materialIcon = ICON_MAP[q.icon] ?? "chat";
          return (
            <button
              key={q.text}
              onClick={() => onSelect(q.text)}
              className="flex items-center gap-3 p-4 bg-surface-container-lowest border border-outline-variant/20 rounded-xl text-left hover:border-primary/30 hover:bg-primary-fixed/30 transition-all group shadow-sm active:scale-[0.98]"
            >
              <div className="w-10 h-10 bg-primary-fixed rounded-lg flex items-center justify-center shrink-0 group-hover:bg-primary transition-colors">
                <span className="material-symbols-outlined text-xl text-primary group-hover:text-on-primary transition-colors">
                  {materialIcon}
                </span>
              </div>
              <span className="text-sm text-on-surface leading-snug line-clamp-2">{q.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
