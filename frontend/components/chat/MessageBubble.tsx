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
      <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-blue-600 text-white px-4 py-2.5 text-sm">
        {content}
      </div>
    </div>
  );
}

export function AssistantBubble({ content, sources, intent, isStreaming }: AssistantBubbleProps) {
  return (
    <div className="flex flex-col gap-2 max-w-[85%]">
      {intent && <IntentBadge value={intent} />}

      {/* Sources skeleton while streaming + no sources yet */}
      {isStreaming && !sources && (
        <div className="flex gap-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="w-56 h-28 rounded-lg shrink-0" />)}
        </div>
      )}
      {sources && sources.length > 0 && <SourceCardList sources={sources} />}
      {sources && sources.length === 0 && !isStreaming && (
        <p className="text-xs text-muted-foreground italic">Không tìm thấy kết quả phù hợp với bộ lọc hiện tại.</p>
      )}

      <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm prose prose-sm max-w-none dark:prose-invert">
        {content ? (
          <ReactMarkdown>{content}</ReactMarkdown>
        ) : isStreaming ? (
          <span className="inline-flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
          </span>
        ) : null}
        {isStreaming && content && <span className="animate-pulse">▋</span>}
      </div>
    </div>
  );
}
