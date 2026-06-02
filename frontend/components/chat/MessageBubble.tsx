import ReactMarkdown from "react-markdown";
import { IntentBadge } from "./IntentBadge";
import { SourceCardList } from "./SourceCardList";
import { Skeleton } from "@/components/ui/skeleton";

interface UserBubbleProps {
  content: string;
}

interface AssistantBubbleProps {
  content: string;
  sources?: Record<string, unknown>[] | null;
  intent?: string | null;
  isStreaming?: boolean;
}

export function UserBubble({ content }: UserBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] rounded-2xl chat-bubble-user bg-primary text-on-primary px-5 py-3 text-sm leading-relaxed shadow-sm">
        {content}
      </div>
    </div>
  );
}

export function AssistantBubble({ content, sources, intent, isStreaming }: AssistantBubbleProps) {
  return (
    <div className="flex gap-3 max-w-[88%]">
      {/* AI Avatar */}
      <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center shrink-0 shadow-md mt-1">
        <span
          className="material-symbols-outlined text-on-primary text-xl"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          smart_toy
        </span>
      </div>

      <div className="flex flex-col gap-2 min-w-0 flex-1">
        {intent && <IntentBadge value={intent} />}

        {/* Sources skeleton while streaming + no sources yet */}
        {isStreaming && !sources && (
          <div className="flex gap-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="w-60 h-32 rounded-xl shrink-0" />
            ))}
          </div>
        )}
        {sources && sources.length > 0 && <SourceCardList sources={sources} />}
        {sources && sources.length === 0 && !isStreaming && (
          <p className="text-xs text-on-surface-variant italic">
            Không tìm thấy kết quả phù hợp với bộ lọc hiện tại.
          </p>
        )}

        {/* Message bubble */}
        <div className="bg-surface-container-lowest border border-outline-variant/10 shadow-sm rounded-2xl chat-bubble-ai px-5 py-3 text-sm leading-relaxed prose prose-sm max-w-none">
          {content ? (
            <ReactMarkdown>{content}</ReactMarkdown>
          ) : isStreaming ? (
            <span className="inline-flex gap-1 py-1">
              <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce [animation-delay:300ms]" />
            </span>
          ) : null}
          {isStreaming && content && <span className="animate-pulse text-primary">▋</span>}
        </div>
      </div>
    </div>
  );
}
